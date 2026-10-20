import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import test_presents
from title_core import grant
from title_notifications import notify_titles, title_icon


class NotificationStorageTests(unittest.TestCase):
    setUp = test_presents.StorageTests.setUp
    set_favorite = test_presents.StorageTests.set_favorite

    def unlock(self, key='fortune10'):
        with self.store.connect() as conn:
            grant(conn, 42, key)

    def test_first_unlock_only_and_existing_titles_are_not_announced(self):
        self.db.execute("INSERT INTO george_titles VALUES (42,'gift10','青蘭学園のメッセンジャー',CURRENT_TIMESTAMP)")
        self.db.commit()
        self.unlock('gift10')
        self.unlock()
        self.unlock()
        self.assertEqual(self.store.claim_title_notifications(43, 'other'), [])
        self.assertEqual(self.store.claim_title_notifications(42, 'one'), [('fortune10', '今日も神頼み')])
        self.store.finish_title_notifications(42, 'one', True)
        self.unlock()
        self.assertEqual(self.store.claim_title_notifications(42, 'again'), [])

    def test_retired_collection_notice_is_never_delivered(self):
        with self.store.connect() as conn:
            grant(conn, 42, 'collection:ロザリー', 'ロザリーとの縁を紡ぎし者')
        self.unlock()
        self.assertEqual(self.store.claim_title_notifications(42, 'one'), [('fortune10', '今日も神頼み')])



    def test_deleted_title_notices_are_skipped_and_renamed_notices_use_current_name(self):
        from title_core import RETIRED_TITLES
        for key in RETIRED_TITLES | {'affection:ロザリー', 'anniversary:ロザリー'}:
            self.db.execute('INSERT INTO george_title_notices(user_id,title_key,name) VALUES (42,?,?)', (key, key))
        self.db.execute("INSERT INTO george_title_notices(user_id,title_key,name) VALUES (42,'favorite_gift:ロザリー','ロザリーの理解者')")
        self.db.commit()
        rows = self.store.claim_title_notifications(42, 'one')
        self.assertEqual(rows, [('favorite_gift:ロザリー', 'ロザリーの右腕')])
        self.assertEqual(self.store.claim_title_notifications(43, 'other'), [])

    def test_all_green_title_unlock_is_user_scoped_and_idempotent(self):
        from title_core import record_event
        with self.store.connect() as conn:
            record_event(conn, 42, 'all-green:100', 'all_green', game='vierge', count=7, worlds=['緑'])
            record_event(conn, 42, 'all-green:100', 'all_green', game='vierge', count=7, worlds=['緑'])
            record_event(conn, 42, 'all-green:101', 'all_green', game='relink', count=10, worlds=['緑'])
        self.assertEqual(self.store.claim_title_notifications(42, 'one'), [('all_green', '青蘭学園の叛逆者')])
        self.assertEqual(self.store.claim_title_notifications(43, 'other'), [])
        self.store.finish_title_notifications(42, 'one', True)
        self.assertEqual(self.store.claim_title_notifications(42, 'next'), [])

    def test_idol_producer_unlocks_once_and_is_user_scoped(self):
        from title_core import record_event
        with self.store.connect() as conn:
            for event in ('idol-producer:1', 'idol-producer:1', 'idol-producer:2'):
                record_event(conn, 42, event, 'idol_producer', game='vierge', count=7, character='小鳥遊希美', rarity='UR')
        self.assertEqual(self.store.claim_title_notifications(42, 'one'), [('idol_producer', '青蘭学園のアイドルプロデューサー')])
        self.assertEqual(self.store.claim_title_notifications(43, 'other'), [])
        self.store.finish_title_notifications(42, 'one', True)
        self.assertEqual(self.store.claim_title_notifications(42, 'next'), [])

    def test_multiple_unlocks_and_failed_delivery_retry(self):
        self.unlock()
        self.unlock('quiz10')
        rows = self.store.claim_title_notifications(42, 'first')
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.store.claim_title_notifications(42, 'second'), [])
        self.store.finish_title_notifications(42, 'first', False)
        self.assertEqual(self.store.claim_title_notifications(42, 'retry'), rows)
        self.store.finish_title_notifications(42, 'wrong-token', True)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_title_notices').fetchone()[0], 2)
        self.store.finish_title_notifications(42, 'retry', True)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_title_notices').fetchone()[0], 0)

    def test_concurrent_claims_and_expired_lease(self):
        self.unlock()
        with patch('gacha_collection.time.time', return_value=1000):
            with ThreadPoolExecutor(max_workers=2) as executor:
                rows = list(executor.map(lambda token: self.store.claim_title_notifications(42, token), ['a', 'b']))
        self.assertEqual(sum(len(batch) for batch in rows), 1)
        with patch('gacha_collection.time.time', return_value=1121):
            self.assertEqual(len(self.store.claim_title_notifications(42, 'after-restart')), 1)

    def test_notification_insert_failure_rolls_back_unlock(self):
        self.fail_on = 'INSERT INTO george_title_notices'
        with self.assertRaises(Exception):
            self.unlock()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_titles').fetchone()[0], 0)



class NotificationDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_difficult_titles_get_crown_and_mixed_unlocks_keep_each_icon(self):
        for key in ('quiz_streak10',):
            self.assertEqual(title_icon(key), '🎖️')
        for key in ('bond10', 'all_green', 'favorite_gift:ロザリー'):
            self.assertEqual(title_icon(key), '👑')
        for key in ('quiz10', 'affection:ロザリー', 'fortune10', 'variety'):
            self.assertEqual(title_icon(key), '🎖️')
        rows = [('fortune10', '今日も神頼み'), ('quiz_streak10', '青蘭学園の名探偵')]
        store = SimpleNamespace(claim_title_notifications=Mock(side_effect=[rows, []]), finish_title_notifications=Mock())
        interaction = SimpleNamespace(user=SimpleNamespace(id=42), followup=SimpleNamespace(send=AsyncMock()))
        await notify_titles(interaction, store)
        text = interaction.followup.send.call_args.args[0]
        self.assertIn('🎖️ **今日も神頼み**', text)
        self.assertIn('🎖️ **青蘭学園の名探偵**', text)
        self.assertNotIn('🏅', text)
        self.assertNotIn('👑', text)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])

    async def test_batched_notification_is_always_ephemeral_and_no_mentions(self):
        rows = [('fortune10', '今日も神頼み'), ('quiz10', '青蘭学園の知恵袋')]
        store = SimpleNamespace(claim_title_notifications=Mock(side_effect=[rows, []]), finish_title_notifications=Mock())
        interaction = SimpleNamespace(user=SimpleNamespace(id=42), followup=SimpleNamespace(send=AsyncMock()))
        await notify_titles(interaction, store)
        interaction.followup.send.assert_awaited_once()
        call = interaction.followup.send.call_args
        self.assertTrue(call.kwargs['ephemeral'])
        self.assertEqual(call.kwargs['allowed_mentions'].to_dict(), discord.AllowedMentions.none().to_dict())
        self.assertIn('今日も神頼み', call.args[0])
        self.assertIn('青蘭学園の知恵袋', call.args[0])
        self.assertTrue(store.finish_title_notifications.call_args.args[-1])

    async def test_failed_send_releases_for_later_private_retry(self):
        store = SimpleNamespace(claim_title_notifications=Mock(return_value=[('fortune10', '今日も神頼み')]), finish_title_notifications=Mock())
        failure = discord.HTTPException(SimpleNamespace(status=500, reason='test'), 'test')
        interaction = SimpleNamespace(user=SimpleNamespace(id=42), followup=SimpleNamespace(send=AsyncMock(side_effect=failure)))
        await notify_titles(interaction, store)
        self.assertFalse(store.finish_title_notifications.call_args.args[-1])
        store.claim_title_notifications.assert_called_once()

    async def test_no_unlock_sends_nothing(self):
        store = SimpleNamespace(claim_title_notifications=Mock(return_value=[]), finish_title_notifications=Mock())
        interaction = SimpleNamespace(user=SimpleNamespace(id=42), followup=SimpleNamespace(send=AsyncMock()))
        await notify_titles(interaction, store)
        interaction.followup.send.assert_not_awaited()
        store.finish_title_notifications.assert_not_called()
