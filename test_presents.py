from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from gacha_collection import CollectionStore
from presents import PresentStore, RARE_RATES, ITEMS, draw_present, draw_quiz_present, affection_gain, character_key, profile_for, affection_display
from present_view import PresentView
from registered_memory import MemoryUnavailable
from favorite_album import ensure_album, record_registration, album_display
from title_core import ensure_titles
from daily_affection import ensure_daily


class PresentRulesTests(unittest.TestCase):
    def test_relink_item_names_keep_existing_inventory_ids(self):
        self.assertEqual({key: value[1] for key, value in ITEMS.items()}, {
            'sweets': 'チョコクッキー', 'food': '紅茶', 'fashion': 'リボン', 'mirror': '手鏡',
            'book': '本', 'pen': '万年筆', 'game': 'ぬいぐるみ', 'music': 'オルゴール',
            'towel': 'タオル', 'charm': 'お守り', 'magic': '魔道書', 'tools': '工具セット',
            'plant': '鉢植え', 'aroma': 'アロマセット', 'rare': '花束（虹）'})
        self.assertEqual(affection_gain('ロザリー', 'magic'), 5)
        self.assertEqual(affection_gain('不明な人物', 'game'), 2)

    def test_seven_categories_cover_all_characters_and_both_items_are_preferred(self):
        from present_catalog import CATEGORIES, preferred_categories, preferred_items
        from progress import progressData
        self.assertEqual(len(CATEGORIES), 7)
        self.assertTrue(all(len(items) == 2 for _, items in CATEGORIES.values()))
        self.assertEqual(len(ITEMS), 15)
        for person in progressData:
            name = person['progressName']
            categories = preferred_categories(name)
            self.assertIn(len(categories), (1, 2), name)
            self.assertEqual(set(preferred_items(name)), {item for category in categories for item in CATEGORIES[category][1]})
            for item in preferred_items(name):
                self.assertEqual(affection_gain(name, item), 5, (name, item))
            self.assertEqual(affection_gain(name, 'rare'), 10)
        self.assertEqual(preferred_items('美海'), preferred_items('日向美海'))
        self.assertEqual(preferred_items('不明な人物'), ())

    def test_quiz_rare_chances_by_attempts(self):
        for attempts, rate in [(1, 10), (2, 5), (3, 4), (4, 3)]:
            for roll in range(100):
                rng = Mock()
                rng.randrange.return_value = roll
                rng.choice.return_value = 'book'
                self.assertEqual(draw_quiz_present(attempts, rng) == 'rare', roll < rate)
        for attempts in (0, 5):
            with self.assertRaises(ValueError):
                draw_quiz_present(attempts)

    def test_gauge_and_numbers_at_boundaries(self):
        for points, filled in [(0, 0), (35, 3), (99, 9), (100, 10), (150, 10)]:
            text = affection_display(points)
            self.assertIn(f'{min(points, 100)}/100', text)
            self.assertEqual(text.count('🟪'), filled)
            self.assertEqual(text.count('⬜'), 10 - filled)

    def test_exact_rare_boundaries_for_every_fortune(self):
        self.assertEqual(RARE_RATES, {'大吉': 10, '吉': 5, '中吉': 4, '小吉': 3, '末吉': 2, '凶': 1})
        for fortune, rate in RARE_RATES.items():
            for number in range(100):
                rng = Mock()
                rng.randrange.return_value = number
                rng.choice.return_value = 'book'
                self.assertEqual(draw_present(fortune, rng) == 'rare', number < rate)
                if number >= rate:
                    self.assertEqual(set(rng.choice.call_args.args[0]), set(ITEMS) - {'rare'})

    def test_gains_and_character_aliases(self):
        self.assertEqual(affection_gain('ロザリー', 'magic'), 5)
        self.assertEqual(affection_gain('ロザリー', 'food'), 2)
        self.assertEqual(affection_gain('ロザリー', 'rare'), 10)
        self.assertEqual(character_key('久遠 空'), '久遠空')
        self.assertEqual(affection_gain('不明な人物', 'rare'), 10)
        self.assertEqual(affection_gain('不明な人物', 'food'), 2)

    def test_all_relink_characters_resolve_to_shared_profiles(self):
        from gacha import Gacha
        for pool in Gacha().pools['relink'].values():
            for card in pool:
                self.assertIsNotNone(profile_for(card.character), card.character)
        self.assertEqual(character_key('空'), '久遠空')
        self.assertEqual(character_key('ユフィ'), 'コードΩ00ユーフィリア')


class StorageTests(unittest.TestCase):
    """Exercise transaction behavior with SQLite, adapting only PostgreSQL syntax."""
    def setUp(self):
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.lock = threading.RLock()
        self.day = date(2026, 10, 19)
        self.fail_on = None
        self.db.execute('CREATE TABLE george_gacha_cards(user_id,game,card_id,card)')
        self.db.execute('CREATE TABLE george_gacha_favorites(user_id,game,card_id)')
        ensure_album(self.db)
        ensure_daily(self.db)
        ensure_titles(self.db)
        self.set_favorite('ロザリー')
        self.store = PresentStore('unused')
        test = self

        class Adapter:
            def execute(self, sql, params=()):
                if test.fail_on and sql.startswith(test.fail_on):
                    raise MemoryUnavailable('offline')
                if 'pg_advisory' in sql:
                    return None
                if 'AT TIME ZONE' in sql:
                    return SimpleNamespace(fetchone=lambda: (test.day,))
                if sql.startswith('SELECT character,last_day'):
                    row = test.db.execute(sql.replace('%s', '?'), params).fetchone()
                    return SimpleNamespace(fetchone=lambda: (row[0], date.fromisoformat(row[1])) if row else None)
                if sql.startswith('SELECT reward_day'):
                    row = test.db.execute(sql.replace('%s', '?'), params).fetchone()
                    return SimpleNamespace(fetchone=lambda: (date.fromisoformat(row[0]), *row[1:]) if row else None)
                if sql.startswith('SELECT c.card'):
                    row = test.db.execute(sql.replace('%s', '?'), params).fetchone()
                    return SimpleNamespace(fetchone=lambda: (json.loads(row[0]),) if row else None)
                if sql.startswith('SELECT card,quantity'):
                    row = test.db.execute(sql.replace('%s', '?'), params).fetchone()
                    return SimpleNamespace(fetchone=lambda: (json.loads(row[0]), row[1]) if row else None)
                if sql.startswith('SELECT f.user_id,c.card'):
                    rows = test.db.execute(sql.replace('%s', '?'), params).fetchall()
                    return SimpleNamespace(fetchall=lambda: [(uid, json.loads(payload)) for uid, payload in rows])
                if sql.startswith(('SELECT first_registered_at', 'SELECT achieved_at', 'SELECT acquired_at')):
                    row = test.db.execute(sql.replace('%s', '?'), params).fetchone()
                    return SimpleNamespace(fetchone=lambda: tuple((datetime.fromisoformat(v) if datetime.fromisoformat(v).tzinfo else datetime.fromisoformat(v).replace(tzinfo=timezone.utc)) if v else None for v in row) if row else None)
                if sql.startswith(('DELETE FROM george_present_receipts', 'DELETE FROM george_title_events')):
                    return SimpleNamespace(rowcount=0)
                sql = sql.replace("CURRENT_TIMESTAMP-INTERVAL '365 days'", "datetime(CURRENT_TIMESTAMP, '-365 days')")
                params = tuple(value.isoformat() if isinstance(value, date) else value for value in params)
                return test.db.execute(sql.replace('%s', '?').replace('DEFAULT NOW()', 'DEFAULT CURRENT_TIMESTAMP'), params)

        @contextmanager
        def connection(_store):
            with test.lock, test.db:
                yield Adapter()

        self.patch = patch.object(CollectionStore, 'connect', connection)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.db.close)

    def set_favorite(self, name):
        self.db.execute('DELETE FROM george_gacha_favorites')
        self.db.execute('DELETE FROM george_gacha_cards')
        if name:
            self.db.execute('INSERT INTO george_gacha_cards VALUES (42,?,?,?)', ('relink', 'id', json.dumps({'character': name})))
            self.db.execute("INSERT INTO george_gacha_favorites VALUES (42,'relink','id')")
        self.db.commit()

    def claim(self, interaction=100):
        with patch('presents.draw_present', return_value='magic'):
            return self.store.claim(42, interaction, '大吉')

    def test_daily_limit_retry_new_day_and_user_isolation(self):
        self.assertTrue(self.claim()['granted'])
        self.assertTrue(self.claim()['granted'])
        self.assertFalse(self.claim(101)['granted'])
        self.assertEqual(self.store.snapshot(42)[1], {'magic': 1})
        self.day = date(2026, 10, 20)
        self.assertTrue(self.claim(102)['granted'])
        self.assertEqual(self.store.snapshot(42)[1], {'magic': 2})
        with patch('presents.draw_present', return_value='food'):
            self.assertTrue(self.store.claim(43, 103, '凶')['granted'])

    def test_spend_is_idempotent_and_affection_survives_favorite_changes(self):
        self.claim()
        self.assertEqual(self.store.give(42, 200, 'ロザリー', 'magic'), (5, 5, False))
        self.assertEqual(self.store.give(42, 200, 'ロザリー', 'magic'), (5, 5, False))
        self.assertEqual(self.store.snapshot(42)[1], {})
        with self.assertRaises(ValueError):
            self.store.give(42, 201, 'ロザリー', 'magic')
        self.assertEqual(self.store.points(42, 'ロザリー'), 5)
        self.assertEqual(self.store.points(43, 'ロザリー'), 0)
        self.set_favorite('日向美海')
        self.assertEqual(self.store.snapshot(42)[2], 0)
        self.set_favorite('ロザリー')
        self.assertEqual(self.store.snapshot(42)[2], 5)

    def test_changed_or_missing_favorite_does_not_consume(self):
        self.claim()
        self.set_favorite('日向美海')
        with self.assertRaises(ValueError):
            self.store.give(42, 200, 'ロザリー', 'magic')
        self.assertEqual(self.store.snapshot(42)[1], {'magic': 1})
        self.set_favorite(None)
        with self.assertRaises(ValueError):
            self.store.give(42, 201, 'ロザリー', 'magic')

    def test_parallel_claims_only_add_one(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(self.claim, (100, 101)))
        self.assertEqual(sum(r['granted'] for r in results), 1)
        self.assertEqual(sum(self.store.snapshot(42)[1].values()), 1)

    def test_failed_affection_write_rolls_back_consumption(self):
        self.claim()
        self.fail_on = 'INSERT INTO george_affection'
        with self.assertRaises(MemoryUnavailable):
            self.store.give(42, 200, 'ロザリー', 'magic')
        self.fail_on = None
        self.assertEqual(self.store.snapshot(42)[1], {'magic': 1})
        self.assertEqual(self.store.points(42, 'ロザリー'), 0)
        self.assertEqual(self.store.give(42, 200, 'ロザリー', 'magic'), (5, 5, False))

    def test_parallel_spend_cannot_make_quantity_negative(self):
        from concurrent.futures import ThreadPoolExecutor
        self.claim()

        def give(number):
            try:
                return self.store.give(42, number, 'ロザリー', 'magic')
            except ValueError:
                return None

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(give, (200, 201)))
        self.assertEqual(results.count((5, 5, False)), 1)
        self.assertEqual(self.store.points(42, 'ロザリー'), 5)

    def test_claim_without_favorite_and_alias_shared_across_costumes(self):
        self.set_favorite(None)
        self.assertTrue(self.claim()['granted'])
        self.set_favorite('美海')
        self.store.give(42, 200, '日向美海', 'magic')
        self.set_favorite('日向美海')
        self.assertEqual(self.store.snapshot(42)[2], 2)

    def test_cap_and_gifts_at_full_consume_but_add_zero(self):
        self.claim()
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',99)")
        self.db.commit()
        self.assertEqual(self.store.give(42, 200, 'ロザリー', 'magic'), (1, 100, False))
        self.day = date(2026, 10, 20)
        self.claim(101)
        self.assertEqual(self.store.give(42, 201, 'ロザリー', 'magic'), (0, 100, True))
        self.assertEqual(self.store.snapshot(42)[1], {})
        self.assertEqual(self.store.points(42, 'ロザリー'), 100)

    def test_perfect_link_requires_preexisting_hundred_and_preferred_gift(self):
        self.claim()
        self.db.execute("UPDATE george_present_items SET quantity=5 WHERE user_id=42")
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',99)")
        self.db.execute("INSERT INTO george_present_items VALUES (42,'rare',1)")
        self.db.execute("INSERT INTO george_present_items VALUES (42,'food',1)")
        self.db.commit()
        self.assertEqual(self.store.give(42, 200, 'ロザリー', 'magic'), (1, 100, 0))
        self.assertEqual(self.store.give(42, 201, 'ロザリー', 'rare'), (0, 100, 0))
        self.assertEqual(self.store.give(42, 202, 'ロザリー', 'food'), (0, 100, 0))
        self.assertEqual(self.store.give(42, 203, 'ロザリー', 'magic'), (0, 100, 1))
        self.assertEqual(self.store.give(42, 203, 'ロザリー', 'magic'), (0, 100, 1))
        self.assertEqual(self.store.inventory(42), {'magic': 3})
        self.assertEqual(self.store.give(42, 204, 'ロザリー', 'magic'), (5, 105, 1))
        self.assertIsNotNone(self.store.album(42, 'ロザリー')[3])
        self.set_favorite('美海')
        self.assertFalse(self.store.snapshot(42)[3])
        self.set_favorite('ロザリー')
        self.assertEqual(PresentStore('unused').affection_status(42, 'ロザリー'), (105, 1))

    def test_perfect_link_rollback_and_parallel_gifts_advance_once_then_continue(self):
        from concurrent.futures import ThreadPoolExecutor
        self.claim()
        self.db.execute("UPDATE george_present_items SET quantity=3 WHERE user_id=42")
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',100)")
        self.db.commit()
        self.fail_on = 'INSERT INTO george_perfect_links'
        with self.assertRaises(MemoryUnavailable):
            self.store.give(42, 200, 'ロザリー', 'magic')
        self.fail_on = None
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (100, False))
        self.assertEqual(self.store.inventory(42), {'magic': 3})

        def give(number):
            try:
                return self.store.give(42, number, 'ロザリー', 'magic')
            except ValueError:
                return None

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(give, (201, 202)))
        self.assertEqual(results.count((0, 100, True)), 1)
        self.assertEqual(results.count((5, 105, 1)), 1)
        self.assertEqual(self.store.inventory(42), {'magic': 1})
        self.assertEqual(self.store.affection_status(43, 'ロザリー'), (0, False))

    def test_quiz_reward_independent_daily_limit_and_next_day(self):
        self.claim()
        with patch('presents.draw_quiz_present', return_value='food') as choose:
            self.assertTrue(self.store.claim_quiz(42, 300)['granted'])
            choose.assert_called_once_with(1)
            self.assertTrue(self.store.claim_quiz(42, 300)['granted'])
            self.assertFalse(self.store.claim_quiz(42, 301)['granted'])
            self.assertEqual(self.store.snapshot(42)[1], {'food': 1, 'magic': 1})
            self.day = date(2026, 10, 20)
            self.assertTrue(self.store.claim_quiz(42, 302)['granted'])
            self.assertTrue(self.store.claim_quiz(43, 303)['granted'])
            self.assertEqual(self.store.snapshot(42)[1]['food'], 2)

    def test_album_first_dates_are_retained_and_no_history_is_invented(self):
        self.assertEqual(self.store.album(42, 'ロザリー'), (None, None, None, None, None))
        with self.store.connect() as connection:
            record_registration(connection, 42, 'ロザリー')
        first = self.store.album(42, 'ロザリー')[0]
        self.claim()
        self.store.give(42, 200, 'ロザリー', 'magic')
        dates = self.store.album(42, 'ロザリー')
        self.assertEqual(dates[0], first)
        self.assertIsNone(dates[1])
        self.assertIsNone(dates[2])
        self.db.execute("UPDATE george_affection SET points=99 WHERE user_id=42")
        self.db.commit()
        self.day = date(2026, 10, 20)
        self.claim(101)
        self.store.give(42, 201, 'ロザリー', 'magic')
        completed = self.store.album(42, 'ロザリー')
        self.assertEqual(completed[:2], dates[:2])
        self.assertIsNotNone(completed[2])
        with self.store.connect() as connection:
            record_registration(connection, 42, 'ロザリー')
        self.assertEqual(self.store.album(42, 'ロザリー'), completed)
        self.assertEqual(self.store.album(43, 'ロザリー'), (None, None, None, None, None))

    def test_album_dates_use_japan_time(self):
        text = album_display((datetime(2026, 10, 19, 16, tzinfo=timezone.utc), None, None,
                              datetime(2026, 10, 20, 16, tzinfo=timezone.utc)))
        self.assertIn('お気に入り登録日：2026年10月20日', text)
        self.assertNotIn('専属αドライバー', text)
        self.assertNotIn('初プレゼント', text)
        self.assertNotIn('好感度100達成', text)
        self.assertEqual(len(text.splitlines()), 3)
        self.assertIn('パーフェクトリンク達成：2026年10月21日', text)
        self.assertEqual(text.splitlines()[-1], 'パーフェクトリンク達成：2026年10月21日')

    def test_album_uses_existing_perfect_link_timestamp_without_rewriting(self):
        self.assertIsNone(self.store.album(42, 'ロザリー')[3])
        self.db.execute("INSERT INTO george_perfect_links VALUES (42,'ロザリー','2026-10-19T16:00:00+00:00')")
        self.db.commit()
        dates = self.store.album(42, 'ロザリー')
        self.assertEqual(dates[:3], (None, None, None))
        self.assertIn('パーフェクトリンク達成：2026年10月20日', album_display(dates))
        self.assertEqual(self.store.album(42, 'ロザリー'), dates)
        self.assertIsNone(self.store.album(43, 'ロザリー')[3])


    def test_retired_anniversary_title_is_not_read_or_shown_in_album(self):
        self.db.execute("INSERT INTO george_titles VALUES (42,'anniversary:ロザリー','ロザリーの専属αドライバー','2026-10-19T00:00:00+00:00')")
        self.db.commit()
        dates = self.store.album(42, 'ロザリー')
        self.assertIsNone(dates[1])
        self.assertNotIn('専属αドライバー', album_display(dates))
        self.assertEqual(len(album_display(dates).splitlines()), 3)
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM george_titles WHERE title_key='anniversary:ロザリー'").fetchone())

    def test_completion_requires_both_games_and_retains_first_date(self):
        from favorite_album import collection_targets, record_completions
        required = sorted(collection_targets()['ロザリー'])
        self.assertEqual({game for game, _ in required}, {'vierge', 'relink'})
        for game, card_id in required[:-1]:
            self.db.execute('INSERT INTO george_gacha_cards VALUES (42,?,?,?)', (game, card_id, '{}'))
        self.db.commit()
        self.assertIsNone(self.store.album(42, 'ロザリー')[4])
        game, card_id = required[-1]
        self.db.execute('INSERT INTO george_gacha_cards VALUES (42,?,?,?)', (game, card_id, '{}'))
        self.db.commit()
        with self.store.connect() as conn:
            record_completions(conn, 42, ('ロザリー',))
        dates = self.store.album(42, 'ロザリー')
        self.assertIsNotNone(dates[4])
        self.assertIsNone(self.db.execute("SELECT 1 FROM george_titles WHERE user_id=42 AND title_key='collection:ロザリー'").fetchone())
        self.assertIn('カード全種類収集：', album_display(dates))
        self.db.execute("UPDATE george_character_completions SET achieved_at='2026-10-01T00:00:00+00:00'")
        self.db.commit()
        self.assertEqual(self.store.album(42, 'ロザリー')[4].day, 1)
        self.assertIsNone(self.store.album(43, 'ロザリー')[4])

    def test_album_failure_rolls_back_item_and_points_together(self):
        self.claim()
        self.fail_on = 'INSERT INTO george_favorite_album'
        with self.assertRaises(MemoryUnavailable):
            self.store.give(42, 200, 'ロザリー', 'magic')
        self.fail_on = None
        self.assertEqual(self.store.snapshot(42)[1], {'magic': 1})
        self.assertEqual(self.store.points(42, 'ロザリー'), 0)
        self.assertEqual(self.store.album(42, 'ロザリー'), (None, None, None, None, None))

    def test_parallel_quiz_correct_answers_only_award_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda number: self.store.claim_quiz(42, number), (300, 301)))
        self.assertEqual(sum(r['granted'] for r in results), 1)
        self.assertEqual(sum(self.store.snapshot(42)[1].values()), 1)

    def test_support_bonus_matches_aliases_and_retry_never_duplicates(self):
        self.set_favorite('美海')
        with patch('presents.draw_present', return_value='rare'), patch('presents.random.choice', return_value='food'):
            result = self.store.claim(42, 100, '大吉', '日向美海')
            self.assertEqual(result['bonus_item'], 'food')
            self.assertEqual(result['lucky_progress'], '日向美海')
            self.assertEqual(self.store.snapshot(42)[1], {'rare': 1, 'food': 1})
            self.set_favorite('ロザリー')
            retry = self.store.claim(42, 100, '凶', 'ロザリー')
            self.assertEqual(retry, result)
            later = self.store.claim(42, 101, '大吉', 'ロザリー')
            self.assertFalse(later['granted'])
            self.assertEqual(self.store.snapshot(42)[1], {'rare': 1, 'food': 1})

    def test_support_bonus_can_be_won_later_but_only_one_item_daily(self):
        with patch('presents.draw_present', return_value='food'), patch('fortune_rewards.random.choice', return_value='book'):
            first = self.store.claim(42, 100, '大吉', '日向美海')
            self.assertIsNone(first['bonus_item'])
            later = self.store.claim(42, 101, '大吉', 'ロザリー')
            self.assertFalse(later['granted'])
            self.assertEqual(later['bonus_item'], 'book')
            self.assertEqual(self.store.snapshot(42)[1], {'food': 1, 'book': 1})
            again = self.store.claim(42, 102, '吉', 'ロザリー')
            self.assertIsNone(again['bonus_item'])
            self.assertTrue(again['support_matched'])
            self.assertEqual(self.store.snapshot(42)[1], {'food': 1, 'book': 1})
            self.assertIsNotNone(self.db.execute("SELECT 1 FROM george_titles WHERE user_id=42 AND title_key='support'").fetchone())



class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_inventory_explains_both_reward_commands(self):
        view = PresentView(42, None, 'ロザリー', {}, 0)
        field = view.embed().fields[0]
        self.assertEqual(field.name, '手持ちのプレゼントはないぜ！')
        self.assertEqual(field.value, '/おみくじ や /クイズ で1日1個もらえるぞ。')
        view.stop()

    async def test_gift_instruction_is_last_and_categories_have_space_above(self):
        view = PresentView(42, None, 'ロザリー', {'magic': 1}, 35)
        text = view.embed().description
        self.assertTrue(text.startswith('好感度：'))
        self.assertIn('\n\n喜ばれる贈り物：', text)
        self.assertNotIn('通常＋2', text)
        self.assertNotIn('好物＋5', text)
        self.assertNotIn('花束（虹）＋10', text)
        self.assertTrue(text.endswith('ボタンを押すと1個贈るぜ！'))
        self.assertEqual(text.count('ボタンを押すと1個贈るぜ！'), 1)
        view.stop()

    async def test_perfect_link_keeps_gifts_enabled_and_only_announces_advancement(self):
        store = SimpleNamespace(give=Mock(side_effect=[(0, 100, 1), (2, 102, 1)]))
        view = PresentView(42, store, 'ロザリー', {'magic': 2, 'food': 1}, 100)
        await view.give(self.interaction(), 'magic')
        self.assertTrue(view.perfect)
        self.assertTrue(all(not button.disabled for button in view.children))
        self.assertIn('パーフェクトリンク', view.embed().description)
        await view.give(self.interaction(201), 'food')
        self.assertEqual(store.give.call_count, 2)
        self.assertEqual(view.items, {'magic': 1, 'food': 0})
        self.assertIn('102/200', view.embed().description)
        view.stop()

    async def test_reopened_perfect_link_view_allows_further_gifts(self):
        from present_view import open_presents
        store = SimpleNamespace(snapshot=Mock(return_value=('ロザリー', {'magic': 1}, 100, True)))
        interaction = self.interaction()
        await open_presents(interaction, store)
        options = interaction.followup.send.call_args.kwargs
        self.assertTrue(options['ephemeral'])
        self.assertTrue(all(not button.disabled for button in options['view'].children))
        self.assertIn('100/200', options['embed'].description)
        self.assertIn('パーフェクトリンク', options['embed'].description)
        options['view'].stop()

    def interaction(self, number=200, user=42):
        return SimpleNamespace(id=number, user=SimpleNamespace(id=user),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))

    async def test_pages_spend_and_duplicate_event(self):
        store = SimpleNamespace(give=Mock(return_value=(5, 5, False)))
        view = PresentView(42, store, 'ロザリー', dict.fromkeys(ITEMS, 1), 0)
        self.assertEqual(len(view.children), 8)
        await view.children[-1].callback(self.interaction())
        self.assertEqual(view.page, 1)
        self.assertEqual(len(view.children), 8)
        await view.children[-1].callback(self.interaction())
        self.assertEqual(view.page, 2)
        self.assertEqual(len(view.children), 5)
        self.assertTrue(view.children[-1].disabled)
        self.assertIn('花束（虹）', view.children[2].label)
        self.assertIn('喜ばれる贈り物', view.embed().description)
        interaction = self.interaction()
        await view.give(interaction, 'magic')
        await view.give(interaction, 'magic')
        store.give.assert_called_once_with(42, 200, 'ロザリー', 'magic')
        self.assertEqual(view.items['magic'], 0)
        self.assertEqual(view.points, 5)
        self.assertFalse(await view.interaction_check(self.interaction(user=43)))
        view.stop()

    async def test_failure_and_timeout_do_not_consume(self):
        store = SimpleNamespace(give=Mock(side_effect=MemoryUnavailable('offline')))
        view = PresentView(42, store, 'ロザリー', {'magic': 1}, 0)
        await view.give(self.interaction(), 'magic')
        self.assertEqual(view.items['magic'], 1)
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        await view.give(self.interaction(201), 'magic')
        store.give.assert_called_once()
        self.assertTrue(all(button.disabled for button in view.children))
        view.stop()
