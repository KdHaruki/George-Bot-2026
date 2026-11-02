"""データ保存で共用するPostgreSQLへの接続とエラー処理を提供する。"""

import os
from contextlib import contextmanager


class MemoryUnavailable(Exception):
    """保存先を利用できない時の共通例外。既存呼び出しとの互換性のため名称を維持する。"""
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
                # 接続プールでも使えるよう、接続時optionsではなく取引内に設定する。
                yield connection
        except (MemoryUnavailable, ValueError):
            raise
        except Exception:
            # 接続URLやパスワードを含むドライバーの生エラーは外に出さない。
            raise MemoryUnavailable("保存先に接続できなかったぜ。管理者に設定を確認してもらってくれ。") from None

    def ping(self):
        with self.connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1
