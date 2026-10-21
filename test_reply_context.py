import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from reply_context import george_reply_target
import main


class ReplyTests(unittest.IsolatedAsyncioTestCase):
    def message(self):
        target = SimpleNamespace(author=SimpleNamespace(id=99), content="今日は楽しかったぜ！")
        channel = SimpleNamespace(id=1, fetch_message=AsyncMock(return_value=target), send=AsyncMock(), typing=MagicMock())
        return SimpleNamespace(reference=SimpleNamespace(channel_id=1, message_id=10, resolved=target),
                               channel=channel, author=SimpleNamespace(id=5, bot=False), mentions=[],
                               guild=SimpleNamespace(id=123), content="何が楽しかったの？")

    async def test_cached_and_uncached_bot_reply(self):
        message = self.message()
        self.assertIs(await george_reply_target(message, 99), message.reference.resolved)
        message.reference.resolved = None
        self.assertIsNotNone(await george_reply_target(message, 99))
        message.channel.fetch_message.assert_awaited_once_with(10)

    async def test_other_user_and_other_channel_are_ignored(self):
        message = self.message()
        self.assertIsNone(await george_reply_target(message, 88))
        message.reference.channel_id = 2
        self.assertIsNone(await george_reply_target(message, 99))

    async def test_reply_without_mention_reaches_chat_with_quote(self):
        message = self.message()
        fake = SimpleNamespace(user=SimpleNamespace(id=99), memories=SimpleNamespace(url=""),
                               george_chat=SimpleNamespace(reply=AsyncMock(return_value="散歩してきたぜ！")),
                               ambient=SimpleNamespace(note_reply=Mock()))
        with patch.object(main, "client", fake), patch("main.random.random", return_value=1):
            await main.on_message(message)
        fake.george_chat.reply.assert_awaited_once_with((1, 5), message.content, reply_to="今日は楽しかったぜ！")
        message.channel.send.assert_awaited_once()

    async def test_image_only_reply_is_not_read_or_forwarded(self):
        message = self.message()
        message.content = ""
        item = SimpleNamespace(read=AsyncMock())
        message.attachments = [item]
        fake = SimpleNamespace(user=SimpleNamespace(id=99), memories=SimpleNamespace(url=""),
                               george_chat=SimpleNamespace(reply=AsyncMock(return_value="いい写真だぜ！")),
                               ambient=SimpleNamespace(note_reply=Mock()))
        with patch.object(main, "client", fake), patch("main.random.random", return_value=1):
            await main.on_message(message)
        item.read.assert_not_awaited()
        fake.george_chat.reply.assert_not_awaited()
        message.channel.send.assert_awaited_once()

    async def test_recording_questions_return_fixed_admin_guidance_without_ai(self):
        import discord
        from george_chat import MANAGEMENT_REPLY
        for dm in (False, True):
            message = self.message()
            if dm:
                message.channel = Mock(spec=discord.DMChannel)
                message.channel.id = 1
                message.channel.send = AsyncMock()
                message.guild = None
                message.reference = None
            message.content = 'この会話やDMは記録・管理されてるの？'
            fake = SimpleNamespace(user=SimpleNamespace(id=99), george_chat=SimpleNamespace(reply=AsyncMock()),
                                   ambient=SimpleNamespace(note_reply=Mock()))
            if not dm:
                message.mentions = [fake.user]
            with patch.object(main, 'client', fake), patch('main.random.random', return_value=1):
                await main.on_message(message)
            fake.george_chat.reply.assert_not_awaited()
            self.assertEqual(message.channel.send.call_args.args[0], MANAGEMENT_REPLY)
