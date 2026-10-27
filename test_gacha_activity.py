import unittest
from gacha_activity import DrawActivity
from gacha import Card
from gacha_commands import collection_facts, gacha_comment
from progress_profiles import george_name


class DrawActivityTests(unittest.TestCase):
    def test_window_duplicate_user_isolation_and_capacity(self):
        tracker = DrawActivity()
        self.assertEqual(tracker.record(1, 10, now=0), 1)
        self.assertEqual(tracker.record(1, 11, now=50), 2)
        self.assertEqual(tracker.record(1, 12, now=100), 3)
        self.assertEqual(tracker.record(1, 12, now=101), 3)
        self.assertEqual(tracker.record(2, 13, now=101), 1)
        self.assertEqual(tracker.record(1, 14, now=300), 1)
        tracker.MAX_USERS = 2
        tracker.record(3, 15, now=301)
        self.assertEqual(len(tracker.users), 2)

    def test_favorite_and_two_highest_and_rapid_draw_all_survive_fallback(self):
        cards = [Card('a', 'ロザリー', 'ロザリー', 'UR'), Card('b', 'ソフィーナ', 'ソフィーナ', 'UR')]
        favorite = ('relink', Card('r', 'ロザリー', 'ロザリー', '★3'), 1)
        facts = collection_facts('vierge', cards, favorite=favorite, rapid_count=3)
        self.assertNotEqual(facts['favorite_relation'], 'none')
        self.assertEqual(facts['highest_count'], 2)
        self.assertTrue(facts['rapid_draws'])
        text = gacha_comment('vierge', cards, favorite=favorite, rapid_count=3)
        self.assertIn(george_name('ロザリー'), text)
        self.assertIn('URが2枚', text)
        self.assertIn('球筋に出てるぜ', text)
        self.assertLessEqual(len(text), 140)
        self.assertFalse(collection_facts('vierge', cards, rapid_count=2)['rapid_draws'])
        self.assertNotIn('球筋に出てるぜ', gacha_comment('vierge', cards, rapid_count=2))
