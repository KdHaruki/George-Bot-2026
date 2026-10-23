import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord


class ReactionAchievementTests(unittest.IsolatedAsyncioTestCase):

    async def test_ambient_success_sets_hour_wait_and_skip_only_short_retry(self):
        import main
        from ambient_chat import AmbientChat, COOLDOWN, RETRY_DELAY
        for answer in (None, '楽しそうだな！'):
            ambient = AmbientChat()
            ambient.observe(1, 42, '散歩したよ', now=98)
            ambient.observe(1, 43, 'いいね', now=99)
            bot = SimpleNamespace(user=SimpleNamespace(id=99), ambient=ambient,
                george_chat=SimpleNamespace(client=object(), ambient_reply=AsyncMock(return_value=answer)))
            message = SimpleNamespace(id=123, author=SimpleNamespace(id=42, bot=False), content='公園に行ったよ',
                mentions=[], reference=None, role_mentions=[], mention_everyone=False, guild=object(),
                channel=SimpleNamespace(id=1, send=AsyncMock()), attachments=[], add_reaction=AsyncMock())
            with patch.object(main, 'client', bot), patch('main.random.random', return_value=0), patch('ambient_chat.time.monotonic', return_value=100), patch('main.load_ambient_history', AsyncMock(return_value=['context'])):
                await main.on_message(message)
            self.assertEqual(ambient.states[1].next_attempt, 100 + (COOLDOWN if answer else RETRY_DELAY))
            self.assertFalse(ambient.states[1].busy)
            self.assertEqual(message.channel.send.await_count, int(bool(answer)))

    async def test_only_successful_reaction_triggers_without_second_lottery(self):
        import main
        from ambient_chat import AmbientChat
        for reaction, fails in [(False, False), (True, True), (True, False)]:
            ambient = AmbientChat()
            bot = SimpleNamespace(user=SimpleNamespace(id=99), ambient=ambient,
                george_chat=SimpleNamespace(client=object(), ambient_reply=AsyncMock(return_value='いいね！')))
            error = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'denied') if fails else None
            message = SimpleNamespace(id=123, author=SimpleNamespace(id=42, bot=False), content='公園の花がきれい',
                mentions=[], reference=None, role_mentions=[], mention_everyone=False, guild=object(),
                channel=SimpleNamespace(id=1, send=AsyncMock()), attachments=[], add_reaction=AsyncMock(side_effect=error))
            history = AsyncMock(return_value=['context'])
            with patch.object(main, 'client', bot), patch('main.random.random', return_value=0 if reaction else 1) as lottery, patch('main.load_ambient_history', history):
                await main.on_message(message)
            self.assertEqual(history.await_count, int(reaction and not fails))
            self.assertEqual(message.channel.send.await_count, int(reaction and not fails))
            self.assertEqual(lottery.call_count, 1)

    async def test_new_normal_message_does_not_cancel_but_direct_reply_does(self):
        import main
        from ambient_chat import AmbientChat
        for directed in (False, True):
            ambient = AmbientChat()
            async def generate(context):
                if directed:
                    ambient.note_reply(1)
                else:
                    ambient.observe(1, 43, '次は別の公園も行こう')
                return '花を見ながら散歩、いいね！'
            bot = SimpleNamespace(user=SimpleNamespace(id=99), ambient=ambient,
                george_chat=SimpleNamespace(client=object(), ambient_reply=generate))
            message = SimpleNamespace(id=123, author=SimpleNamespace(id=42, bot=False), content='公園の花がきれい',
                mentions=[], reference=None, role_mentions=[], mention_everyone=False, guild=object(),
                channel=SimpleNamespace(id=1, send=AsyncMock()), attachments=[], add_reaction=AsyncMock())
            with patch.object(main, 'client', bot), patch('main.random.random', return_value=0), patch('main.load_ambient_history', AsyncMock(return_value=['context'])):
                await main.on_message(message)
            self.assertEqual(message.channel.send.await_count, int(not directed))
