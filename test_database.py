import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from database import DatabaseStore, MemoryUnavailable


class DatabaseConnectionTests(unittest.TestCase):
    def test_missing_configuration_does_not_attempt_connection(self):
        with self.assertRaises(MemoryUnavailable):
            DatabaseStore('').ping()

    def test_transaction_timeout_and_ping_without_retired_table_creation(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = (1,)
        connect = MagicMock(return_value=connection)
        with patch.dict(sys.modules, {'psycopg': SimpleNamespace(connect=connect)}):
            self.assertTrue(DatabaseStore('postgresql://test-only').ping())
        connect.assert_called_once_with('postgresql://test-only', connect_timeout=10)
        queries = [call.args[0] for call in connection.execute.call_args_list]
        self.assertIn("SET LOCAL statement_timeout = '10s'", queries)
        self.assertFalse(any('george_memories' in query for query in queries))

    def test_connection_errors_do_not_expose_secret(self):
        connect = MagicMock(side_effect=RuntimeError('secret-password'))
        with patch.dict(sys.modules, {'psycopg': SimpleNamespace(connect=connect)}):
            with self.assertRaises(MemoryUnavailable) as result:
                DatabaseStore('postgresql://secret-password').ping()
            self.assertNotIn('secret-password', str(result.exception))
