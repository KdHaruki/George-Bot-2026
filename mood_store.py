"""Postgres persistence; credentials are never printed."""
import os


class MoodStore:
    def __init__(self, url=None):
        self.url = os.getenv("DATABASE_URL", "").strip() if url is None else url

    def _connect(self):
        import psycopg
        return psycopg.connect(self.url, connect_timeout=10, options="-c statement_timeout=10000")

    def load(self):
        if not self.url:
            return []
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS george_mood (
                channel_id BIGINT PRIMARY KEY,
                confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
                confusion INTEGER NOT NULL CHECK (confusion BETWEEN 0 AND 100),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            return connection.execute("SELECT channel_id, confidence, confusion FROM george_mood ORDER BY updated_at DESC LIMIT 512").fetchall()

    def save(self, channel_id, confidence, confusion):
        if not self.url:
            return
        with self._connect() as connection:
            connection.execute("""INSERT INTO george_mood (channel_id, confidence, confusion)
                VALUES (%s, %s, %s) ON CONFLICT (channel_id) DO UPDATE
                SET confidence = EXCLUDED.confidence, confusion = EXCLUDED.confusion, updated_at = NOW()""",
                               (channel_id, confidence, confusion))

    def get(self, channel_id):
        if not self.url:
            return None
        with self._connect() as connection:
            return connection.execute("SELECT confidence, confusion FROM george_mood WHERE channel_id = %s", (channel_id,)).fetchone()
