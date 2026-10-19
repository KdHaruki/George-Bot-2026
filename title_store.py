from contextlib import contextmanager
from presents import PresentStore
from title_core import change_streak, refresh_affection, record_event


class TitleStore(PresentStore):
    @contextmanager
    def connect(self):
        with super().connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS george_title_settings (
                    guild_id BIGINT PRIMARY KEY, enabled BOOLEAN NOT NULL)''')
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
            refresh_affection(conn, user_id)
            character = self.current_character(conn, user_id, required=False)
            change_streak(conn, user_id, character)
            return conn.execute('SELECT title_key,name,acquired_at FROM george_titles WHERE user_id=%s ORDER BY name,title_key', (user_id,)).fetchall()

    def world_search(self, user_id, interaction_id, world):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            record_event(conn, user_id, f'world:{interaction_id}', 'world', world=world)

    def enabled(self, guild_id):
        with self.connect() as conn:
            row = conn.execute('SELECT enabled FROM george_title_settings WHERE guild_id=%s', (guild_id,)).fetchone()
            return bool(row and row[0])

    def configure(self, guild_id, enabled):
        with self.connect() as conn:
            conn.execute('''INSERT INTO george_title_settings VALUES (%s,%s)
                ON CONFLICT(guild_id) DO UPDATE SET enabled=EXCLUDED.enabled''', (guild_id, enabled))

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
