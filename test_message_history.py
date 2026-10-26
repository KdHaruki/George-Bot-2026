import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from contextlib import contextmanager
from message_history import MessageHistory, MessageHistoryStore


class MessageHistoryTests(unittest.IsolatedAsyncioTestCase):
    def message(self):
        return SimpleNamespace(id=123, created_at=datetime.now(timezone.utc),
            author=SimpleNamespace(id=7, bot=False), guild=SimpleNamespace(id=8),
            channel=SimpleNamespace(id=9), content="hello'); DROP TABLE x; --",
            reference=SimpleNamespace(message_id=100))

    async def test_fields_dm_and_bot_filter(self):
        store = SimpleNamespace(url='test', save=Mock())
        history = MessageHistory(store)
        message = self.message()
        history.observe(message, 'reply')
        await history.close()
        record = store.save.call_args.args[0]
        self.assertEqual(record[0], 123)
        self.assertEqual(record[4:9], (8, 9, 'reply', message.content, 100))
        message.guild = None
        history.observe(message, 'dm')
        await history.close()
        self.assertIsNone(store.save.call_args.args[0][4])
        message.author.bot = True
        history.observe(message, 'dm')
        self.assertFalse(history.tasks)

    async def test_parameterized_save_retention_and_duplicate_protection(self):
        connection = MagicMock()
        store = MessageHistoryStore('test')
        @contextmanager
        def connect():
            yield connection
        store.connect = connect
        record = (1, datetime.now(timezone.utc), 2, 'user', None, 3, 'dm', "'); DROP TABLE x; --", None)
        store.save(record)
        sql, params = connection.execute.call_args_list[0].args
        self.assertEqual(params, record)
        self.assertNotIn(record[7], sql)
        self.assertIn('ON CONFLICT(message_id) DO NOTHING', sql)
        self.assertIn("interval '30 days'", connection.execute.call_args_list[1].args[0])

    async def test_failure_is_background_and_does_not_log_content(self):
        store = SimpleNamespace(url='test', save=Mock(side_effect=RuntimeError('secret message body')))
        history = MessageHistory(store)
        with self.assertLogs('george.operations', level='WARNING') as logs:
            history.observe(self.message(), 'mention')
            await history.close()
        self.assertIn('【受信メッセージDB】保存失敗', str(logs.output))
        self.assertNotIn('secret message body', str(logs.output))

    async def test_help_mention_is_recorded_before_reply(self):
        import main
        bot = SimpleNamespace(user=SimpleNamespace(id=99), message_history=Mock(),
                              ambient=SimpleNamespace(note_reply=Mock()))
        message = self.message()
        message.content = '<@99> ヘルプ'
        message.mentions = [bot.user]
        message.channel.send = AsyncMock()
        with patch.object(main, 'client', bot), patch('main.random.random', return_value=1), patch('main.george_reply_target', AsyncMock(return_value=None)), patch('main.help_embed', AsyncMock(return_value=object())):
            await main.on_message(message)
        bot.message_history.observe.assert_called_once_with(message, 'mention')
        message.channel.send.assert_awaited_once()
