"""Postgres persistence; credentials are never printed."""
import os
from contextlib import contextmanager


def database_error_reason(exc):
    message = str(exc).lower()
    state = getattr(exc, "sqlstate", None)
    if isinstance(exc, ModuleNotFoundError):
        return "missing_psycopg_dependency"
    if "unsupported startup parameter" in message:
        return "unsupported_startup_parameter"
    if state == "28P01" or "password authentication failed" in message:
        return "invalid_database_password"
    if state == "42501":
        return "insufficient_database_permission"
    if "invalid" in message and ("dsn" in message or "connection option" in message):
        return "invalid_database_url"
    if "timeout" in message or "timed out" in message:
        return "database_timeout"
    if "could not translate host" in message or "name or service not known" in message:
        return "database_dns_failure"
    return "database_connection_or_query_error"


class MoodStore:
    def __init__(self, url=None):
        self.url = os.getenv("DATABASE_URL", "").strip() if url is None else url

    @contextmanager
    def _connect(self):
        import psycopg
        # PgBouncer may reject statement_timeout in the startup packet.
        # SET LOCAL scopes the timeout to this transaction, including on a pooler.
        with psycopg.connect(self.url, connect_timeout=10) as connection:
            connection.execute("SET LOCAL statement_timeout = '10s'")
            yield connection

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
