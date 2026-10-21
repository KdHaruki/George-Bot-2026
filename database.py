"""Shared PostgreSQL connection and error handling for persistent Bot features."""
import os
from contextlib import contextmanager


class MemoryUnavailable(Exception):
    pass


class DatabaseStore:
    def __init__(self, url=None):
        self.url = os.getenv("DATABASE_URL", "").strip() if url is None else url

    @contextmanager
    def connect(self):
        if not self.url:
            raise MemoryUnavailable("保存機能にはDATABASE_URLの設定が必要だぜ。")
        try:
            import psycopg
            with psycopg.connect(self.url, connect_timeout=10) as connection:
                connection.execute("SET LOCAL statement_timeout = '10s'")
                yield connection
        except (MemoryUnavailable, ValueError):
            raise
        except Exception:
            raise MemoryUnavailable("保存先に接続できなかったぜ。管理者に設定を確認してもらってくれ。") from None

    def ping(self):
        with self.connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1
