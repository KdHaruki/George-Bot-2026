import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock, patch

import discord
import main


class ConversationLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setup_message(self, kind='メンション', text='秘密の会話本文'):
        user = SimpleNamespace(id=99)
        bot = SimpleNamespace(user=user, message_history=Mock(),
                              ambient=SimpleNamespace(note_reply=Mock()),
                              george_chat=SimpleNamespace(reply=AsyncMock(return_value='秘密の返答')))
        channel = SimpleNamespace(id=1, send=AsyncMock(), typing=MagicMock())
        if kind == 'DM':
            channel = MagicMock(spec=discord.DMChannel)
            channel.id = 1
            channel.send = AsyncMock()
        message = SimpleNamespace(id=123, author=SimpleNamespace(id=5, bot=False),
                                  guild=None if kind == 'DM' else SimpleNamespace(id=8),
                                  channel=channel, content=text, mentions=[user])
        target = SimpleNamespace(content='秘密の引用') if kind == 'ジョージへの返信' else None
        return bot, message, target

    async def run_message(self, bot, message, target):
        with patch.object(main, 'client', bot), patch('main.random.random', return_value=1), \
                patch('main.george_reply_target', AsyncMock(return_value=target)), \
                self.assertLogs('george.operations') as logs:
            await main.on_message(message)
        output = '\n'.join(logs.output)
        self.assertNotIn('秘密', output)
        return output

    async def test_all_three_routes_log_receipt_and_success_with_duration(self):
        for kind in ('DM', 'メンション', 'ジョージへの返信'):
            bot, message, target = self.setup_message(kind)
            output = await self.run_message(bot, message, target)
            self.assertIn(f'【会話・{kind}】受付', output)
            self.assertIn(f'【会話・{kind}】返信完了', output)
            self.assertIn('秒：', output)
            self.assertIn('メッセージID：123', output)
            bot.message_history.observe.assert_called_once()
            message.channel.send.assert_awaited_once()

    async def test_help_and_management_are_distinguished(self):
        for text, result in [('ヘルプ', 'ヘルプ表示完了'),
                             ('この会話は記録されてる？', '管理情報への回答を見送り・案内返信完了')]:
            bot, message, target = self.setup_message(text=text)
            with patch('main.help_embed', AsyncMock(return_value=object())):
                output = await self.run_message(bot, message, target)
            self.assertIn(result, output)
            bot.george_chat.reply.assert_not_awaited()

    async def test_generation_failure_and_error_reply_are_distinguished(self):
        bot, message, target = self.setup_message()
        bot.george_chat.reply.side_effect = TimeoutError('秘密のAPIキー')
        output = await self.run_message(bot, message, target)
        self.assertIn('返答生成に失敗', output)
        self.assertIn('待ち時間の上限に到達', output)
        self.assertIn('エラー案内の返信完了', output)

    async def test_busy_is_not_reported_as_normal_reply(self):
        bot, message, target = self.setup_message()
        bot.george_chat.reply.side_effect = main.ChatBusy()
        output = await self.run_message(bot, message, target)
        self.assertIn('通常の返答を見送り', output)
        self.assertIn('案内返信完了', output)

    async def test_send_failure_never_logs_success(self):
        bot, message, target = self.setup_message()
        message.channel.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='test'), '秘密の本文')
        output = await self.run_message(bot, message, target)
        self.assertIn('処理失敗・返信未完了', output)
        self.assertIn('Discordの権限不足', output)
        self.assertNotIn('】返信完了', output)
