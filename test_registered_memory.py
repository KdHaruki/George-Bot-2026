import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from registered_memory import MemoryStore, MemoryUnavailable


class MemoryStoreTests(unittest.TestCase):
    def test_no_database_and_validation(self):
        with self.assertRaises(MemoryUnavailable):
            MemoryStore("").list(1, 2)
        with self.assertRaises(ValueError):
            MemoryStore("").save(1, 2, "", "内容")

    def connection(self, rows):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchall.return_value = rows
        connection.execute.return_value.rowcount = 1
        return connection

    def test_owner_scope_filters_and_parameterized_content(self):
        connection = self.connection([])
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=MagicMock(return_value=connection))}):
            store = MemoryStore("postgresql://test-only")
            store.save(1, 2, "趣味", "ゲーム'); DROP TABLE george_memories; --")
            self.assertEqual(connection.execute.call_args.args[1], (1, 2, "趣味", "ゲーム'); DROP TABLE george_memories; --"))
            store.list(1, 2)
            self.assertEqual(connection.execute.call_args.args[1], (1, 2))
            store.delete(1, 2, "趣味")
            self.assertEqual(connection.execute.call_args.args[1], (1, 2, "趣味"))

    def test_limit_allows_replacing_existing_title(self):
        connection = self.connection([(str(i),) for i in range(20)])
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=MagicMock(return_value=connection))}):
            store = MemoryStore("postgresql://test-only")
            with self.assertRaises(ValueError):
                store.save(1, 2, "新規", "内容")
            store.save(1, 2, "0", "更新")

    def test_connection_errors_do_not_expose_secret(self):
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=MagicMock(side_effect=RuntimeError("secret-password")))}):
            with self.assertRaises(MemoryUnavailable) as result:
                MemoryStore("postgresql://secret-password").list(1, 2)
            self.assertNotIn("secret-password", str(result.exception))


if __name__ == "__main__":
    unittest.main()
