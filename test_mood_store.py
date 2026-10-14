import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from mood_store import MoodStore, database_error_reason


class MoodStoreTests(unittest.TestCase):
    def test_pooler_connection_and_transaction_timeout(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchall.return_value = [(1, 65, 0)]
        connect = MagicMock(return_value=connection)
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}):
            self.assertEqual(MoodStore("postgresql://test-only").load(), [(1, 65, 0)])
        connect.assert_called_once_with("postgresql://test-only", connect_timeout=10)
        self.assertEqual(connection.execute.call_args_list[0].args, ("SET LOCAL statement_timeout = '10s'",))
        self.assertIn("CREATE TABLE IF NOT EXISTS", connection.execute.call_args_list[1].args[0])

    def test_credentials_are_never_returned_in_diagnostics(self):
        for message, expected in [
            ("unsupported startup parameter in options: statement_timeout secret", "unsupported_startup_parameter"),
            ("password authentication failed secret", "invalid_database_password"),
            ("connection timeout expired secret", "database_timeout"),
            ("other secret", "database_connection_or_query_error")]:
            self.assertEqual(database_error_reason(RuntimeError(message)), expected)


if __name__ == "__main__":
    unittest.main()
