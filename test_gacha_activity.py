import unittest
from gacha_activity import DrawActivity
from gacha import Card
from gacha_commands import collection_facts, gacha_comment, rapid_comment_counts_match
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
        self.assertIn('3回', text)
        self.assertLessEqual(len(text), 140)
        self.assertFalse(collection_facts('vierge', cards, rapid_count=2)['rapid_draws'])
        self.assertNotIn('球筋に出てるぜ', gacha_comment('vierge', cards, rapid_count=2))

    def test_five_runs_are_not_five_cards_in_both_games(self):
        for game, rarities in [('vierge', ['SR', 'HR', 'HR', 'HR', 'R', 'R', 'R']),
                                ('relink', ['★2'] + ['★1'] * 9)]:
            cards = [Card(str(i), 'ロザリー', 'ロザリー', rarity) for i, rarity in enumerate(rarities)]
            facts = collection_facts(game, cards, rapid_count=5)
            self.assertEqual(facts['rapid_count'], 5)
            self.assertEqual(facts['batch_card_count'], len(cards))
            self.assertFalse(rapid_comment_counts_match(facts, '一気に5枚も引くなんて！ 球筋に出てるぜ！'))
            self.assertFalse(rapid_comment_counts_match(facts, '5回で一気に5枚！ 球筋に出てるぜ！'))
            self.assertFalse(rapid_comment_counts_match(facts, '15回も引くなんて！ 球筋に出てるぜ！'))
            self.assertTrue(rapid_comment_counts_match(facts, f'5回も引いたんだな！ 今回は{len(cards)}枚だぜ！'))
            fallback = gacha_comment(game, cards, rapid_count=5)
            self.assertIn('5回', fallback)
            self.assertIn('球筋に出てるぜ', fallback)
            self.assertTrue(rapid_comment_counts_match(facts, fallback))
