import json
import unittest
from unittest.mock import patch

import test_presents
from title_store import TitleStore


class QuizRoundTests(unittest.TestCase):
    setUp = test_presents.StorageTests.setUp
    set_favorite = test_presents.StorageTests.set_favorite

    def streak(self):
        row = self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()
        return json.loads(row[0]).get('quiz_streak', 0) if row else 0

    def test_ten_first_correct_same_day_grants_once_without_daily_reward(self):
        for number in range(1, 11):
            self.store.start_quiz_round(42, number)
            self.store.resolve_quiz_round(42, number, True)
            self.store.resolve_quiz_round(42, number, True)
            self.assertEqual(self.streak(), number)
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM george_titles WHERE title_key='quiz_streak10'").fetchone())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE title_key='quiz_streak10'").fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_quiz_daily').fetchone()[0], 0)

    def test_wrong_answer_abandoned_round_and_old_buttons_cannot_extend_streak(self):
        self.store.start_quiz_round(42, 1)
        self.store.resolve_quiz_round(42, 1, True)
        self.store.start_quiz_round(42, 2)
        self.store.resolve_quiz_round(42, 2, False)
        self.store.resolve_quiz_round(42, 2, True)
        self.assertEqual(self.streak(), 0)
        self.store.start_quiz_round(42, 3)
        self.store.resolve_quiz_round(42, 3, True)
        self.store.start_quiz_round(42, 4)
        self.store.start_quiz_round(42, 5)
        self.assertEqual(self.streak(), 0)
        self.store.resolve_quiz_round(42, 4, True)
        self.assertEqual(self.streak(), 0)
        self.store.resolve_quiz_round(42, 5, True)
        self.assertEqual(self.streak(), 1)

    def test_expired_round_after_restart_is_reset_on_title_check(self):
        with patch('quiz_rounds.time.time', return_value=1000):
            self.store.start_quiz_round(42, 1)
            self.store.resolve_quiz_round(42, 1, True)
            self.store.start_quiz_round(42, 2)
        self.assertEqual(self.streak(), 1)
        with patch('quiz_rounds.time.time', return_value=1181):
            TitleStore('unused').titles(42)
        self.assertEqual(self.streak(), 0)
        self.store.resolve_quiz_round(42, 2, True)
        self.assertEqual(self.streak(), 0)

    def test_same_round_start_is_idempotent_and_users_are_isolated(self):
        self.store.start_quiz_round(42, 100)
        self.store.resolve_quiz_round(42, 100, True)
        self.store.start_quiz_round(42, 100)
        self.store.resolve_quiz_round(42, 100, True)
        self.assertEqual(self.streak(), 1)
        self.store.start_quiz_round(43, 101)
        self.store.resolve_quiz_round(43, 101, False)
        self.assertEqual(self.streak(), 1)
