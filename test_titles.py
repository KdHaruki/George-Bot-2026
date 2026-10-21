import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import test_presents
from title_core import COMMON, NORMAL_GIFTS, event_result, record_event
from title_store import TitleStore
from title_roles import TitleRoles
from title_commands import TitleView
from database import MemoryUnavailable


class TitleRulesTests(unittest.TestCase):
    def test_kaguya_threshold_and_order(self):
        from title_core import pending_titles
        from title_notifications import title_icon
        state = {}
        for result in ['大吉', '大吉', '凶', '大吉', '大吉', '大吉']:
            state, unlocked = event_result(state, 'fortune', {'fortune': result})
            self.assertEqual('kaguya' in dict(unlocked), state['great_streak'] >= 3)
        self.assertEqual(state['great_streak'], 3)
        self.assertEqual(event_result({}, 'kaguya', dict(game='relink', count=10, rare_count=4))[1], [])
        keys = [key for key, _, _ in pending_titles(set(), {}, 0)]
        self.assertEqual(keys[keys.index('all_green') + 1], 'kaguya')
        self.assertEqual(title_icon('kaguya'), '👑')

    def test_special_gift_title_only_for_rainbow_bouquet(self):
        from title_core import pending_titles, title_condition
        from title_notifications import title_icon
        for item in NORMAL_GIFTS:
            self.assertNotIn('special_gift', dict(event_result({}, 'gift', {'item': item})[1]))
        state, unlocked = event_result({}, 'gift', {'item': 'rare'})
        self.assertIn(('special_gift', '青蘭学園のロマンチスト'), unlocked)
        self.assertTrue(state['special_gift_given'])
        self.assertEqual(title_icon('special_gift'), '🎖️')
        self.assertEqual(title_condition('special_gift'), '特別な贈り物をプレゼントする。')
        keys = [key for key, _, _ in pending_titles(set(), {}, 0)]
        self.assertEqual(keys[keys.index('variety') + 1], 'special_gift')


    def test_named_profiles_count_unique_people_and_aliases(self):
        from title_core import pending_titles, title_condition
        from title_notifications import title_icon
        state = {}
        for name in ('美海', '日向美海', '美海'):
            state, unlocked = event_result(state, 'profile_search', {'character': name})
            self.assertEqual(unlocked, [])
        self.assertEqual(len(state['profile_names']), 1)
        keys = [key for key, _, _ in pending_titles(set(), state, 0)]
        self.assertEqual(keys.index('named10'), keys.index('worlds') + 1)
        self.assertEqual(title_icon('named10'), '🎖️')
        self.assertEqual(title_condition('named10'), 'プログレスを累計10人検索する。（世界別の検索は除く）')


    def test_deleted_titles_do_not_unlock_or_appear_and_green_requires_full_batch(self):
        from title_core import RETIRED_TITLES, pending_titles
        self.assertTrue(RETIRED_TITLES.isdisjoint({key for key, _, _ in pending_titles(set(), {}, 100, 'ロザリー')}))
        state = {}
        for _ in range(100):
            state, unlocked = event_result(state, 'fortune', {'fortune': '大吉'})
            self.assertTrue(RETIRED_TITLES.isdisjoint({key for key, _ in unlocked}))
        for game, count in (('vierge', 7), ('relink', 10)):
            facts = dict(game=game, count=count, green_count=7)
            self.assertEqual(event_result({}, 'all_green', facts)[1], [('all_green', '青蘭学園の叛逆者')])
            for change in (dict(count=1), dict(green_count=6), dict(green_count=0), dict(game='invalid')):
                self.assertEqual(event_result({}, 'all_green', facts | change)[1], [])



    def test_quiz_streak_threshold_reset_and_retired_collection(self):
        from title_core import pending_titles
        from title_notifications import title_icon
        state = {}
        for number in range(1, 11):
            state, unlocked = event_result(state, 'quiz_streak', {'correct_first': True})
            self.assertEqual(any(key == 'quiz_streak10' for key, _ in unlocked), number == 10)
        state, unlocked = event_result(state, 'quiz_streak', {'correct_first': False})
        self.assertEqual(state['quiz_streak'], 0)
        self.assertEqual(unlocked, [])
        self.assertNotIn('collection:ロザリー', {row[0] for row in pending_titles(set(), {}, 0, 'ロザリー')})
        self.assertEqual(title_icon('quiz_streak10'), '🎖️')

    def test_earned_conditions_cover_common_and_personal_titles(self):
        from title_core import title_condition
        for key in COMMON:
            self.assertNotIn('確認できません', title_condition(key))
            self.assertTrue(title_condition(key).endswith(('。', '）')))
        self.assertEqual(title_condition('all_green'), '1回のガチャで緑の世界のプログレスを7枚以上引く。')
        self.assertEqual(title_condition('fortune10'), 'おみくじに累計10回挑戦する。')
        self.assertEqual(title_condition('variety'), '贈り物14種類をプレゼントする。（特別な贈り物は除く）')
        self.assertEqual(title_condition('favorite_gift:ロザリー'), '好感度100の状態で喜ばれる贈り物をプレゼントする。')
        self.assertIn('喜ばれる贈り物', title_condition('favorite_gift:ロザリー'))

    def test_pending_conditions_counters_and_favorite_scope(self):
        from title_core import pending_titles
        rows = pending_titles({'fortune10', 'favorite_gift:ロザリー'},
                              {'quiz_first': 7, 'fortunes': 10, 'gift_kinds': ['book', 'rare'], 'worlds': ['赤', '青']},
                              3, 'ロザリー')
        data = {key: condition for key, _, condition in rows}
        self.assertNotIn('fortune10', data)
        self.assertNotIn('favorite_gift:ロザリー', data)
        self.assertIn('7/10回', data['quiz10'])
        self.assertIn('1/14種類', data['variety'])
        self.assertIn('2/5世界', data['worlds'])
        self.assertIn('3/5人', data['bond10'])
        self.assertIn('クイズをヒント1回目で正解', data['quiz10'])
        self.assertNotIn('不正解・時間切れ', data['quiz_streak10'])
        keys = list(data)
        self.assertEqual(keys.index('quiz_streak10'), keys.index('quiz10') + 1)
        self.assertNotIn('triple_rare', keys)
        self.assertNotIn('anniversary:ロザリー', data)
        keys = [key for key, _, _ in rows]
        start = keys.index('variety')
        self.assertEqual(keys[start:start + 4], ['variety', 'special_gift', 'preferred_gifts10:ロザリー', 'worlds'])
        self.assertNotIn('affection:ロザリー', data)
        self.assertNotIn('exchange10', data)
        self.assertFalse(any(':' in key for key, _, _ in pending_titles(set(), {}, 0)))

    def test_all_counter_thresholds_and_exact_names(self):
        for kind, facts, thresholds in [
            ('quiz', {'attempts': 1}, {10: 'quiz10'}),
            ('fortune', {'fortune': '大吉'}, {10: 'fortune10'}),
        ]:
            state = {}
            for number in range(1, max(thresholds) + 1):
                state, unlocked = event_result(state, kind, facts)
                keys = {key for key, _ in unlocked}
                for threshold, key in thresholds.items():
                    self.assertEqual(key in keys, number >= threshold)
        _, unlocked = event_result({}, 'fortune', {'fortune': '凶', 'bonus': True})
        self.assertIn(('support', 'エール・フレンドを受けし者'), unlocked)

    def test_preferred_gifts_count_per_person_and_order_follows_sommelier(self):
        from title_core import pending_titles, title_condition
        from title_notifications import title_icon
        state = {}
        for number in range(1, 11):
            state, unlocked = event_result(state, 'gift', dict(character='美海' if number % 2 else '日向美海', item='book', preferred=True))
            self.assertEqual(any(key == 'preferred_gifts10:日向美海' for key, _ in unlocked), number >= 3)
            self.assertFalse(any(key.startswith('favorite_gift:') for key, _ in unlocked))
        state, _ = event_result(state, 'gift', dict(character='ロザリー', item='magic', preferred=True))
        state, _ = event_result(state, 'gift', dict(character='美海', item='rare', preferred=True))
        state, _ = event_result(state, 'gift', dict(character='美海', item='food', preferred=False))
        self.assertEqual(state['preferred_gift_counts'], {'日向美海': 10, 'ロザリー': 1})
        rows = pending_titles(set(), state, 0, '日向美海')
        keys = [key for key, _, _ in rows]
        self.assertEqual(keys[keys.index('variety') + 2], 'preferred_gifts10:日向美海')
        self.assertIn('3/3個', dict((key, condition) for key, _, condition in rows)['preferred_gifts10:日向美海'])
        self.assertEqual(title_icon('preferred_gifts10:日向美海'), '🎖️')
        self.assertIn('累計3個', title_condition('preferred_gifts10:日向美海'))

    def test_idol_producer_requires_nozomi_ur_in_vierge_seven_and_order(self):
        from title_core import pending_titles, title_condition
        from title_notifications import title_icon
        facts = dict(game='vierge', count=7, character='小鳥遊希美', rarity='UR')
        self.assertEqual(event_result({}, 'idol_producer', facts)[1], [('idol_producer', '青蘭学園のアイドルプロデューサー')])
        for change in (dict(game='relink'), dict(count=1), dict(character='ロザリー'), dict(rarity='SR')):
            self.assertEqual(event_result({}, 'idol_producer', facts | change)[1], [])
        keys = [key for key, _, _ in pending_titles(set(), {}, 0)]
        self.assertEqual(keys.index('favorite_registered') + 1, keys.index('reunion'))
        self.assertLess(keys.index('idol_producer'), keys.index('favorite_registered'))
        self.assertEqual(title_icon('idol_producer'), '🎖️')
        self.assertIn('小鳥遊希美', title_condition('idol_producer'))
        self.assertEqual(title_condition('idol_producer'), 'ガチャでURの小鳥遊希美を獲得する。')

    def test_new_titles_have_requested_order_and_misfortune_counts_all_attempts(self):
        from title_core import pending_titles
        from title_notifications import title_icon
        keys = [key for key, _, _ in pending_titles(set(), {}, 0)]
        self.assertEqual(keys[0], 'quiz10')
        self.assertNotIn('bad10', keys)
        self.assertNotIn('reaction', keys)
        self.assertEqual(keys.index('favorite_registered'), keys.index('reunion') - 1)
        self.assertEqual(keys[keys.index('all_green') + 1:keys.index('all_green') + 4], ['kaguya', 'complete_vierge', 'complete_relink'])
        state = {}
        for number in range(1, 11):
            state, unlocked = event_result(state, 'fortune', {'fortune': '凶'})
            self.assertFalse(any(key == 'bad10' for key, _ in unlocked))
        state, _ = event_result(state, 'fortune', {'fortune': '吉'})
        self.assertNotIn('bad', state)
        for key in ('complete_vierge', 'complete_relink'):
            self.assertEqual(title_icon(key), '👑')
        self.assertEqual(title_icon('reaction'), '🎖️')


    def test_fortune_set_counts_unique_six_results_and_has_requested_order(self):
        from title_core import FORTUNE_TYPES, pending_titles, title_condition
        from title_notifications import title_icon
        from fun_features import FORTUNES
        self.assertEqual(FORTUNE_TYPES, {name for name, _ in FORTUNES})
        state = {}
        for fortune in ('大吉', '大吉', '吉', '中吉', '小吉', '末吉'):
            state, unlocked = event_result(state, 'fortune', {'fortune': fortune})
            self.assertFalse(any(key == 'fortune_set' for key, _ in unlocked))
        rows = pending_titles(set(), state, 0)
        keys = [key for key, _, _ in rows]
        self.assertEqual(keys.index('fortune_set'), keys.index('fortune10') + 1)
        self.assertIn('5/6種類', {key: condition for key, _, condition in rows}['fortune_set'])
        state, unlocked = event_result(state, 'fortune', {'fortune': '凶'})
        self.assertIn(('fortune_set', '占い師'), unlocked)
        self.assertEqual(title_icon('fortune_set'), '🎖️')
        self.assertEqual(title_condition('fortune_set'), 'おみくじで全種類を取得する。')

    def test_sets_and_personal_titles(self):
        state = {}
        for kind in NORMAL_GIFTS:
            state, unlocked = event_result(state, 'gift', {'character': '美海', 'item': kind, 'preferred': True})
        self.assertIn(('variety', 'ソムリエの証'), unlocked)
        self.assertIn(('preferred_gifts10:日向美海', '日向美海の良き理解者'), unlocked)
        _, rare = event_result({}, 'gift', {'character': '美海', 'item': 'rare', 'preferred': True})
        self.assertFalse(any(key.startswith('favorite_gift:') for key, _ in rare))
        state = {}
        for world in '青黒赤白緑':
            state, unlocked = event_result(state, 'world', {'world': world})
        self.assertIn(('worlds', '青蘭学園の歩く図書館'), unlocked)
        self.assertEqual(event_result({}, 'quiz', {'attempts': 2}), ({}, []))
        self.assertEqual(event_result({}, 'reunion', {})[1], [('reunion', '青蘭学園の熟練アルドラ')])


class TitleStorageTests(unittest.TestCase):

    def test_named_search_unique_threshold_replay_and_user_isolation(self):
        from progress_profiles import profile_for
        names = ['日向美海', 'ロザリー', 'ソフィーナ', 'ユーフィリア', 'エルエル',
                 '御影葵', '東条遥', '小鳥遊希美', 'フランボワーズ', 'リゼリッタ']
        self.assertTrue(all(profile_for(name) for name in names))
        store = self.setUpTitles()
        for index, name in enumerate(names):
            store.named_profile_search(42, 2000 + index, name)
            store.named_profile_search(42, 2000 + index, name)
            if index < 9:
                self.assertNotIn('named10', self.keys())
        store.named_profile_search(42, 3000, '美海')
        store.named_profile_search(42, 3001, '該当なしの名前')
        self.assertIn('named10', self.keys())
        self.assertNotIn('named10', self.keys(43))
        data = json.loads(self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()[0])
        self.assertEqual(len(data['profile_names']), 10)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE user_id=42 AND title_key='named10'").fetchone()[0], 1)

    def test_named_search_saved_progress_backfills_once(self):
        from progress_profiles import profile_for
        names = ['日向美海', 'ロザリー', 'ソフィーナ', 'ユーフィリア', 'エルエル',
                 '御影葵', '東条遥', '小鳥遊希美', 'フランボワーズ', 'リゼリッタ']
        self.db.execute('INSERT INTO george_title_stats VALUES (43,?)', (json.dumps({'profile_names': names}),))
        self.db.commit()
        self.assertIn('named10', self.keys(43))
        self.assertIn('named10', self.keys(43))
        self.assertNotIn('profile30', self.keys(43))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE user_id=43 AND title_key='named10'").fetchone()[0], 1)


    def test_reunion_rename_keeps_key_date_and_does_not_renotify(self):
        old_name = '奇跡の再会を手繰り寄せし者'
        self.db.execute("INSERT INTO george_titles VALUES (42,'reunion',?,'2026-10-01T00:00:00+00:00')", (old_name,))
        self.db.commit()
        row = next(row for row in self.setUpTitles().titles(42) if row[0] == 'reunion')
        self.assertEqual(row[1], '青蘭学園の熟練アルドラ')
        stored = self.db.execute("SELECT name,acquired_at FROM george_titles WHERE title_key='reunion'").fetchone()
        self.assertEqual(stored, ('青蘭学園の熟練アルドラ', '2026-10-01T00:00:00+00:00'))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE title_key='reunion'").fetchone()[0], 0)

    def test_same_day_first_answer_corrects_unlock_quiz10_with_only_one_reward(self):
        with patch('presents.draw_quiz_present', return_value='food'):
            for index in range(10):
                self.store.claim_quiz(42, 900 + index, 1)
                self.store.claim_quiz(42, 900 + index, 1)
        self.assertIn('quiz10', self.keys())
        self.assertEqual(self.store.inventory(42), {'food': 1})
        row = self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()
        self.assertEqual(json.loads(row[0])['quiz_first'], 10)


    def test_pending_loads_saved_counts_and_current_favorite(self):
        self.db.execute('INSERT INTO george_title_stats VALUES (42,?)', (json.dumps({'quiz_first': 7}),))
        self.db.commit()
        rows = self.setUpTitles().pending(42, [('fortune10', '神頼み', None)])
        data = {key: condition for key, _, condition in rows}
        self.assertIn('7/10回', data['quiz10'])
        self.assertNotIn('anniversary:ロザリー', data)
        self.assertNotIn('fortune10', data)
        self.assertIn('0/10回', dict((key, condition) for key, _, condition in self.setUpTitles().pending(43, []))['quiz10'])

    # Reuse the offline transaction adapter without duplicating all present tests.
    setUp = test_presents.StorageTests.setUp
    set_favorite = test_presents.StorageTests.set_favorite
    claim = test_presents.StorageTests.claim

    def setUpTitles(self):
        return TitleStore('unused')

    def keys(self, user=42):
        return {row[0] for row in self.setUpTitles().titles(user)}

    def test_first_quiz_daily_and_fortune_replay_count_once(self):
        self.claim()
        self.claim()
        self.store.claim(42, 101, '大吉')
        self.store.claim_quiz(42, 300, 2)
        self.store.claim_quiz(42, 301, 1)
        row = self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()
        self.assertEqual(json.loads(row[0])['fortunes'], 2)
        self.assertEqual(json.loads(row[0])['quiz_first'], 1)
        self.day += timedelta(days=1)
        self.store.claim_quiz(42, 302, 1)
        self.store.claim_quiz(42, 302, 1)
        row = self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()
        self.assertEqual(json.loads(row[0])['quiz_first'], 2)

    def test_existing_hundred_points_unlocks_global_and_personal_titles(self):
        # Create affection tables, then model existing data from before title support.
        self.store.points(42, 'ロザリー')
        from progress import progressData
        for record in progressData[:100]:
            self.db.execute('INSERT INTO george_affection VALUES (42,?,100)', (record['progressName'],))
        self.db.commit()
        keys = self.keys()
        self.assertIn('bond10', keys)
        self.assertNotIn('bond100', keys)
        self.assertNotIn('affection:東条遥', keys)
        self.assertNotIn('bond10', self.keys(43))



    def test_event_failure_rolls_back_reward_and_inventory(self):
        self.fail_on = 'INSERT INTO george_title_events'
        with self.assertRaises(MemoryUnavailable):
            self.claim()
        self.fail_on = None
        self.assertEqual(self.store.inventory(42), {})
        self.assertTrue(self.claim()['granted'])

    def test_role_equipment_is_server_scoped(self):
        store = self.setUpTitles()
        store.bind_role(1, 'fortune10', 100)
        store.bind_role(2, 'fortune10', 200)
        store.save_equipped(1, 42, 'fortune10', 100)
        self.assertEqual(store.equipped(1, 42), 'fortune10')
        self.assertIsNone(store.equipped(2, 42))
        self.assertEqual(store.role_map(2), {'fortune10': 200})
        store.save_equipped(1, 42)
        self.assertIsNone(store.equipped(1, 42))


    def test_removed_titles_and_renames_preserve_remaining_ownership_and_dates(self):
        from title_core import RETIRED_TITLES, grant
        store = self.setUpTitles()
        store.titles(42)
        for key in RETIRED_TITLES | {'affection:ロザリー', 'anniversary:ロザリー'}:
            self.db.execute('INSERT INTO george_titles(user_id,title_key,name) VALUES (42,?,?)', (key, key))
        self.db.execute("INSERT INTO george_titles VALUES (42,'favorite_gift:ロザリー','ロザリーの理解者','2026-10-18T00:00:00+00:00')")
        self.db.commit()
        rows = {key: (name, day) for key, name, day in store.titles(42)}
        self.assertTrue(RETIRED_TITLES.isdisjoint(rows))
        self.assertNotIn('affection:ロザリー', rows)
        self.assertNotIn('anniversary:ロザリー', rows)
        self.assertNotIn('triple_rare', rows)
        self.assertEqual(rows['favorite_gift:ロザリー'][0], 'ロザリーの右腕')
        self.assertEqual(datetime.fromisoformat(rows['favorite_gift:ロザリー'][1]).day, 18)
        for guild in (1, 2):
            store.bind_role(guild, 'quiz100', guild * 10)
            store.save_equipped(guild, 42, 'quiz100', guild * 10)
        store.retire_title(1, 'quiz100', 10)
        self.assertEqual(store.role_map(1), {})
        self.assertEqual(store.role_map(2), {'quiz100': 20})
        self.assertIsNone(store.equipped(2, 42))
        with self.assertRaises(ValueError):
            store.retire_title(2, 'fortune10', 20)
        self.assertEqual(self.setUpTitles().titles(43), [])

    def test_retired_exchange_title_is_hidden_and_cleanup_is_server_scoped(self):
        store = self.setUpTitles()
        store.titles(42)
        self.db.execute("INSERT INTO george_titles(user_id,title_key,name) VALUES (42,'exchange10','贈り物コーディネーター')")
        self.db.execute("INSERT INTO george_titles(user_id,title_key,name) VALUES (42,'fortune10','神頼み')")
        self.db.commit()
        self.assertNotIn('exchange10', self.keys())
        self.assertIn('fortune10', self.keys())
        store.bind_role(1, 'exchange10', 10)
        store.bind_role(2, 'exchange10', 20)
        store.save_equipped(1, 42, 'exchange10', 10)
        store.save_equipped(2, 42, 'exchange10', 20)
        store.retire_exchange(1, 10)
        self.assertEqual(store.role_map(1), {})
        self.assertEqual(store.role_map(2), {'exchange10': 20})
        self.assertIsNone(store.equipped(1, 42))
        self.assertIsNone(store.equipped(2, 42))

    def test_retired_collection_title_is_hidden_and_cleanup_is_server_scoped(self):
        store = self.setUpTitles()
        store.titles(42)
        self.db.execute("INSERT INTO george_titles(user_id,title_key,name) VALUES (42,'collection:ロザリー','ロザリーとの縁を紡ぎし者')")
        self.db.commit()
        self.assertNotIn('collection:ロザリー', self.keys())
        for guild, role in ((1, 10), (2, 20)):
            store.bind_role(guild, 'collection:ロザリー', role)
            store.save_equipped(guild, 42, 'collection:ロザリー', role)
        self.assertIsNone(store.equipped(1, 42))
        store.retire_collection(1, 'collection:ロザリー', 10)
        self.assertEqual(store.role_map(1), {})
        self.assertEqual(store.role_map(2), {'collection:ロザリー': 20})
        with self.assertRaises(ValueError):
            store.retire_collection(2, 'fortune10', 20)


    def test_three_preferred_gifts_are_transactional_idempotent_and_user_scoped(self):
        self.claim()
        self.db.execute("UPDATE george_present_items SET quantity=4 WHERE user_id=42")
        self.db.commit()
        for number in range(2):
            self.store.give(42, 500 + number, 'ロザリー', 'magic')
        self.store.give(42, 501, 'ロザリー', 'magic')
        self.assertNotIn('preferred_gifts10:ロザリー', self.keys())
        self.assertNotIn('favorite_gift:ロザリー', self.keys())
        self.fail_on = 'INSERT INTO george_title_notices'
        with self.assertRaises(MemoryUnavailable):
            self.store.give(42, 502, 'ロザリー', 'magic')
        self.fail_on = None
        self.assertEqual(self.store.inventory(42), {'magic': 2})
        self.store.give(42, 502, 'ロザリー', 'magic')
        self.store.give(42, 502, 'ロザリー', 'magic')
        self.assertIn('preferred_gifts10:ロザリー', self.keys())
        self.assertNotIn('preferred_gifts10:ロザリー', self.keys(43))
        state = json.loads(self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()[0])
        self.assertEqual(state['preferred_gift_counts']['ロザリー'], 3)
        self.assertEqual(self.store.inventory(42), {'magic': 1})

    def test_saved_three_preferred_gifts_unlock_after_threshold_change(self):
        self.db.execute('INSERT INTO george_title_stats VALUES (42,?)', (json.dumps({'preferred_gift_counts': {'ロザリー': 3, '日向美海': 2}}),))
        self.db.commit()
        self.assertIn('preferred_gifts10:ロザリー', self.keys())
        self.assertNotIn('preferred_gifts10:日向美海', self.keys())
        self.assertNotIn('preferred_gifts10:ロザリー', self.keys(43))
        self.keys()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE user_id=42 AND title_key='preferred_gifts10:ロザリー'").fetchone()[0], 1)

    def test_collection_titles_use_current_ids_and_games_and_existing_holdings(self):
        from title_core import refresh_collection_titles
        targets = {'ロザリー': {('vierge', 'v1'), ('relink', 'r1')}}
        self.db.execute("INSERT INTO george_gacha_cards VALUES (42,'vierge','v1','{}')")
        self.db.execute("INSERT INTO george_gacha_cards VALUES (43,'relink','r1','{}')")
        self.db.commit()
        with patch('favorite_album.collection_targets', return_value=targets):
            rows = {key for key, _, _ in self.setUpTitles().titles(42)}
            self.assertIn('complete_vierge', rows)
            self.assertNotIn('complete_relink', rows)
            self.db.execute("INSERT INTO george_gacha_cards VALUES (42,'relink','r1','{}')")
            self.db.commit()
            rows = {key for key, _, _ in self.setUpTitles().titles(42)}
            self.assertIn('complete_relink', rows)
            self.setUpTitles().titles(42)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE user_id=42 AND title_key LIKE 'complete_%'").fetchone()[0], 2)
            self.assertNotIn('complete_vierge', {key for key, _, _ in self.setUpTitles().titles(43)})

    def test_walking_library_rename_keeps_acquisition_date_without_renotification(self):
        self.db.execute("INSERT INTO george_titles VALUES (42,'quiz_streak10','青蘭学園の歩く図書館','2026-10-19T00:00:00+00:00')")
        self.db.commit()
        rows = {key: (name, day) for key, name, day in self.setUpTitles().titles(42)}
        self.assertEqual(rows['quiz_streak10'][0], '青蘭学園の名探偵')
        self.assertEqual(str(rows['quiz_streak10'][1]), '2026-10-19T00:00:00+00:00')
        self.assertIsNone(self.db.execute("SELECT 1 FROM george_title_notices WHERE user_id=42 AND title_key='quiz_streak10'").fetchone())

    def test_restored_world_title_uses_saved_progress_and_preserves_old_ownership(self):
        from title_core import is_retired_title
        store = self.setUpTitles()
        self.assertFalse(is_retired_title('worlds'))
        self.db.execute("INSERT INTO george_titles VALUES (42,'worlds','世界の秘密を知る者','2026-10-19T00:00:00+00:00')")
        self.db.execute('INSERT INTO george_title_stats VALUES (43,?)', (json.dumps({'worlds': list('青黒赤白緑')}),))
        self.db.commit()
        old = next(row for row in store.titles(42) if row[0] == 'worlds')
        self.assertEqual(old[1], '青蘭学園の歩く図書館')
        self.assertEqual(str(old[2]), '2026-10-19T00:00:00+00:00')
        self.assertIsNone(self.db.execute("SELECT 1 FROM george_title_notices WHERE user_id=42 AND title_key='worlds'").fetchone())
        self.assertIn('worlds', {key for key, _, _ in store.titles(43)})
        for number, world in enumerate('青青黒赤白緑'):
            store.world_search(44, 1000 + number, world)
            store.world_search(44, 1000 + number, world)
        self.assertIn('worlds', {key for key, _, _ in store.titles(44)})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE user_id=44 AND title_key='worlds'").fetchone()[0], 1)

    def test_favorite_completion_requires_all_current_variants_and_registration(self):
        from title_core import pending_titles, title_condition, title_sort_key
        from title_notifications import title_icon
        targets = {'ロザリー': {('vierge', 'v1'), ('relink', 'r1'), ('relink', 'r2')}}
        self.db.execute("INSERT INTO george_gacha_cards VALUES (42,'vierge','v1','{}')")
        self.db.execute("INSERT INTO george_gacha_cards VALUES (42,'relink','r1','{}')")
        self.db.execute("INSERT INTO george_gacha_cards VALUES (43,'relink','r2','{}')")
        self.db.commit()
        with patch('favorite_album.collection_targets', return_value=targets):
            self.assertNotIn('favorite_complete', self.keys())
            self.db.execute("INSERT INTO george_gacha_cards VALUES (42,'relink','r2','{}')")
            self.db.execute('DELETE FROM george_gacha_favorites')
            self.db.commit()
            self.assertNotIn('favorite_complete', self.keys())
            self.db.execute("INSERT INTO george_gacha_favorites VALUES (42,'relink','id')")
            self.db.commit()
            self.assertIn('favorite_complete', self.keys())
            self.keys()
            self.assertNotIn('favorite_complete', self.keys(43))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE user_id=42 AND title_key='favorite_complete'").fetchone()[0], 1)
        self.assertEqual(title_icon('favorite_complete'), '🎖️')
        self.assertEqual(title_condition('favorite_complete'), 'お気に入り本人のレアリティ・衣装を全て獲得する。')
        keys = [key for key, _, _ in pending_titles(set(), {}, 0)]
        self.assertEqual(keys.index('favorite_complete'), keys.index('reunion') + 1)
        rows = sorted([('favorite_complete', '青蘭学園の一流アルドラ', None), ('reunion', '青蘭学園の熟練アルドラ', None)], key=title_sort_key)
        self.assertEqual(rows[0][0], 'reunion')

    def test_fortune_set_can_use_saved_distinct_fortune_history(self):
        self.db.execute('INSERT INTO george_title_stats VALUES (42,?)', (json.dumps({'fortunes_seen': ['大吉', '吉', '中吉', '小吉', '末吉', '凶']}),))
        self.db.commit()
        self.assertIn('fortune_set', self.keys())
        self.assertNotIn('fortune_set', self.keys(43))
        self.keys()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE user_id=42 AND title_key='fortune_set'").fetchone()[0], 1)

    def test_registration_title_backfills_only_real_registration(self):
        from favorite_album import record_registration
        self.assertNotIn('favorite_registered', self.keys())
        with self.store.connect() as conn:
            record_registration(conn, 42, 'ロザリー')
        self.assertIn('favorite_registered', self.keys())
        self.assertNotIn('favorite_registered', self.keys(43))


    def test_existing_full_affection_can_earn_preferred_gift_title_without_fake_date(self):
        self.claim()
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',100)")
        self.db.commit()
        self.assertNotIn('affection:ロザリー', self.keys())
        self.assertEqual(self.store.give(42, 200, 'ロザリー', 'magic'), (0, 100, True))
        self.assertIn('favorite_gift:ロザリー', self.keys())
        self.assertNotIn('affection:ロザリー', self.keys())
        self.assertEqual(self.store.inventory(42), {})
        self.assertIsNone(self.store.album(42, 'ロザリー')[2])

    def test_perfect_link_title_is_retired_but_progress_and_album_are_retained(self):
        self.store.points(42, 'ロザリー')
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',100)")
        self.db.execute("INSERT INTO george_perfect_links(user_id,character) VALUES (42,'ロザリー')")
        self.db.execute("INSERT INTO george_titles(user_id,title_key,name) VALUES (42,'affection:東条遥','東条遥の右腕')")
        self.db.commit()
        keys = self.keys()
        self.assertNotIn('affection:ロザリー', keys)
        self.assertNotIn('affection:東条遥', keys)
        self.assertNotIn('affection:ロザリー', self.keys(43))
        self.assertIsNotNone(self.store.album(42, 'ロザリー')[3])
        self.assertIn('favorite_gift:ロザリー', self.keys())


class FakeRole:
    def __init__(self, number, position=1, permissions=0):
        self.id, self.position = number, position
        self.managed = self.hoist = self.mentionable = False
        self.permissions = discord.Permissions(permissions)
        self.colour = discord.Colour.default()
        self.name = '旧称号'

        async def edit(**kwargs):
            self.name = kwargs['name']
            return self

        self.edit = AsyncMock(side_effect=edit)

    def __ge__(self, other):
        return self.position >= other.position

    def is_default(self):
        return False


class TitleRoleTests(unittest.IsolatedAsyncioTestCase):
    def objects(self):
        old, target, unrelated = FakeRole(10), FakeRole(11), FakeRole(99)
        store = SimpleNamespace(titles=Mock(return_value=[('fortune10', '神頼み', None)]),
            role_map=Mock(return_value={'old': 10, 'fortune10': 11}), save_equipped=Mock(), bind_role=Mock(return_value=11))
        member = SimpleNamespace(roles=[old, unrelated], remove_roles=AsyncMock(), add_roles=AsyncMock())
        guild = SimpleNamespace(id=1, me=SimpleNamespace(guild_permissions=discord.Permissions(manage_roles=True), top_role=FakeRole(100, 10)),
            fetch_roles=AsyncMock(return_value=[old, target, unrelated]), fetch_member=AsyncMock(return_value=member))
        return store, member, guild, target

    async def test_equip_remove_only_title_roles_and_reject_unearned(self):
        store, member, guild, target = self.objects()
        manager = TitleRoles(store)
        self.assertEqual(await manager.equip(guild, 42, 'fortune10'), '神頼み')
        self.assertEqual(member.remove_roles.call_args.args[0].id, 10)
        member.add_roles.assert_awaited_once_with(target, reason='ジョージの称号を装着', atomic=True)
        store.save_equipped.assert_called_with(1, 42, 'fortune10', 11)
        self.assertEqual(target.name, '🎖️ 神頼み')
        await manager.equip(guild, 42, 'fortune10')
        target.edit.assert_awaited_once()
        with self.assertRaises(ValueError):
            await manager.equip(guild, 42, 'unearned')

    async def test_hard_title_updates_existing_bound_role_with_crown(self):
        store, member, guild, target = self.objects()
        store.titles.return_value = [('all_green', '青蘭学園の叛逆者', None)]
        store.role_map.return_value = {'all_green': target.id}
        await TitleRoles(store).equip(guild, 42, 'all_green')
        self.assertEqual(target.name, '👑 青蘭学園の叛逆者')

    async def test_modified_role_is_rejected_and_owner_can_remove_safe_old_title(self):
        store, member, guild, target = self.objects()
        manager = TitleRoles(store)
        target.permissions = discord.Permissions(administrator=True)
        with self.assertRaises(ValueError):
            await manager.equip(guild, 42, 'fortune10')
        member.add_roles.assert_not_awaited()
        await manager.equip(guild, 42, None)
        store.save_equipped.assert_called_with(1, 42, None, None)

    async def test_database_failure_rolls_back_role_changes(self):
        store, member, guild, target = self.objects()
        store.save_equipped.side_effect = MemoryUnavailable('offline')
        with self.assertRaises(MemoryUnavailable):
            await TitleRoles(store).equip(guild, 42, 'fortune10')
        self.assertIn(target, [call.args[0] for call in member.remove_roles.call_args_list])
        self.assertIn(10, [call.args[0].id for call in member.add_roles.call_args_list])

    async def test_new_roles_have_no_permissions_color_or_hoist(self):
        store, member, guild, target = self.objects()
        store.role_map.return_value = {'old': 10}
        guild.create_role = AsyncMock(return_value=target)
        await TitleRoles(store).equip(guild, 42, 'fortune10')
        params = guild.create_role.call_args.kwargs
        self.assertEqual(params['permissions'].value, 0)
        self.assertEqual(params['colour'].value, 0)
        self.assertFalse(params['hoist'] or params['mentionable'])

    async def test_private_view_dm_and_owner_only(self):
        view = TitleView(42, [('fortune10', '神頼み', None)], None)
        self.assertNotIn('獲得した称号は全サーバー共通', view.embed().description)
        self.assertFalse(view.embed().description.startswith('\n'))
        self.assertTrue(view.children[1].disabled)
        self.assertTrue(view.children[2].disabled)
        interaction = SimpleNamespace(user=SimpleNamespace(id=43), response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await view.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        view.stop()

    async def test_switch_pending_and_back_preserves_equipped_and_resets_page(self):
        roles = SimpleNamespace(equip=AsyncMock())
        earned = [('fortune10', '神頼み', datetime(2026, 10, 19, 16, tzinfo=timezone.utc))]
        view = TitleView(42, earned, roles, SimpleNamespace(id=1), 'fortune10',
                         [('quiz10', '青蘭学園の知恵袋', '初回正解7/10回')])
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), edit_original_response=AsyncMock())
        self.assertIn('2026年10月20日', view.embed().description)
        self.assertIn('🎖️ **神頼み**\nおみくじに累計10回挑戦する。\n獲得日：2026年10月20日', view.embed().description)
        view.selected = 'fortune10'
        await next(child for child in view.children if getattr(child, 'label', '') == '未獲得').callback(interaction)
        self.assertEqual(view.mode, 'pending')
        self.assertIsNone(view.selected)
        self.assertIn('初回正解7/10回', view.embed().description)
        self.assertNotIn('プログレス別の未獲得称号は', view.embed().description)
        self.assertFalse(any(isinstance(child, discord.ui.Select) for child in view.children))
        await view.apply(interaction, 'quiz10')
        roles.equip.assert_not_awaited()
        await next(child for child in view.children if getattr(child, 'label', '') == '獲得済み').callback(interaction)
        self.assertEqual(view.mode, 'earned')
        self.assertEqual(view.page, 0)
        self.assertEqual(view.equipped, 'fortune10')
        self.assertTrue(any(isinstance(child, discord.ui.Select) for child in view.children))
        await view.on_timeout()
        self.assertTrue(all(child.disabled for child in view.children))
        view.stop()

    async def test_title_icons_match_in_earned_pending_equipped_and_selector(self):
        rows = [('fortune10', '神頼み', None), ('quiz_streak10', '青蘭学園の名探偵', None),
                ('bond10', 'エール・フレンドを繋ぎし者', None), ('all_green', '青蘭学園の叛逆者', None)]
        view = TitleView(42, rows, None, SimpleNamespace(id=1), 'quiz_streak10',
                         [(key, name, '条件') for key, name, _ in rows])
        self.assertIn('【装着中】\n🎖️ 青蘭学園の名探偵', view.embed().description)
        options = next(child for child in view.children if isinstance(child, discord.ui.Select)).options
        self.assertEqual([str(option.emoji) for option in options], ['🎖️', '🎖️', '👑', '👑'])
        for mode in ('earned', 'pending'):
            view.mode = mode
            view.build()
            text = view.embed().description
            if mode == 'pending':
                self.assertNotIn('【装着中】', text)
                self.assertNotIn('【未獲得】', text)
            self.assertIn('🎖️ **神頼み**', text)
            self.assertIn('🎖️ **青蘭学園の名探偵**', text)
            for name in ('エール・フレンドを繋ぎし者', '青蘭学園の叛逆者'):
                self.assertIn(f'👑 **{name}**', text)
        view.stop()

    async def test_missing_permission_and_role_hierarchy_block_changes(self):
        store, member, guild, target = self.objects()
        target.position = 11
        with self.assertRaises(ValueError):
            await TitleRoles(store).equip(guild, 42, 'fortune10')
        member.add_roles.assert_not_awaited()
        member.remove_roles.assert_not_awaited()
        guild.me.guild_permissions = discord.Permissions.none()
        with self.assertRaises(ValueError):
            await TitleRoles(store).equip(guild, 42, 'fortune10')

    async def test_fresh_role_positions_override_stale_gateway_cache(self):
        store, member, guild, target = self.objects()
        guild.me.top_role = FakeRole(100, 1)
        guild.me.roles = [guild.me.top_role]
        guild.fetch_roles.return_value.append(FakeRole(100, 2))
        await TitleRoles(store).equip(guild, 42, 'fortune10')
        member.add_roles.assert_awaited_once()

    async def test_retired_cleanup_deletes_only_registered_exchange_role(self):
        store, member, guild, target = self.objects()
        old = guild.fetch_roles.return_value[0]
        old.delete, target.delete = AsyncMock(), AsyncMock()
        store.role_map.return_value = {'exchange10': old.id, 'fortune10': target.id}
        store.retire_exchange = Mock()
        await TitleRoles(store).retire_exchange(guild)
        old.delete.assert_awaited_once()
        target.delete.assert_not_awaited()
        store.retire_exchange.assert_called_once_with(guild.id, old.id)

    async def test_retired_collection_cleanup_only_deletes_tracked_safe_role(self):
        store, member, guild, target = self.objects()
        old = guild.fetch_roles.return_value[0]
        old.delete, target.delete = AsyncMock(), AsyncMock()
        store.role_map.return_value = {'collection:ロザリー': old.id, 'fortune10': target.id}
        store.retire_collection = Mock()
        await TitleRoles(store).retire_collections(guild)
        old.delete.assert_awaited_once()
        target.delete.assert_not_awaited()
        store.retire_collection.assert_called_once_with(guild.id, 'collection:ロザリー', old.id)

    async def test_retired_collection_cleanup_preserves_modified_role(self):
        store, member, guild, target = self.objects()
        target.delete = AsyncMock()
        target.permissions = discord.Permissions(administrator=True)
        store.role_map.return_value = {'collection:ロザリー': target.id}
        store.retire_collection = Mock()
        with self.assertRaises(ValueError):
            await TitleRoles(store).retire_collections(guild)
        target.delete.assert_not_awaited()
        store.retire_collection.assert_not_called()

    async def test_deleted_title_cleanup_deletes_only_safe_registered_roles(self):
        store, member, guild, target = self.objects()
        old = guild.fetch_roles.return_value[0]
        old.delete, target.delete = AsyncMock(), AsyncMock()
        store.role_map.return_value = {'anniversary:ロザリー': old.id, 'fortune10': target.id}
        store.retire_title = Mock()
        await TitleRoles(store).retire_removed(guild)
        old.delete.assert_awaited_once()
        target.delete.assert_not_awaited()
        store.retire_title.assert_called_once_with(guild.id, 'anniversary:ロザリー', old.id)
        old.delete.reset_mock()
        store.retire_title.reset_mock()
        old.permissions = discord.Permissions(administrator=True)
        await TitleRoles(store).retire_removed(guild)
        old.delete.assert_not_awaited()
        store.retire_title.assert_not_called()

    async def test_retired_cleanup_without_permission_preserves_role_and_mapping(self):
        store, member, guild, target = self.objects()
        target.delete = AsyncMock()
        store.role_map.return_value = {'exchange10': target.id}
        store.retire_exchange = Mock()
        guild.me.guild_permissions = discord.Permissions.none()
        with self.assertRaises(ValueError):
            await TitleRoles(store).retire_exchange(guild)
        target.delete.assert_not_awaited()
        store.retire_exchange.assert_not_called()
