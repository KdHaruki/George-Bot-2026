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
                channel=SimpleNamespace(id=1, send=AsyncMock()), attachments=[])
            with patch.object(main, 'client', bot), patch('main.random.random', side_effect=[1, 0]), patch('ambient_chat.time.monotonic', return_value=100), patch('main.load_ambient_history', AsyncMock(return_value=['context'])):
                await main.on_message(message)
            self.assertEqual(ambient.states[1].next_attempt, 100 + (COOLDOWN if answer else RETRY_DELAY))
            self.assertFalse(ambient.states[1].busy)
            self.assertEqual(message.channel.send.await_count, int(bool(answer)))
