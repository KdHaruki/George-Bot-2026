import random
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from database import MemoryUnavailable

from ange_quiz import QuizView, hints_for


class QuizTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_attempt_and_timeout_are_persisted_once(self):
        store = SimpleNamespace(resolve_quiz_round=Mock(), claim_quiz=Mock(return_value={'granted': False, 'item': 'food'}))
        view = QuizView(42, reward_store=store, reward_id=100)
        wrong = next(button for button in view.children if button.label != view.answer['progressName'])
        correct = next(button for button in view.children if button.label == view.answer['progressName'])
        await wrong.callback(self.interaction())
        await correct.callback(self.interaction())
        store.resolve_quiz_round.assert_called_once_with(42, 100, False)
        timeout = QuizView(42, reward_store=store, reward_id=101)
        await timeout.on_timeout()
        self.assertEqual(store.resolve_quiz_round.call_args.args, (42, 101, False))
        timeout.stop()

    async def test_hint_order_varies_between_questions_but_is_fixed_during_question(self):
        records = [dict(progressName=f'人物{i}', progressWorld='青', progressLike='お菓子',
                        progressDisLike='雨', progressInscription='元気', progressDetail1='紹介') for i in range(4)]
        first_hints = set()
        for seed in range(20):
            view = QuizView(42, records=records, rng=random.Random(seed))
            expected = hints_for(view.answer)
            self.assertCountEqual(view.hints, expected)
            self.assertEqual(view.hints[-1][0], '出身世界')
            first_hints.add(view.hints[0][0])
            original = list(view.hints)
            wrong = next(button for button in view.children if button.label != view.answer['progressName'])
            await wrong.callback(self.interaction())
            self.assertEqual(view.hints, original)
            self.assertEqual([field.name for field in view.embed().fields],
                             [f'【{label}】' for label, _ in original[:2]])
            view.stop()
        self.assertEqual(first_hints, {'好きなもの', '苦手なもの', '座右の銘', 'プロフィール'})

    def interaction(self, user=42):
        return SimpleNamespace(user=SimpleNamespace(id=user), edit_original_response=AsyncMock(), response=SimpleNamespace(
            edit_message=AsyncMock(), send_message=AsyncMock(), defer=AsyncMock()))

    async def test_four_unique_choices_and_incremental_hints(self):
        view = QuizView(42, rng=random.Random(1))
        self.assertEqual(len({b.label for b in view.children}), 4)
        self.assertEqual(len(view.embed().fields), 1)
        wrong = next(b for b in view.children if b.label != view.answer['progressName'])
        await wrong.callback(self.interaction())
        self.assertTrue(wrong.disabled)
        self.assertEqual(len(view.embed().fields), 2)
        await wrong.callback(self.interaction())
        self.assertEqual(view.revealed, 2)
        correct = next(b for b in view.children if b.label == view.answer['progressName'])
        await correct.callback(self.interaction())
        self.assertTrue(view.finished)
        self.assertTrue(all(b.disabled for b in view.children))
        self.assertEqual(view.revealed, len(view.hints))
        fields = [field.name for field in view.embed().fields]
        self.assertEqual(fields[:2], ['【出身世界】', '【好きなもの】'])
        self.assertTrue(view.embed().description.endswith('\n\u200b'))

    async def test_owner_only_and_timeout(self):
        view = QuizView(42)
        interaction = self.interaction(43)
        self.assertFalse(await view.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        self.assertTrue(all(b.disabled for b in view.children))
        view.message.edit.assert_awaited_once()
        view.stop()

    async def test_hint_redacts_name_and_alias(self):
        hints = hints_for({'progressName': 'ロザリー', 'progressNickname1': 'ロザ',
                           'progressDetail1': 'ロザリー、愛称ロザ'})
        self.assertNotIn('ロザ', hints[0][1])

    async def test_reward_only_on_correct_and_once_per_view(self):
        store = SimpleNamespace(claim_quiz=Mock(return_value={'granted': True, 'item': 'food'}))
        view = QuizView(42, reward_store=store, reward_id=100)
        wrong = next(b for b in view.children if b.label != view.answer['progressName'])
        await wrong.callback(self.interaction())
        store.claim_quiz.assert_not_called()
        correct = next(b for b in view.children if b.label == view.answer['progressName'])
        interaction = self.interaction()
        await correct.callback(interaction)
        await correct.callback(self.interaction())
        store.claim_quiz.assert_called_once_with(42, 100, 2)
        self.assertIn('紅茶', interaction.edit_original_response.call_args.kwargs['embed'].description)

    async def test_daily_limit_and_database_failure_keep_correct_result(self):
        for result in ({'granted': False, 'item': 'food'}, MemoryUnavailable('offline')):
            claim = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
            view = QuizView(42, reward_store=SimpleNamespace(claim_quiz=claim), reward_id=100)
            correct = next(b for b in view.children if b.label == view.answer['progressName'])
            interaction = self.interaction()
            await correct.callback(interaction)
            text = interaction.edit_original_response.call_args.kwargs['embed'].description
            self.assertIn('正解！', text)
            self.assertIn('受け取り済み' if isinstance(result, dict) else '受け取りを確認できなかった', text)
            self.assertTrue(all(b.disabled for b in view.children))
