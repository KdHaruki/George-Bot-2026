import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import main
from fun_features import FORTUNES
from database import MemoryUnavailable


class FortuneFavoriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_support_gift_is_shown_with_current_lucky_progress(self):
        _, embed = await self.run_fortune(None, reward={'granted': False, 'item': 'food', 'fortune': '吉',
            'lucky_progress': 'ロザリー', 'bonus_item': 'book', 'support_matched': True})
        self.assertEqual(embed.fields[2].name, '【今日の贈り物】')
        self.assertIn('応援ボーナス', embed.fields[2].value)
        self.assertIn('本', embed.fields[2].value)
        self.assertIn('ロザリー', embed.fields[1].value)

    async def test_public_fortune_result_has_separate_private_unlock_notification(self):
        store = SimpleNamespace(claim=Mock(return_value={'granted': True, 'item': 'food', 'fortune': '吉'}),
            claim_title_notifications=Mock(side_effect=[[('fortune10', '神頼み')], []]),
            finish_title_notifications=Mock())
        bot = SimpleNamespace(present_store=store, george_chat=SimpleNamespace(fortune_details=AsyncMock(return_value='いい日だぜ！')))
        interaction = SimpleNamespace(id=100, user=SimpleNamespace(id=42),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(main, 'client', bot):
            await main.omikuji.callback(interaction)
        public, private = interaction.followup.send.call_args_list
        self.assertIn('embed', public.kwargs)
        self.assertFalse(public.kwargs.get('ephemeral', False))
        self.assertNotIn('神頼み', str(public.kwargs['embed'].to_dict()))
        self.assertTrue(private.kwargs['ephemeral'])
        self.assertIn('神頼み', private.args[0])

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
        self.assertEqual(embed.fields[2].name, '【贈り物は受け取り済み】')
        self.assertIn('明日の0時（日本時間）', embed.fields[2].value)

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
        self.assertEqual(embed.fields[2].name, '【今日の贈り物】')
        self.assertIn('を受け取ったぜ！', embed.fields[2].value)
        self.assertIn('大吉', embed.description)

    async def test_database_failure_still_returns_fortune_with_clear_notice(self):
        _, embed = await self.run_fortune(None, db_failure=True)
        self.assertIn('受け取りを確認できなかった', embed.fields[2].value)
        self.assertEqual(embed.fields[2].name, '【贈り物の受け取り確認】')

    async def test_support_bonus_uses_saved_lucky_progress_in_display(self):
        _, embed = await self.run_fortune(None, reward={'granted': True, 'item': 'rare', 'fortune': '大吉',
            'lucky_progress': '日向美海', 'bonus_item': 'food'})
        self.assertEqual(embed.fields[1].value.removesuffix('\n\u200b'), '日向美海')
        self.assertIn('応援ボーナス', embed.fields[2].value)
        self.assertIn('紅茶', embed.fields[2].value)
