"""好感度上限100・1回だけのパーフェクトリンク・上限時の贈答確認を検証する。"""

from datetime import timedelta
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

import test_presents
from presents import affection_display, PresentStore, GiftConfirmationRequired
from present_view import PresentView, GiftConfirmationView
from database import MemoryUnavailable


class LinkLimitTests(unittest.TestCase):
    setUp = test_presents.StorageTests.setUp
    set_favorite = test_presents.StorageTests.set_favorite

    def prepare(self, points=100):
        self.store.snapshot(42)
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',?)", (points,))
        for item in ('magic', 'tools', 'rare'):
            self.db.execute('INSERT INTO george_present_items VALUES (42,?,5)', (item,))
        self.db.commit()

    def test_all_gifts_require_confirmation_at_cap_and_link_happens_once(self):
        self.prepare(99)
        self.assertEqual(self.store.give(42, 100, 'ロザリー', 'magic'), (1, 100, False))
        before = self.store.inventory(42)
        for operation, item in enumerate(('magic', 'tools', 'rare'), 101):
            with self.subTest(item=item), self.assertRaises(GiftConfirmationRequired):
                self.store.give(42, operation, 'ロザリー', item)
            self.assertEqual(self.store.inventory(42), before)
        self.assertIsNone(self.store.album(42, 'ロザリー')[3])
        self.assertEqual(self.store.give(42, 104, 'ロザリー', 'tools', confirmed=True), (0, 100, False))
        self.assertEqual(self.store.give(42, 105, 'ロザリー', 'rare', confirmed=True), (0, 100, False))
        self.assertEqual(self.store.give(42, 106, 'ロザリー', 'magic', confirmed=True), (0, 100, True))
        first = self.store.album(42, 'ロザリー')[3]
        for operation, item in enumerate(('magic', 'tools', 'rare'), 107):
            self.assertEqual(self.store.give(42, operation, 'ロザリー', item, confirmed=True), (0, 100, True))
        self.assertEqual(self.store.album(42, 'ロザリー')[3], first)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_perfect_links').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_perfect_link_levels').fetchone()[0], 0)
        self.assertIn('100/100', affection_display(100, True))
        self.assertNotIn('Ⅰ', affection_display(100, True))

    def test_old_points_and_multiple_stages_are_capped_without_deleting_records(self):
        self.prepare(310)
        self.db.execute("INSERT INTO george_perfect_links VALUES (42,'ロザリー','2026-10-01T00:00:00+00:00')")
        self.db.execute("INSERT INTO george_perfect_link_levels VALUES (42,'ロザリー',3,'2026-10-10T00:00:00+00:00')")
        self.db.commit()
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (100, 1))
        self.assertEqual(self.db.execute('SELECT points FROM george_affection').fetchone()[0], 310)
        self.assertEqual(self.db.execute('SELECT level FROM george_perfect_link_levels').fetchone()[0], 3)
        self.day += timedelta(days=150)
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (100, 1))
        with self.assertRaises(GiftConfirmationRequired):
            self.store.give(42, 100, 'ロザリー', 'magic')
        self.assertEqual(self.store.give(42, 101, 'ロザリー', 'magic', confirmed=True), (0, 100, True))
        self.assertEqual(self.store.album(42, 'ロザリー')[3].day, 1)
        self.assertEqual(PresentStore('unused').affection_status(42, 'ロザリー'), (100, 1))

    def test_confirmation_is_checked_after_daily_gain(self):
        self.prepare(99)
        self.day += timedelta(days=1)
        before = self.store.inventory(42)
        with self.assertRaises(GiftConfirmationRequired):
            self.store.give(42, 100, 'ロザリー', 'tools')
        self.assertEqual(self.store.inventory(42), before)
        self.assertEqual(self.store.give(42, 101, 'ロザリー', 'tools', confirmed=True), (0, 100, False))

    def test_link_failure_rolls_back_consumption_and_retry_does_not_spend_twice(self):
        self.prepare()
        self.fail_on = 'INSERT INTO george_perfect_links'
        with self.assertRaises(MemoryUnavailable):
            self.store.give(42, 100, 'ロザリー', 'magic', confirmed=True)
        self.fail_on = None
        self.assertEqual(self.store.inventory(42)['magic'], 5)
        self.assertIsNone(self.store.album(42, 'ロザリー')[3])
        self.assertEqual(self.store.give(42, 100, 'ロザリー', 'magic', confirmed=True), (0, 100, True))
        self.assertEqual(self.store.give(42, 100, 'ロザリー', 'magic'), (0, 100, True))
        self.assertEqual(self.store.inventory(42)['magic'], 4)


class GiftConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, number=1, user=42):
        return SimpleNamespace(id=number, user=SimpleNamespace(id=user),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))

    async def test_cap_prompts_and_confirm_consumes_only_once(self):
        store = SimpleNamespace(give=Mock(return_value=(0, 100, True)))
        parent = PresentView(42, store, 'ロザリー', {'magic': 2, 'tools': 1, 'rare': 1}, 100)
        self.assertTrue(all(not button.disabled for button in parent.children))
        interaction = self.interaction()
        await parent.give(interaction, 'magic')
        prompt = interaction.edit_original_response.call_args.kwargs['view']
        self.assertIsInstance(prompt, GiftConfirmationView)
        self.assertIn('これ以上は好感度が上がらないが、本当にあげるのか？', prompt.embed().description)
        store.give.assert_not_called()
        await prompt.confirm.callback(self.interaction(2))
        await prompt.confirm.callback(self.interaction(3))
        store.give.assert_called_once_with(42, 2, 'ロザリー', 'magic', confirmed=True)
        self.assertEqual(parent.items['magic'], 1)
        self.assertIn('100/100', parent.embed().description)
        parent.stop()

    async def test_cancel_timeout_and_wrong_owner_never_consume(self):
        store = SimpleNamespace(give=Mock())
        parent = PresentView(42, store, 'ロザリー', {'rare': 1}, 100, True)
        await parent.give(self.interaction(), 'rare')
        prompt = parent.confirmation
        self.assertFalse(await prompt.interaction_check(self.interaction(user=43)))
        await prompt.cancel.callback(self.interaction(2))
        await prompt.confirm.callback(self.interaction(3))
        store.give.assert_not_called()
        self.assertEqual(parent.items['rare'], 1)
        await parent.give(self.interaction(4), 'rare')
        prompt = parent.confirmation
        prompt.message = SimpleNamespace(edit=AsyncMock())
        await prompt.on_timeout()
        await prompt.confirm.callback(self.interaction(5))
        store.give.assert_not_called()
        self.assertTrue(parent.expired)
        prompt.stop()
        parent.stop()

    async def test_stale_screen_rechecks_at_storage_and_old_prompt_cannot_consume(self):
        store = SimpleNamespace(give=Mock(side_effect=[GiftConfirmationRequired(False), (0, 100, True)]))
        parent = PresentView(42, store, 'ロザリー', {'magic': 2}, 99)
        await parent.give(self.interaction(), 'magic')
        self.assertEqual(parent.items['magic'], 2)
        old = parent.confirmation
        await parent.give(self.interaction(2), 'magic')
        await old.confirm.callback(self.interaction(3))
        self.assertEqual(store.give.call_count, 1)
        await parent.confirmation.confirm.callback(self.interaction(4))
        self.assertEqual(store.give.call_count, 2)
        parent.stop()

    async def test_favorite_change_or_missing_item_during_confirmation_does_not_change_screen_inventory(self):
        for reason in ('お気に入りが変わった', 'そのプレゼントはもう持っていない'):
            store = SimpleNamespace(give=Mock(side_effect=ValueError(reason)))
            parent = PresentView(42, store, 'ロザリー', {'tools': 1}, 100)
            await parent.give(self.interaction(), 'tools')
            interaction = self.interaction(2)
            await parent.confirmation.confirm.callback(interaction)
            self.assertEqual(parent.items['tools'], 1)
            self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
            parent.confirmation.stop()
            parent.stop()

    async def test_confirmation_does_not_extend_original_deadline(self):
        store = SimpleNamespace(give=Mock())
        parent = PresentView(42, store, 'ロザリー', {'magic': 1}, 100)
        await parent.give(self.interaction(), 'magic')
        prompt = parent.confirmation
        parent.deadline = 0
        interaction = self.interaction(2)
        self.assertFalse(await prompt.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        await prompt.confirm.callback(self.interaction(3))
        store.give.assert_not_called()
        self.assertEqual(parent.items['magic'], 1)
        prompt.stop()
        parent.stop()
