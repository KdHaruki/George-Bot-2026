import json
from contextlib import contextmanager
from presents import PresentStore
from title_core import refresh_affection, record_event, grant, FORTUNE_TYPES
from daily_affection import settle_daily
from title_core import pending_titles, current_title_name, is_retired_title, refresh_collection_titles, refresh_registration_title, title_sort_key, refresh_preferred_titles
from quiz_rounds import expire_round
from progress_profiles import profile_for, character_key


class TitleStore(PresentStore):
    def pending(self, user_id, earned):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            row = conn.execute('SELECT data FROM george_title_stats WHERE user_id=%s', (user_id,)).fetchone()
            state = json.loads(row[0]) if row else {}
            people = conn.execute('SELECT character FROM george_affection WHERE user_id=%s AND points>=100', (user_id,)).fetchall()
            character = self.current_character(conn, user_id, required=False)
            return pending_titles({row[0] for row in earned}, state, len(people), character)

    @contextmanager
    def connect(self):
        with super().connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS george_title_roles (
                    guild_id BIGINT NOT NULL, title_key TEXT NOT NULL, role_id BIGINT NOT NULL,
                    PRIMARY KEY(guild_id,title_key), UNIQUE(guild_id,role_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS george_title_equipped (
                    guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, title_key TEXT NOT NULL,
                    role_id BIGINT NOT NULL, PRIMARY KEY(guild_id,user_id))''')
            yield conn

    def titles(self, user_id):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            settle_daily(conn, user_id)
            expire_round(conn, user_id)
            stats = conn.execute('SELECT data FROM george_title_stats WHERE user_id=%s', (user_id,)).fetchone()
            if stats and set(json.loads(stats[0]).get('worlds', [])) >= set('青黒赤白緑'):
                grant(conn, user_id, 'worlds')
            if stats and set(json.loads(stats[0]).get('fortunes_seen', [])) >= FORTUNE_TYPES:
                grant(conn, user_id, 'fortune_set')
            if stats and len({character_key(name) for name in json.loads(stats[0]).get('profile_names', [])}) >= 10:
                grant(conn, user_id, 'named10')
            if stats and json.loads(stats[0]).get('special_gift_given'):
                grant(conn, user_id, 'special_gift')
            refresh_preferred_titles(conn, user_id)
            refresh_affection(conn, user_id)
            refresh_collection_titles(conn, user_id)
            refresh_registration_title(conn, user_id)
            rows = conn.execute("SELECT title_key,name,acquired_at FROM george_titles WHERE user_id=%s AND title_key<>'exchange10' AND title_key NOT LIKE %s ORDER BY name,title_key", (user_id, 'collection:%')).fetchall()
            result = []
            for key, name, acquired in rows:
                if is_retired_title(key):
                    continue
                current_name = current_title_name(key, name)
                if current_name != name:
                    conn.execute('UPDATE george_titles SET name=%s WHERE user_id=%s AND title_key=%s', (current_name, user_id, key))
                result.append((key, current_name, acquired))
            return sorted(result, key=title_sort_key)

    def world_search(self, user_id, interaction_id, world):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            record_event(conn, user_id, f'world:{interaction_id}', 'world', world=world)

    def named_profile_search(self, user_id, interaction_id, character):
        profile = profile_for(character)
        if not profile:
            return
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            record_event(conn, user_id, f'profile:{interaction_id}', 'profile_search', character=profile['progressName'])

    def role_map(self, guild_id):
        with self.connect() as conn:
            return dict(conn.execute('SELECT title_key,role_id FROM george_title_roles WHERE guild_id=%s', (guild_id,)).fetchall())

    def bind_role(self, guild_id, key, role_id, previous=None):
        with self.connect() as conn:
            conn.execute('''INSERT INTO george_title_roles VALUES (%s,%s,%s)
                ON CONFLICT(guild_id,title_key) DO NOTHING''', (guild_id, key, role_id))
            if previous is not None:
                conn.execute('''UPDATE george_title_roles SET role_id=%s
                    WHERE guild_id=%s AND title_key=%s AND role_id=%s''', (role_id, guild_id, key, previous))
            return conn.execute('SELECT role_id FROM george_title_roles WHERE guild_id=%s AND title_key=%s', (guild_id, key)).fetchone()[0]

    def save_equipped(self, guild_id, user_id, key=None, role_id=None):
        with self.connect() as conn:
            if key is None:
                conn.execute('DELETE FROM george_title_equipped WHERE guild_id=%s AND user_id=%s', (guild_id, user_id))
            else:
                conn.execute('''INSERT INTO george_title_equipped VALUES (%s,%s,%s,%s)
                    ON CONFLICT(guild_id,user_id) DO UPDATE SET title_key=EXCLUDED.title_key,role_id=EXCLUDED.role_id''',
                    (guild_id, user_id, key, role_id))

    def equipped(self, guild_id, user_id):
        with self.connect() as conn:
            row = conn.execute('SELECT title_key FROM george_title_equipped WHERE guild_id=%s AND user_id=%s', (guild_id, user_id)).fetchone()
            return row[0] if row and not is_retired_title(row[0]) else None

    def retire_exchange(self, guild_id, role_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM george_title_equipped WHERE guild_id=%s AND title_key='exchange10'", (guild_id,))
            conn.execute("DELETE FROM george_title_roles WHERE guild_id=%s AND title_key='exchange10' AND role_id=%s", (guild_id, role_id))

    def retire_collection(self, guild_id, key, role_id):
        if not key.startswith('collection:'):
            raise ValueError('Not a retired collection title')
        with self.connect() as conn:
            conn.execute('DELETE FROM george_title_equipped WHERE guild_id=%s AND title_key=%s AND role_id=%s', (guild_id, key, role_id))
            conn.execute('DELETE FROM george_title_roles WHERE guild_id=%s AND title_key=%s AND role_id=%s', (guild_id, key, role_id))

    def retire_title(self, guild_id, key, role_id):
        if not is_retired_title(key):
            raise ValueError('Not a retired title')
        with self.connect() as conn:
            conn.execute('DELETE FROM george_title_equipped WHERE guild_id=%s AND title_key=%s AND role_id=%s', (guild_id, key, role_id))
            conn.execute('DELETE FROM george_title_roles WHERE guild_id=%s AND title_key=%s AND role_id=%s', (guild_id, key, role_id))
