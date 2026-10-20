from contextlib import contextmanager
from presents import PresentStore
from title_core import change_streak, refresh_affection, record_event
from daily_affection import settle_daily
from title_core import pending_titles, COMMON
import json
from datetime import datetime, timezone
from quiz_rounds import expire_round
from favorite_album import record_completions, collection_targets
from progress_profiles import profile_for


class TitleStore(PresentStore):
    def pending(self, user_id, earned):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            row = conn.execute('SELECT data FROM george_title_stats WHERE user_id=%s', (user_id,)).fetchone()
            state = json.loads(row[0]) if row else {}
            people = conn.execute('SELECT character FROM george_affection WHERE user_id=%s AND points>=100', (user_id,)).fetchall()
            character = self.current_character(conn, user_id, required=False)
            streak = conn.execute('SELECT character,since FROM george_title_streaks WHERE user_id=%s', (user_id,)).fetchone()
            days = 0
            if streak and streak[0] == character:
                since = streak[1] if isinstance(streak[1], datetime) else datetime.fromisoformat(streak[1])
                since = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since
                days = max(0, (datetime.now(timezone.utc) - since).days)
            return pending_titles({row[0] for row in earned}, state, len(people), character, days)

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
            record_completions(conn, user_id, collection_targets())
            # Existing album dates prove past registrations; no historical guesses.
            registrations = conn.execute('SELECT character FROM george_favorite_album WHERE user_id=%s AND first_registered_at IS NOT NULL', (user_id,)).fetchall()
            stats = conn.execute('SELECT data FROM george_title_stats WHERE user_id=%s', (user_id,)).fetchone()
            counted = set(json.loads(stats[0]).get('favorite_worlds', [])) if stats else set()
            worlds = {profile['progressWorld'] for (name,) in registrations if (profile := profile_for(name))}
            for world in sorted(worlds - counted):
                record_event(conn, user_id, f'favorite-world-history:{world}', 'favorite_world', world=world)
            refresh_affection(conn, user_id)
            character = self.current_character(conn, user_id, required=False)
            change_streak(conn, user_id, character)
            rows = conn.execute("SELECT title_key,name,acquired_at FROM george_titles WHERE user_id=%s AND title_key<>'exchange10' ORDER BY name,title_key", (user_id,)).fetchall()
            result = []
            for key, name, acquired in rows:
                current_name = COMMON.get(key, name)
                if current_name != name:
                    conn.execute('UPDATE george_titles SET name=%s WHERE user_id=%s AND title_key=%s', (current_name, user_id, key))
                result.append((key, current_name, acquired))
            return sorted(result, key=lambda row: (row[1], row[0]))

    def world_search(self, user_id, interaction_id, world):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            record_event(conn, user_id, f'world:{interaction_id}', 'world', world=world)

    def profile_search(self, user_id, interaction_id, character):
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
            return row[0] if row else None

    def retire_exchange(self, guild_id, role_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM george_title_equipped WHERE guild_id=%s AND title_key='exchange10'", (guild_id,))
            conn.execute("DELETE FROM george_title_roles WHERE guild_id=%s AND title_key='exchange10' AND role_id=%s", (guild_id, role_id))
