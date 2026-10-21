import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import test_presents
from database import MemoryUnavailable


class FortuneSupportTests(unittest.TestCase):
    setUp = test_presents.StorageTests.setUp
    set_favorite = test_presents.StorageTests.set_favorite

    def test_album_support_first_date_is_per_person_and_retained(self):
        with patch('presents.draw_present', return_value='food'):
            self.store.claim(42, 700, '吉', '日向美海')
            self.assertIsNone(self.store.album(42, 'ロザリー')[5])
            self.store.claim(42, 701, '吉', 'ロザリー')
            first = self.store.album(42, 'ロザリー')[5]
            self.assertIsNotNone(first)
            self.assertIsNone(self.store.album(43, 'ロザリー')[5])
            self.assertIsNone(self.store.album(42, '日向美海')[5])
            self.store.claim(42, 701, '吉', 'ロザリー')
            self.day += timedelta(days=1)
            self.store.claim(42, 702, '吉', 'ロザリー')
            self.assertEqual(self.store.album(42, 'ロザリー')[5], first)

    def test_late_matches_count_every_run_but_gifts_are_daily(self):
        with patch('presents.draw_present', return_value='food'), patch('fortune_rewards.random.choice', return_value='book'):
            self.store.claim(42, 100, '吉', '日向美海')
            result = self.store.claim(42, 101, '大吉', 'ロザリー')
            self.assertFalse(result['granted'])
            self.assertEqual(result['bonus_item'], 'book')
            self.assertEqual(result['lucky_progress'], 'ロザリー')
            self.assertEqual(self.store.claim(42, 101, '凶', '日向美海'), result)
            again = self.store.claim(42, 102, '中吉', 'ロザリー')
            self.assertIsNone(again['bonus_item'])
            self.assertEqual(self.store.inventory(42), {'food': 1, 'book': 1})
            state = json.loads(self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()[0])
            self.assertEqual(state['fortunes'], 3)
            self.assertEqual(state['support_matches'], 2)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE title_key='support'").fetchone()[0], 1)
            self.day += timedelta(days=1)
            next_day = self.store.claim(42, 103, '吉', 'ロザリー')
            self.assertTrue(next_day['granted'])
            self.assertEqual(next_day['bonus_item'], 'book')
            self.assertEqual(self.store.inventory(42), {'food': 2, 'book': 2})

    def test_concurrent_late_matches_only_give_one_support_item(self):
        with patch('presents.draw_present', return_value='food'), patch('fortune_rewards.random.choice', return_value='book'):
            self.store.claim(42, 100, '吉', '日向美海')
            with ThreadPoolExecutor(2) as executor:
                results = list(executor.map(lambda number: self.store.claim(42, number, '吉', 'ロザリー'), (101, 102)))
            self.assertEqual(sum(result['bonus_item'] is not None for result in results), 1)
            self.assertEqual(self.store.inventory(42), {'food': 1, 'book': 1})

    def test_legacy_bonus_already_paid_today_does_not_duplicate(self):
        with patch('presents.draw_present', return_value='food'), patch('fortune_rewards.random.choice', return_value='book'):
            self.store.claim(42, 100, '吉', 'ロザリー')
            self.db.execute('DELETE FROM george_fortune_runs')
            self.db.execute('DELETE FROM george_fortune_bonus_daily')
            self.db.commit()
            result = self.store.claim(42, 101, '大吉', 'ロザリー')
            self.assertTrue(result['support_matched'])
            self.assertIsNone(result['bonus_item'])
            self.assertEqual(self.store.inventory(42), {'food': 1, 'book': 1})

    def test_receipt_failure_rolls_back_gifts_titles_and_daily_limit(self):
        self.fail_on = 'INSERT INTO george_fortune_runs'
        with self.assertRaises(MemoryUnavailable):
            self.store.claim(42, 100, '吉', 'ロザリー')
        self.fail_on = None
        self.assertEqual(self.store.inventory(42), {})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_present_daily').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_fortune_bonus_daily').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_titles').fetchone()[0], 0)

    def test_retry_cannot_claim_another_users_result(self):
        self.store.claim(42, 100, '吉', 'ロザリー')
        with self.assertRaises(ValueError):
            self.store.claim(43, 100, '吉', 'ロザリー')
