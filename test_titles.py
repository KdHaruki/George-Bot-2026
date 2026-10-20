import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import test_presents
from title_core import COMMON, NORMAL_GIFTS, event_result, record_event, change_streak, seed_existing_streaks
from title_store import TitleStore
from title_roles import TitleRoles
from title_commands import TitleView
from registered_memory import MemoryUnavailable


class TitleRulesTests(unittest.TestCase):
    def test_ambassador_counts_unique_worlds_and_information_title_counts_unique_people(self):
        from progress import progressData
        state = {}
        for world in '青青黒赤白':
            state, unlocked = event_result(state, 'favorite_world', {'world': world})
            self.assertNotIn(('ambassador', '青蘭学園の親善大使'), unlocked)
        state, unlocked = event_result(state, 'favorite_world', {'world': '緑'})
        self.assertIn(('ambassador', '青蘭学園の親善大使'), unlocked)
        state, _ = event_result({}, 'profile_search', {'character': '美海'})
        state, _ = event_result(state, 'profile_search', {'character': '日向美海'})
        self.assertEqual(state['profile_names'], ['日向美海'])
        state = {}
        for index, record in enumerate(progressData[:10]):
            state, unlocked = event_result(state, 'profile_search', {'character': record['progressName']})
            self.assertEqual(('profile30', '青蘭学園の情報通') in unlocked, index == 9)

    def test_royal_flush_requires_all_four_rarities_in_one_vierge_batch(self):
        from title_core import title_condition, pending_titles
        from title_notifications import title_icon
        facts = dict(game='vierge', count=7, rarities=['UR', 'SR', 'HR', 'R'])
        self.assertIn(('royal_flush', '青蘭学園のロイヤルフラッシュ'), event_result({}, 'royal_flush', facts)[1])
        for change in (dict(game='relink'), dict(count=6), dict(count=14), dict(rarities=['UR', 'SR', 'R'])):
            self.assertEqual(event_result({}, 'royal_flush', facts | change)[1], [])
        self.assertEqual(title_icon('royal_flush'), '🎖️')
        self.assertIn('7連', title_condition('royal_flush'))
        self.assertIn('royal_flush', {key for key, _, _ in pending_titles(set(), {}, 0)})

    def test_triple_rare_threshold_icon_and_condition(self):
        from title_core import title_condition
        from title_notifications import title_icon
        for count in (0, 1, 2):
            self.assertEqual(event_result({}, 'triple_rare', {'count': count})[1], [])
        for count in (3, 4, 7, 10):
            self.assertEqual(event_result({}, 'triple_rare', {'count': count})[1], [('triple_rare', '奇跡を束ねし者')])
        self.assertEqual(title_icon('triple_rare'), '👑')
        self.assertNotIn('同じカード', title_condition('triple_rare'))

    def test_all_six_fortunes_title_counts_distinct_results_and_uses_current_names(self):
        from title_core import FORTUNE_TYPES, pending_titles, title_condition
        from fun_features import FORTUNES
        from title_notifications import title_icon
        self.assertEqual(FORTUNE_TYPES, {name for name, _ in FORTUNES})
        state = {}
        for fortune in ('大吉', '大吉', '吉', '中吉', '小吉', '末吉'):
            state, unlocked = event_result(state, 'fortune', {'fortune': fortune})
            self.assertNotIn(('fortune_all', '運命を巡りし者'), unlocked)
        pending = {key: condition for key, _, condition in pending_titles(set(), state, 0, 'ロザリー')}
        self.assertIn('5/6種類', pending['fortune_all'])
        self.assertFalse(any('好物' in condition for condition in pending.values()))
        self.assertNotIn('好物', title_condition('affection:ロザリー'))
        state, unlocked = event_result(state, 'fortune', {'fortune': '凶'})
        self.assertIn(('fortune_all', '運命を巡りし者'), unlocked)
        self.assertEqual(title_icon('fortune_all'), '🎖️')

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
        self.assertEqual(title_condition('fortune10'), 'おみくじを累計10回')
        self.assertIn('全14種類', title_condition('variety'))
        self.assertEqual(title_condition('affection:ロザリー'), 'ロザリーの好感度100の状態で喜ばれる贈り物を贈る')
        self.assertIn('プログレスの変更または解除でリセット', title_condition('anniversary:ロザリー'))
        self.assertIn('喜ばれる贈り物', title_condition('favorite_gift:ロザリー'))

    def test_pending_conditions_counters_and_favorite_scope(self):
        from title_core import pending_titles
        rows = pending_titles({'fortune10', 'favorite_gift:ロザリー'},
                              {'quiz_first': 7, 'fortunes': 10, 'gift_kinds': ['book', 'rare'], 'worlds': ['赤', '青']},
                              3, 'ロザリー', 12)
        data = {key: condition for key, _, condition in rows}
        self.assertNotIn('fortune10', data)
        self.assertNotIn('favorite_gift:ロザリー', data)
        self.assertIn('7/10回', data['quiz10'])
        self.assertIn('1/14種類', data['variety'])
        self.assertIn('2/5世界', data['worlds'])
        self.assertIn('3/5人', data['bond10'])
        self.assertIn('クイズをヒント1回目で正解', data['quiz10'])
        self.assertNotIn('不正解・時間切れ', data['quiz_streak10'])
        self.assertIn('お気に入りに登録する：', data['ambassador'])
        self.assertIn('プログレスを10人名前で検索する：', data['profile30'])
        keys = list(data)
        self.assertEqual(keys.index('quiz_streak10'), keys.index('quiz100') + 1)
        self.assertIn('12/365日', data['anniversary:ロザリー'])
        self.assertEqual(data['anniversary:ロザリー'], 'お気に入りに設定して1年が経つ：12/365日（プログレスの変更または解除でリセット）')
        keys = [key for key, _, _ in rows]
        start = keys.index('gift10')
        self.assertEqual(keys[start:start + 4], ['gift10', 'variety', 'worlds', 'reunion'])
        self.assertEqual(data['affection:ロザリー'], '好感度100の状態で喜ばれる贈り物を贈る')
        self.assertNotIn('exchange10', data)
        self.assertFalse(any(':' in key for key, _, _ in pending_titles(set(), {}, 0)))

    def test_all_counter_thresholds_and_exact_names(self):
        for kind, facts, thresholds in [
            ('quiz', {'attempts': 1}, {10: 'quiz10', 100: 'quiz100'}),
            ('fortune', {'fortune': '大吉'}, {10: 'great10'}),
            ('gift', {'character': '美海', 'item': 'rare'}, {10: 'gift10'}),
        ]:
            state = {}
            for number in range(1, max(thresholds) + 1):
                state, unlocked = event_result(state, kind, facts)
                keys = {key for key, _ in unlocked}
                for threshold, key in thresholds.items():
                    self.assertEqual(key in keys, number >= threshold)
        _, unlocked = event_result({}, 'fortune', {'fortune': '凶', 'bonus': True})
        self.assertIn(('support', 'エール・フレンドを受けし者'), unlocked)

    def test_sets_and_personal_titles(self):
        state = {}
        for kind in NORMAL_GIFTS:
            state, unlocked = event_result(state, 'gift', {'character': '美海', 'item': kind, 'preferred': True})
        self.assertIn(('variety', '青蘭学園のソムリエ'), unlocked)
        self.assertIn(('favorite_gift:日向美海', '日向美海の理解者'), unlocked)
        _, rare = event_result({}, 'gift', {'character': '美海', 'item': 'rare', 'preferred': True})
        self.assertFalse(any(key.startswith('favorite_gift:') for key, _ in rare))
        state = {}
        for world in '青黒赤白緑':
            state, unlocked = event_result(state, 'world', {'world': world})
        self.assertIn(('worlds', '世界の秘密を知る者'), unlocked)
        self.assertEqual(event_result({}, 'quiz', {'attempts': 2}), ({}, []))
        self.assertEqual(event_result({}, 'reunion', {})[1], [('reunion', '青蘭学園の時間超越者')])


class TitleStorageTests(unittest.TestCase):
    def test_past_registration_album_can_unlock_ambassador_without_re_registering(self):
        from favorite_album import record_registration
        from progress import progressData
        with self.store.connect() as conn:
            for world in '青黒赤白緑':
                person = next(record for record in progressData if record['progressWorld'] == world)
                record_registration(conn, 42, person['progressName'])
        self.assertIn('ambassador', self.keys())
        self.assertNotIn('ambassador', self.keys(43))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE title_key='ambassador'").fetchone()[0], 1)
        self.keys()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE title_key='ambassador'").fetchone()[0], 1)

    def test_named_profile_search_counts_canonical_names_and_replay_once(self):
        store = self.setUpTitles()
        store.profile_search(42, 501, '美海')
        store.profile_search(42, 502, '日向美海')
        store.profile_search(42, 502, 'ロザリー')
        store.profile_search(42, 503, '存在しない名前')
        store.world_search(42, 504, '赤')
        row = self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()
        self.assertEqual(json.loads(row[0])['profile_names'], ['日向美海'])

    def test_reunion_rename_keeps_key_date_and_does_not_renotify(self):
        old_name = '奇跡の再会を手繰り寄せし者'
        self.db.execute("INSERT INTO george_titles VALUES (42,'reunion',?,'2026-10-01T00:00:00+00:00')", (old_name,))
        self.db.commit()
        row = next(row for row in self.setUpTitles().titles(42) if row[0] == 'reunion')
        self.assertEqual(row[1], '青蘭学園の時間超越者')
        stored = self.db.execute("SELECT name,acquired_at FROM george_titles WHERE title_key='reunion'").fetchone()
        self.assertEqual(stored, ('青蘭学園の時間超越者', '2026-10-01T00:00:00+00:00'))
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

    def test_all_fortunes_title_counts_same_day_and_is_user_scoped_once(self):
        for index, fortune in enumerate(('大吉', '吉', '中吉', '小吉', '末吉', '凶')):
            with patch('presents.draw_present', return_value='food'):
                self.store.claim(42, 700 + index, fortune)
                self.store.claim(42, 700 + index, '凶')
            self.assertEqual('fortune_all' in self.keys(), index == 5)
        self.assertNotIn('fortune_all', self.keys(43))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM george_title_notices WHERE title_key='fortune_all'").fetchone()[0], 1)
        self.assertEqual(sum(self.store.inventory(42).values()), 1)

    def test_pending_loads_saved_counts_and_current_favorite(self):
        self.db.execute('INSERT INTO george_title_stats VALUES (42,?)', (json.dumps({'quiz_first': 7}),))
        self.db.commit()
        rows = self.setUpTitles().pending(42, [('fortune10', '今日も神頼み', None)])
        data = {key: condition for key, _, condition in rows}
        self.assertIn('7/10回', data['quiz10'])
        self.assertIn('anniversary:ロザリー', data)
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
        self.assertIn('bond100', keys)
        self.assertNotIn('affection:東条遥', keys)
        self.assertNotIn('bond10', self.keys(43))

    def test_continuous_streak_preserves_costumes_resets_characters_and_retains_awards(self):
        with self.store.connect() as conn:
            change_streak(conn, 42, '美海')
        since = (datetime.now(timezone.utc) - timedelta(days=364)).strftime('%Y-%m-%d %H:%M:%S')
        self.db.execute('UPDATE george_title_streaks SET since=? WHERE user_id=42', (since,))
        self.db.commit()
        with self.store.connect() as conn:
            change_streak(conn, 42, '日向美海')
        self.assertEqual(self.db.execute('SELECT since FROM george_title_streaks').fetchone()[0], since)
        with self.store.connect() as conn:
            change_streak(conn, 42, 'ロザリー')
        self.assertNotEqual(self.db.execute('SELECT since FROM george_title_streaks').fetchone()[0], since)
        old = (datetime.now(timezone.utc) - timedelta(days=366)).strftime('%Y-%m-%d %H:%M:%S')
        self.db.execute('UPDATE george_title_streaks SET since=? WHERE user_id=42', (old,))
        self.db.commit()
        with self.store.connect() as conn:
            change_streak(conn, 42, None)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_title_streaks').fetchone()[0], 0)
        self.assertIn('anniversary:ロザリー', self.keys())

    def test_world_searches_and_replay_are_user_scoped(self):
        store = self.setUpTitles()
        for number, world in enumerate('青黒赤白緑'):
            store.world_search(42, number + 1000, world)
            store.world_search(42, number + 1000, world)
        self.assertIn('worlds', self.keys())
        self.assertNotIn('worlds', self.keys(43))

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

    def test_existing_streaks_begin_at_migration_and_are_not_reseeded(self):
        self.db.execute('CREATE TABLE george_gacha_migrations(name TEXT PRIMARY KEY)')
        with self.store.connect() as conn:
            seed_existing_streaks(conn)
        row = self.db.execute('SELECT character,since FROM george_title_streaks').fetchone()
        self.assertEqual(row[0], 'ロザリー')
        self.assertIsNotNone(row[1])
        with self.store.connect() as conn:
            change_streak(conn, 42, None)
            seed_existing_streaks(conn)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_title_streaks').fetchone()[0], 0)

    def test_retired_exchange_title_is_hidden_and_cleanup_is_server_scoped(self):
        store = self.setUpTitles()
        store.titles(42)
        self.db.execute("INSERT INTO george_titles(user_id,title_key,name) VALUES (42,'exchange10','贈り物コーディネーター')")
        self.db.execute("INSERT INTO george_titles(user_id,title_key,name) VALUES (42,'fortune10','今日も神頼み')")
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
        self.assertEqual(store.equipped(2, 42), 'exchange10')

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

    def test_real_registration_keeps_same_person_streak_and_resets_on_clear(self):
        from dataclasses import asdict
        from gacha import Gacha
        from gacha_collection import CollectionStore
        engine = Gacha()
        cards = [c for c in engine.pools['relink']['★3'] if c.character == '美海']
        self.db.execute('DELETE FROM george_gacha_favorites')
        self.db.execute('DELETE FROM george_gacha_cards')
        self.db.execute('CREATE UNIQUE INDEX favorite_user ON george_gacha_favorites(user_id)')
        self.db.execute('ALTER TABLE george_gacha_cards ADD COLUMN quantity BIGINT')
        for card in cards:
            self.db.execute('INSERT INTO george_gacha_cards VALUES (42,?,?,?,1)', ('relink', card.id, json.dumps(asdict(card))))
        self.db.commit()
        store = CollectionStore('unused')
        store.set_favorite(42, 'relink', cards[0].id, toggle=True)
        old = (datetime.now(timezone.utc) - timedelta(days=364)).strftime('%Y-%m-%d %H:%M:%S')
        self.db.execute('UPDATE george_title_streaks SET since=?', (old,))
        self.db.commit()
        store.set_favorite(42, 'relink', cards[1].id, toggle=True)
        self.assertEqual(self.db.execute('SELECT character,since FROM george_title_streaks').fetchone(), ('日向美海', old))
        store.set_favorite(42, 'relink', cards[1].id, toggle=True)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_title_streaks').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM george_gacha_cards').fetchone()[0], len(cards))

    def test_existing_full_affection_can_earn_preferred_gift_title_without_fake_date(self):
        self.claim()
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',100)")
        self.db.commit()
        self.assertNotIn('affection:ロザリー', self.keys())
        self.assertEqual(self.store.give(42, 200, 'ロザリー', 'magic'), (0, 100, True))
        self.assertIn('favorite_gift:ロザリー', self.keys())
        self.assertIn('affection:ロザリー', self.keys())
        self.assertEqual(self.store.inventory(42), {})
        self.assertIsNone(self.store.album(42, 'ロザリー')[2])

    def test_perfect_link_unlocks_good_understanding_and_existing_titles_are_kept(self):
        self.store.points(42, 'ロザリー')
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',100)")
        self.db.execute("INSERT INTO george_perfect_links(user_id,character) VALUES (42,'ロザリー')")
        self.db.execute("INSERT INTO george_titles(user_id,title_key,name) VALUES (42,'affection:東条遥','東条遥の良き理解者')")
        self.db.commit()
        keys = self.keys()
        self.assertIn('affection:ロザリー', keys)
        self.assertIn('affection:東条遥', keys)
        self.assertNotIn('affection:ロザリー', self.keys(43))


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
        store = SimpleNamespace(titles=Mock(return_value=[('fortune10', '今日も神頼み', None)]),
            role_map=Mock(return_value={'old': 10, 'fortune10': 11}), save_equipped=Mock(), bind_role=Mock(return_value=11))
        member = SimpleNamespace(roles=[old, unrelated], remove_roles=AsyncMock(), add_roles=AsyncMock())
        guild = SimpleNamespace(id=1, me=SimpleNamespace(guild_permissions=discord.Permissions(manage_roles=True), top_role=FakeRole(100, 10)),
            fetch_roles=AsyncMock(return_value=[old, target, unrelated]), fetch_member=AsyncMock(return_value=member))
        return store, member, guild, target

    async def test_equip_remove_only_title_roles_and_reject_unearned(self):
        store, member, guild, target = self.objects()
        manager = TitleRoles(store)
        self.assertEqual(await manager.equip(guild, 42, 'fortune10'), '今日も神頼み')
        self.assertEqual(member.remove_roles.call_args.args[0].id, 10)
        member.add_roles.assert_awaited_once_with(target, reason='ジョージの称号を装着', atomic=True)
        store.save_equipped.assert_called_with(1, 42, 'fortune10', 11)
        self.assertEqual(target.name, '🎖️ 今日も神頼み')
        await manager.equip(guild, 42, 'fortune10')
        target.edit.assert_awaited_once()
        with self.assertRaises(ValueError):
            await manager.equip(guild, 42, 'unearned')

    async def test_hard_title_updates_existing_bound_role_with_crown(self):
        store, member, guild, target = self.objects()
        store.titles.return_value = [('anniversary:ロザリー', 'ロザリーの右腕', None)]
        store.role_map.return_value = {'anniversary:ロザリー': target.id}
        await TitleRoles(store).equip(guild, 42, 'anniversary:ロザリー')
        self.assertEqual(target.name, '👑 ロザリーの右腕')

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
        view = TitleView(42, [('fortune10', '今日も神頼み', None)], None)
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
        earned = [('fortune10', '今日も神頼み', datetime(2026, 10, 19, 16, tzinfo=timezone.utc))]
        view = TitleView(42, earned, roles, SimpleNamespace(id=1), 'fortune10',
                         [('quiz10', '青蘭学園の知恵袋', '初回正解7/10回')])
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), edit_original_response=AsyncMock())
        self.assertIn('2026年10月20日', view.embed().description)
        self.assertIn('🎖️ **今日も神頼み**\nおみくじを累計10回\n獲得日：2026年10月20日', view.embed().description)
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
        rows = [('fortune10', '今日も神頼み', None), ('quiz100', '青蘭学園の秘密兵器', None),
                ('bond100', 'エルエルを超えし者', None), ('anniversary:ロザリー', 'ロザリーの右腕', None)]
        view = TitleView(42, rows, None, SimpleNamespace(id=1), 'quiz100',
                         [(key, name, '条件') for key, name, _ in rows])
        self.assertIn('【装着中】\n🎖️ 青蘭学園の秘密兵器', view.embed().description)
        options = next(child for child in view.children if isinstance(child, discord.ui.Select)).options
        self.assertEqual([str(option.emoji) for option in options], ['🎖️', '🎖️', '👑', '👑'])
        for mode in ('earned', 'pending'):
            view.mode = mode
            view.build()
            text = view.embed().description
            if mode == 'pending':
                self.assertNotIn('【装着中】', text)
                self.assertNotIn('【未獲得】', text)
            self.assertIn('🎖️ **今日も神頼み**', text)
            self.assertIn('🎖️ **青蘭学園の秘密兵器**', text)
            for name in ('エルエルを超えし者', 'ロザリーの右腕'):
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
