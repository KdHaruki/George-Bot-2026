import unittest
from bot_guide import bot_guide_context, title_fact_answer
from title_core import COMMON, title_condition


class FeatureFactTests(unittest.TestCase):
    def test_guide_uses_live_title_conditions_without_dummy_progress(self):
        guide = bot_guide_context()
        for key, name in COMMON.items():
            self.assertIn(name, guide)
            self.assertIn(title_condition(key), guide)
        self.assertNotIn('進捗：0/', guide)
        self.assertIn('初めての応援ボーナス', guide)
        self.assertNotIn('/季節通知', guide)
        self.assertNotIn('/状態', guide)
        self.assertIn('7〜10枚', guide)

    def test_factual_routing_does_not_intercept_casual_conversation(self):
        self.assertIsNone(title_fact_answer('青蘭学園の叛逆者ってかっこいいね'))
        self.assertIsNone(title_fact_answer('おみくじの遊び方を教えて'))
        answer = title_fact_answer('青蘭学園の超大吉の取得条件は？')
        self.assertIn('大吉を3回連続', answer)
        self.assertNotIn('UR', answer)


class GiftFactTests(unittest.TestCase):
    def test_every_named_profile_uses_exact_item_preferences(self):
        from bot_guide import gift_fact_answer
        from present_catalog import preferred_items, ITEMS, NORMAL_ITEMS
        from progress import progressData
        for record in progressData:
            name = record['progressName']
            answer = gift_fact_answer(f'{name}に喜ばれる贈り物は何？')
            for item in NORMAL_ITEMS:
                self.assertEqual(ITEMS[item][1] in answer, item in preferred_items(name), (name, item))

    def test_missing_favorite_never_guesses_and_explicit_name_wins(self):
        from bot_guide import gift_fact_answer
        self.assertIn('名前を教えて', gift_fact_answer('その子に喜ばれる贈り物は？'))
        explicit = gift_fact_answer('ロザリーに喜ばれる贈り物は何？', {'character': '日向美海'})
        self.assertIn('ロザリー', explicit)
        self.assertIn('魔道書', explicit)
        self.assertNotIn('工具セット', explicit)
        self.assertIsNone(gift_fact_answer('今日は贈り物を渡したよ'))
