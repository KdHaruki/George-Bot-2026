import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from operation_logging import event, command_finished


class OperationLoggingTests(unittest.TestCase):
    def test_logs_ids_but_not_exception_text_or_unexpected_values(self):
        with self.assertLogs('george.operations') as captured:
            event('AI', '定型文に切り替え', error=TimeoutError('secret token'),
                  操作ID=123, 本文='private message', 接続情報='postgres://secret')
        output = '\n'.join(captured.output)
        self.assertIn('待ち時間の上限に到達', output)
        self.assertIn('操作ID：123', output)
        for secret in ('secret', 'private', 'postgres'):
            self.assertNotIn(secret, output)

    def test_command_completion_omits_user_options(self):
        interaction = SimpleNamespace(id=123, created_at=datetime.now(timezone.utc),
                                      data={'options': 'private input'})
        with self.assertLogs('george.operations') as captured:
            command_finished(interaction, SimpleNamespace(qualified_name='お気に入り プレゼント'))
        output = '\n'.join(captured.output)
        self.assertIn('/お気に入り プレゼント', output)
        self.assertIn('処理終了', output)
        self.assertIn('秒：', output)
        self.assertNotIn('private', output)

    def test_api_limit_and_unknown_code_are_safe(self):
        ClientError = type('ClientError', (Exception,), {})
        for code in (429, 402):
            error = ClientError('secret provider text')
            error.code = code
            with self.assertLogs('george.operations') as captured:
                event('AI', '失敗', error=error)
            output = '\n'.join(captured.output)
            self.assertNotIn('secret', output)
            if code == 429:
                self.assertIn('利用上限', output)

    def test_db_pruning_count_is_returned(self):
        from contextlib import contextmanager
        from unittest.mock import MagicMock
        from command_history import CommandHistoryStore
        from message_history import MessageHistoryStore
        for store in (CommandHistoryStore('test'), MessageHistoryStore('test')):
            connection = MagicMock()
            connection.execute.return_value.rowcount = 3
            @contextmanager
            def connect():
                yield connection
            store.connect = connect
            self.assertEqual(store.save(tuple()), 3)


class CommandLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_and_handled_error_are_logged(self):
        import main
        from unittest.mock import AsyncMock, Mock
        command = SimpleNamespace(qualified_name='おみくじ')
        interaction = SimpleNamespace(id=123, created_at=datetime.now(timezone.utc), command=command,
                                      response=SimpleNamespace(is_done=Mock(return_value=True)),
                                      followup=SimpleNamespace(send=AsyncMock()))
        with self.assertLogs('george.operations') as captured:
            await main.on_app_command_completion(interaction, command)
            await main.on_command_error(interaction, RuntimeError('secret'))
        output = '\n'.join(captured.output)
        self.assertIn('処理終了', output)
        self.assertIn('失敗', output)
        self.assertNotIn('secret', output)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])

    async def test_full_queue_does_not_log_record_body(self):
        from command_history import CommandHistory
        history = CommandHistory(SimpleNamespace(url='test'))
        history.tasks = set(range(32))
        with self.assertLogs('george.operations') as captured:
            history.schedule((123, 'secret body'))
        output = '\n'.join(captured.output)
        self.assertIn('上限32件', output)
        self.assertNotIn('secret', output)
