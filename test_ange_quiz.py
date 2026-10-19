import random
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from registered_memory import MemoryUnavailable

from ange_quiz import QuizView, hints_for


class QuizTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertIn('お弁当', interaction.edit_original_response.call_args.kwargs['embed'].description)

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
