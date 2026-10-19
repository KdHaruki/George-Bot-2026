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
        self.assertIn(('variety', '贈り物のソムリエ'), unlocked)
        self.assertIn(('favorite_gift:日向美海', '日向美海の理解者'), unlocked)
        _, rare = event_result({}, 'gift', {'character': '美海', 'item': 'rare', 'preferred': True})
        self.assertFalse(any(key.startswith('favorite_gift:') for key, _ in rare))
        state = {}
        for world in '青黒赤白緑':
            state, unlocked = event_result(state, 'world', {'world': world})
        self.assertIn(('worlds', '世界の秘密を知る者'), unlocked)
        self.assertEqual(event_result({}, 'quiz', {'attempts': 2}), ({}, []))
        self.assertEqual(event_result({}, 'reunion', {})[1], [('reunion', '奇跡の再会を手繰り寄せし者')])


class TitleStorageTests(unittest.TestCase):
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
        self.assertEqual(json.loads(row[0])['fortunes'], 1)
        self.assertNotIn('quiz_first', json.loads(row[0]))
        self.day += timedelta(days=1)
        self.store.claim_quiz(42, 302, 1)
        self.store.claim_quiz(42, 302, 1)
        row = self.db.execute('SELECT data FROM george_title_stats WHERE user_id=42').fetchone()
        self.assertEqual(json.loads(row[0])['quiz_first'], 1)

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
        with self.assertRaises(ValueError):
            await manager.equip(guild, 42, 'unearned')

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
        self.assertTrue(view.children[1].disabled)
        self.assertTrue(view.children[2].disabled)
        interaction = SimpleNamespace(user=SimpleNamespace(id=43), response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await view.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
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
