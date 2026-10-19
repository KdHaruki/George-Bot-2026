import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import main
from fun_features import FORTUNES
from registered_memory import MemoryUnavailable


class FortuneFavoriteTests(unittest.IsolatedAsyncioTestCase):
    async def run_fortune(self, favorite, failure=False, reward=None, db_failure=False):
        generate = AsyncMock(return_value='いい一日にしようね！')
        if failure:
            generate.side_effect = ValueError('invalid response')
        claim = Mock(return_value=reward or {'granted': False, 'item': 'food', 'fortune': '吉'})
        if db_failure:
            claim.side_effect = MemoryUnavailable('offline')
        bot = SimpleNamespace(present_store=SimpleNamespace(claim=claim), george_chat=SimpleNamespace(fortune_details=generate))
        interaction = SimpleNamespace(id=100, user=SimpleNamespace(id=42),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(main, 'client', bot), patch.object(main, 'conversation_favorite',
                AsyncMock(return_value=favorite)) as lookup:
            await main.omikuji.callback(interaction)
        lookup.assert_not_awaited()
        self.assertEqual(claim.call_args.args[:2], (42, 100))
        self.assertEqual(generate.await_count, 1)
        return generate, interaction.followup.send.call_args.kwargs['embed']

    async def test_default_speaker_is_george(self):
        generate, embed = await self.run_fortune(None)
        self.assertEqual(embed.fields[0].name, '【ジョージの一言】')
        self.assertEqual(generate.call_args.kwargs, {})

    async def test_generation_failure_uses_george_fallback(self):
        generate, embed = await self.run_fortune({'character': 'ロザリー'}, failure=True)
        fortune = generate.call_args.args[0]
        self.assertEqual(embed.fields[0].name, '【ジョージの一言】')
        self.assertIn(dict(FORTUNES)[fortune], embed.fields[0].value)

    async def test_saved_reward_survives_ai_failure(self):
        generate, embed = await self.run_fortune(None, failure=True,
            reward={'granted': True, 'item': 'rare', 'fortune': '大吉'})
        self.assertEqual(generate.call_args.args[0], '大吉')
        self.assertIn('虹色の花束', embed.fields[2].value)
        self.assertIn('大吉', embed.description)

    async def test_database_failure_still_returns_fortune_with_clear_notice(self):
        _, embed = await self.run_fortune(None, db_failure=True)
        self.assertIn('受け取りを確認できなかった', embed.fields[2].value)

    async def test_support_bonus_uses_saved_lucky_progress_in_display(self):
        _, embed = await self.run_fortune(None, reward={'granted': True, 'item': 'rare', 'fortune': '大吉',
            'lucky_progress': '日向美海', 'bonus_item': 'food'})
        self.assertEqual(embed.fields[1].value.removesuffix('\n\u200b'), '日向美海')
        self.assertIn('応援ボーナス', embed.fields[2].value)
        self.assertIn('お弁当', embed.fields[2].value)
