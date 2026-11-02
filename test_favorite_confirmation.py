"""お気に入り解除の確認・取消・期限切れと、変更済みの登録を守る処理を検証する。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from favorite_confirmation import FavoriteRemovalView
import test_presents
from present_view import PresentView
from ange_quiz import QuizView
from title_commands import TitleView


class RemovalStorageTests(unittest.TestCase):
    setUp = test_presents.StorageTests.setUp
    set_favorite = test_presents.StorageTests.set_favorite

    def test_remove_keeps_cards_affection_and_album(self):
        self.store.snapshot(42)
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',50)")
        self.db.execute("INSERT INTO george_favorite_album(user_id,character,first_registered_at) VALUES (42,'ロザリー','2026-10-01')")
        self.db.commit()
        self.store.remove_favorite(42, 'ロザリー')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_gacha_favorites').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_gacha_cards').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT points FROM george_affection').fetchone()[0], 50)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_favorite_album').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_daily_affection').fetchone()[0], 0)

    def test_changed_or_already_removed_favorite_is_not_deleted(self):
        self.store.snapshot(42)
        self.set_favorite('美海')
        with self.assertRaisesRegex(ValueError, 'お気に入りが変わって'):
            self.store.remove_favorite(42, 'ロザリー')
        self.assertEqual(self.store.snapshot(42)[0], '日向美海')
        self.set_favorite(None)
        with self.assertRaises(ValueError):
            self.store.remove_favorite(42, 'ロザリー')


class ConfirmationViewTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, user=42):
        return SimpleNamespace(user=SimpleNamespace(id=user),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def test_confirm_removes_once_and_cancel_never_writes(self):
        for remove in (True, False):
            store = SimpleNamespace(remove_favorite=Mock())
            view = FavoriteRemovalView(42, store, 'ロザリー')
            interaction = self.interaction()
            self.assertTrue(await view.interaction_check(interaction))
            await view.finish(interaction, remove=remove)
            await view.finish(interaction, remove=remove)
            self.assertEqual(store.remove_favorite.call_count, int(remove))
            self.assertTrue(all(button.disabled for button in view.children))
            interaction.edit_original_response.assert_awaited_once()

    async def test_other_user_timeout_and_storage_error_do_not_remove(self):
        store = SimpleNamespace(remove_favorite=Mock())
        view = FavoriteRemovalView(42, store, 'ロザリー')
        outsider = self.interaction(43)
        self.assertFalse(await view.interaction_check(outsider))
        self.assertTrue(outsider.response.send_message.call_args.kwargs['ephemeral'])
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        await view.finish(self.interaction(), remove=True)
        store.remove_favorite.assert_not_called()
        view.stop()

        view = FavoriteRemovalView(42, SimpleNamespace(remove_favorite=Mock(side_effect=ValueError('変更済み'))), 'ロザリー')
        interaction = self.interaction()
        await view.finish(interaction, remove=True)
        self.assertFalse(view.finished)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        interaction.edit_original_response.assert_not_awaited()
        view.stop()

    async def test_beginner_instructions_and_timeouts_are_visible(self):
        presents = PresentView(42, None, 'ロザリー', {'magic': 1}, 100)
        self.assertIn('好感度が上限のため、喜ばれる贈り物を送ってパーフェクトリンクを達成しよう', presents.embed().description)
        self.assertIn('3分', presents.embed().footer.text)
        quiz = QuizView(42)
        self.assertIn('/クイズ', quiz.embed().footer.text)
        self.assertIn('3分', quiz.embed().footer.text)
        quiz.finished = True
        self.assertFalse(quiz.embed().footer.text)
        titles = TitleView(42, [('fortune10', '神頼み', None)], None, guild=SimpleNamespace(id=1))
        self.assertIn('称号を選択 →「装着」', titles.embed().description)
        for view in (presents, quiz, titles):
            view.stop()
