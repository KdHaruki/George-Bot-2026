"""Explicit user notes stored separately from conversation history."""
import os
from contextlib import contextmanager


class MemoryUnavailable(Exception):
    pass


class MemoryStore:
    def __init__(self, url=None):
        self.url = os.getenv("DATABASE_URL", "").strip() if url is None else url

    @contextmanager
    def connect(self):
        if not self.url:
            raise MemoryUnavailable("登録記憶にはDATABASE_URLの設定が必要だぜ。")
        try:
            import psycopg
            with psycopg.connect(self.url, connect_timeout=10) as connection:
                connection.execute("SET LOCAL statement_timeout = '10s'")
                connection.execute("""CREATE TABLE IF NOT EXISTS george_memories (
                    scope_id BIGINT NOT NULL, owner_id BIGINT NOT NULL,
                    title TEXT NOT NULL, content TEXT NOT NULL,
                    PRIMARY KEY (scope_id, owner_id, title))""")
                yield connection
        except (MemoryUnavailable, ValueError):
            raise
        except Exception:
            raise MemoryUnavailable("登録記憶の保存先に接続できなかったぜ。管理者に設定を確認してもらってくれ。") from None

    def list(self, scope_id, owner_id):
        with self.connect() as connection:
            return connection.execute("SELECT title, content FROM george_memories WHERE scope_id=%s AND owner_id=%s ORDER BY title", (scope_id, owner_id)).fetchall()

    def ping(self):
        with self.connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

    def save(self, scope_id, owner_id, title, content):
        title, content = title.strip(), content.strip()
        if not 1 <= len(title) <= 40 or not 1 <= len(content) <= 300:
            raise ValueError("タイトルは1〜40文字、内容は1〜300文字で頼むぜ。")
        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"george-memory:{scope_id}:{owner_id}",))
            rows = connection.execute("SELECT title FROM george_memories WHERE scope_id=%s AND owner_id=%s", (scope_id, owner_id)).fetchall()
            if len(rows) >= 20 and title not in {row[0] for row in rows}:
                raise ValueError("登録は20件までだぜ。不要な記憶を削除してくれ。")
            connection.execute("""INSERT INTO george_memories VALUES (%s,%s,%s,%s)
                ON CONFLICT (scope_id,owner_id,title) DO UPDATE SET content=EXCLUDED.content""", (scope_id, owner_id, title, content))

    def delete(self, scope_id, owner_id, title):
        with self.connect() as connection:
            result = connection.execute("DELETE FROM george_memories WHERE scope_id=%s AND owner_id=%s AND title=%s", (scope_id, owner_id, title.strip()))
            return result.rowcount > 0
