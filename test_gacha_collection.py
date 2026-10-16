import unittest
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

from gacha import Card, Gacha, vierge_character_card
from gacha_collection import CollectionStore, collection_summary, unowned_cards
from gacha_commands import favorite_details, gacha_comment, register_gacha_commands, result_embed
from registered_memory import MemoryUnavailable


class StoreTests(unittest.TestCase):
    def test_vierge_migration_merges_variants_and_moves_favorite_once(self):
        canonical = vierge_character_card('ロザリー', 'UR')
        inventory = {'old-a': (asdict(Card('old-a', 'ロザリー', 'ロザリー【水着】', 'UR', 15, '技')), 2),
                     'old-b': (asdict(Card('old-b', 'ロザリー', 'ロザリー【制服】', 'UR', 14, '別技')), 3),
                     canonical.id: (asdict(canonical), 1)}
        favorite = ['old-b']
        migrated = [False]
        connection = Mock()
        def execute(sql, params=None):
            if sql.startswith('SELECT 1 FROM george_gacha_migrations'):
                return SimpleNamespace(fetchone=lambda: (1,) if migrated[0] else None)
            if sql.startswith('SELECT user_id,card_id'):
                return SimpleNamespace(fetchall=lambda: [(10, key, payload, count) for key, (payload, count) in list(inventory.items())])
            if sql.startswith('INSERT INTO george_gacha_cards'):
                import json
                uid, key, payload, count = params
                self.assertEqual(uid, 10)
                inventory[key] = (json.loads(payload), count + inventory.get(key, (None, 0))[1])
            if sql.startswith('UPDATE george_gacha_favorites'):
                new_id, uid, old_id = params
                if favorite[0] == old_id:
                    favorite[0] = new_id
            if sql.startswith('DELETE FROM george_gacha_cards'):
                self.assertEqual(favorite[0] == params[1], False)
                del inventory[params[1]]
            if sql.startswith('INSERT INTO george_gacha_migrations'):
                migrated[0] = True
            return Mock()
        connection.execute.side_effect = execute
        CollectionStore.migrate_vierge(connection)
        self.assertEqual(inventory, {canonical.id: (asdict(canonical), 6)})
        self.assertEqual(favorite, [canonical.id])
        CollectionStore.migrate_vierge(connection)
        self.assertEqual(inventory[canonical.id][1], 6)

    def test_batch_guarantees_persist_separately_and_replay_does_not_increment(self):
        engine = Gacha()
        counters, receipts = {}, {}
        connection = Mock()
        def execute(sql, params):
            if sql.startswith('INSERT INTO george_relink_counts'):
                key = (params[0], 'relink')
                counters[key] = counters.get(key, 0) + params[2]
                return SimpleNamespace(fetchone=lambda: (counters[key],))
            if sql.startswith('SELECT user_id'):
                return SimpleNamespace(fetchone=lambda: receipts.get(params[0]))
            if sql.startswith('INSERT INTO george_gacha_batches'):
                counters[params] = counters.get(params, 0) + 1
                return SimpleNamespace(fetchone=lambda: (counters[params],))
            if sql.startswith('INSERT INTO george_gacha_cards'):
                return SimpleNamespace(fetchone=lambda: (1,))
            if sql.startswith('INSERT INTO george_gacha_draws'):
                import json
                receipts[params[0]] = (params[1], params[2], json.loads(params[3]))
            return Mock()
        connection.execute.side_effect = execute
        @contextmanager
        def connect():
            yield connection
        store = CollectionStore('test')
        with patch.object(store, 'connect', connect):
            for game, limit in [('vierge', 4), ('relink', 10)]:
                low = engine.pools[game][list(engine.pools[game])[-1]][0]
                for index in range(1, limit * 2 + 1):
                    result = store.save_draw(10, game, len(receipts) + 100, [low] * (7 if game == 'vierge' else 10))
                    expected = ('UR' if game == 'vierge' else '★3') if index % limit == 0 else ('SR' if game == 'vierge' and index % limit == 1 else low.rarity)
                    self.assertEqual(result[-1]['card']['rarity'], expected)
                    self.assertEqual(len(result), 7 if game == 'vierge' else 10)
                before = dict(counters)
                receipt_id = next(key for key, value in receipts.items() if value[1] == game)
                store.save_draw(10, game, receipt_id, [low])
                self.assertEqual(counters, before)
                store.save_draw(10, game, len(receipts) + 100, [low])
                if game == 'relink':
                    before[(10, game)] += 1
                self.assertEqual(counters, before)
            self.assertEqual(counters, {(10, 'vierge'): 8, (10, 'relink'): 201})
            counters[(20, 'relink')] = 95
            low = engine.pools['relink']['★1'][0]
            result = store.save_draw(20, 'relink', 999, [low] * 10)
            self.assertEqual([entry['card']['rarity'] for entry in result], ['★1'] * 4 + ['★3'] + ['★1'] * 5)
            self.assertEqual(counters[(20, 'relink')], 105)
            counters[(20, 'relink')] = 199
            birthday_card = next(card for card in engine.pools['relink']['★3'] if card.character == 'ロザリー')
            with patch.object(Gacha, 'choose_card', return_value=birthday_card) as birthday_selection:
                result = store.save_draw(20, 'relink', 1000, [low])
                birthday_selection.assert_called_once_with('relink', '★3')
            self.assertEqual(result[0]['card']['character'], 'ロザリー')
            self.assertEqual(result[0]['card']['rarity'], '★3')

    def test_favorite_requires_ownership_and_clear_only_targets_current_user(self):
        card = Card('id', 'ロザリー', 'ロザリー', 'UR')
        connection = Mock()
        found = [None]
        def execute(sql, params):
            if sql.startswith('SELECT card,quantity'):
                self.assertEqual(params, (10, 'vierge', 'id'))
                return SimpleNamespace(fetchone=lambda: found[0])
            return SimpleNamespace(rowcount=1)
        connection.execute.side_effect = execute
        @contextmanager
        def connect():
            yield connection
        store = CollectionStore('test')
        with patch.object(store, 'connect', connect):
            with self.assertRaises(ValueError):
                store.set_favorite(10, 'vierge', 'id')
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in connection.execute.call_args_list))
            found[0] = (asdict(card), 2)
            self.assertEqual(store.set_favorite(10, 'vierge', 'id'), ('vierge', card, 2))
            self.assertTrue(store.clear_favorite(10))
            self.assertEqual(connection.execute.call_args.args, ('DELETE FROM george_gacha_favorites WHERE user_id=%s', (10,)))

    def test_unowned_compares_card_ids_within_game_and_excludes_archived_cards(self):
        first = Card('first', 'ロザリー', 'ロザリー', 'UR')
        second = Card('second', 'ロザリー', 'ロザリー', 'SR')
        other = Card('first', '別作品の子', '別作品の子', '★3')
        engine = SimpleNamespace(pools={'vierge': {'UR': [first], 'SR': [second]}, 'relink': {'★3': [other]}})
        rows = [('vierge', first, 20), ('vierge', Card('old', '旧カード', '旧カード', 'UR'), 1)]
        self.assertEqual(unowned_cards(engine, rows), [('vierge', second, 0), ('relink', other, 0)])
        self.assertEqual(unowned_cards(engine, rows, 'vierge'), [('vierge', second, 0)])
        self.assertEqual(unowned_cards(engine, [], 'relink'), [('relink', other, 0)])

    def test_duplicate_cards_increment_and_receipt_prevents_double_award(self):
        card = vierge_character_card('ロザリー', 'UR')
        connection = Mock()
        receipt = Mock()
        receipt.fetchone.return_value = None
        writes = [SimpleNamespace(fetchone=lambda: (1,)), SimpleNamespace(fetchone=lambda: (2,))]
        def execute(sql, params):
            if sql.startswith('SELECT user_id'):
                return receipt
            if sql.startswith('INSERT INTO george_gacha_cards'):
                return writes.pop(0)
            return Mock()
        connection.execute.side_effect = execute
        @contextmanager
        def connect():
            yield connection
        store = CollectionStore('test')
        with patch.object(store, 'connect', connect):
            result = store.save_draw(10, 'vierge', 100, [card, card])
            self.assertEqual([(entry['new'], entry['quantity']) for entry in result], [(True, 1), (False, 2)])
            connection.execute.reset_mock()
            receipt.fetchone.return_value = (10, 'vierge', result)
            self.assertEqual(store.save_draw(10, 'vierge', 100, [card]), result)
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in connection.execute.call_args_list))
            with self.assertRaises(ValueError):
                store.save_draw(20, 'vierge', 100, [card])

    def test_owned_is_scoped_only_to_requesting_user_and_optional_game(self):
        card = Card('id', 'ロザリー', 'ロザリー', 'UR')
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [('vierge', asdict(card), 3)]
        @contextmanager
        def connect():
            yield connection
        store = CollectionStore('test')
        with patch.object(store, 'connect', connect):
            self.assertEqual(store.owned(10), [('vierge', card, 3)])
        self.assertEqual(connection.execute.call_args.args[1], (10, None, None))
        self.assertIn('WHERE user_id=%s', connection.execute.call_args.args[0])

    def test_collection_rate_counts_unique_current_cards_and_keeps_archived(self):
        engine = Gacha()
        card = engine.pools['vierge']['UR'][0]
        rows = [('vierge', card, 3), ('vierge', Card('old', '昔のカード', '昔のカード', 'UR'), 2)]
        unique, total, copies, archived = collection_summary(engine, rows, 'vierge')
        self.assertEqual((unique, copies, archived), (1, 5, 1))
        self.assertEqual(total, sum(len(pool) for pool in engine.pools['vierge'].values()))
        saved = [dict(card=asdict(card), quantity=1, new=True), dict(card=asdict(card), quantity=2, new=False)]
        embed = result_embed(engine, 'vierge', [card, card], saved)
        self.assertTrue(embed.description.splitlines()[0].startswith('【UR】'))
        self.assertTrue(embed.description.splitlines()[0].endswith('（NEW）'))
        self.assertTrue(embed.description.splitlines()[1].startswith('【UR】'))
        self.assertNotIn('NEW', embed.description.splitlines()[1])
        self.assertNotIn('`01`', embed.description)
        self.assertNotIn('【所持', embed.description)


class ResultCommentTests(unittest.TestCase):
    def test_only_selected_game_counter_and_next_draw_message(self):
        engine = Gacha()
        for counts in ({'vierge': 3, 'relink': 90}, {'vierge': 7, 'relink': 190}):
            for game, expected in [('vierge', '3/4回：**次回7連でUR1枚確定！**'), ('relink', '90/100カウント：**次回10連で★3確定！**')]:
                card = next(iter(engine.pools[game].values()))[0]
                embed = result_embed(engine, game, [card], batch_counts=counts)
                counters = [field.value for field in embed.fields if field.name == 'ガチャカウント']
                self.assertEqual(counters, [expected])
                reset = result_embed(engine, game, [card], batch_counts={'vierge': 4, 'relink': 100})
                text = next(field.value for field in reset.fields if field.name == 'ガチャカウント')
                self.assertTrue(text.startswith('0/'))
                self.assertNotIn('次回', text)

    def test_favorite_introduction_exact_short_and_unknown_names(self):
        for name in ('ロザリー', 'ユーフィリア'):
            introduction, comment = favorite_details(Card('id', name, name, 'UR'))
            self.assertIn('紹介だぜ', introduction)
            self.assertIn(name, comment)
            self.assertNotIn('https://', introduction)
        introduction, _ = favorite_details(Card('id', '存在しない名前', '不明', 'UR'))
        self.assertIn('分からねえ', introduction)

    def test_favorite_exact_and_same_character_take_priority(self):
        favorite = Card('fav', 'ロザリー', 'お気に入り', 'UR')
        variant = Card('variant', 'ロザリー', '別カード', 'SR')
        with patch('gacha_commands.random.choice', side_effect=lambda choices: choices[0]):
            exact = gacha_comment('vierge', [favorite], favorite=('vierge', favorite, 2))
            self.assertIn('お気に入りのロザリー', exact)
            other = gacha_comment('vierge', [variant], favorite=('vierge', favorite, 2))
            self.assertIn('別の一枚', other)
            unrelated = gacha_comment('relink', [Card('fav', 'ロザリー', '別作品', '★1')], favorite=('vierge', favorite, 2))
            self.assertNotIn('お気に入り', unrelated)

    def test_comments_follow_saved_new_rare_and_duplicate_results(self):
        card = Card('one', 'ロザリー', 'ロザリー', 'SR')
        new = [dict(new=True)]
        duplicate = [dict(new=False)]
        with patch('gacha_commands.random.choice', side_effect=lambda choices: choices[0]):
            self.assertIn('初入手が1種類', gacha_comment('vierge', [card], new))
            self.assertIn('枚数はしっかり増えた', gacha_comment('vierge', [card], duplicate))
            self.assertNotIn('増えた', gacha_comment('vierge', [card]))
            rare = Card('rare', 'ロザリー', 'ロザリー', 'UR')
            self.assertIn('URが1枚', gacha_comment('vierge', [rare], duplicate))
            self.assertIn('初入手も1種類', gacha_comment('vierge', [rare], new))

    def test_relink_result_has_bracketed_rarity_and_new_without_numbers(self):
        engine = Gacha()
        card = engine.pools['relink']['★2'][0]
        saved = [dict(new=index == 0, quantity=index + 1) for index in range(10)]
        embed = result_embed(engine, 'relink', [card] * 10, saved)
        for index, line in enumerate(embed.description.splitlines(), 1):
            self.assertTrue(line.startswith('【★2】'))
            self.assertNotIn(f'`{index:02d}`', line)
        self.assertNotIn('【確定枠】', embed.description)
        self.assertEqual(embed.description.count('（NEW）'), 1)
        self.assertLessEqual(len(embed), 6000)


class CollectionCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_draw_ai_uses_saved_facts_and_falls_back_on_failure(self):
        card = Gacha().pools['relink']['★1'][0]
        saved = [dict(card=asdict(card), quantity=1, new=True)]
        store = SimpleNamespace(url='test', save_draw=Mock(return_value=saved))
        client = discord.Client(intents=discord.Intents.default())
        bot = SimpleNamespace(tree=app_commands.CommandTree(client), george_chat=SimpleNamespace(collection_comment=AsyncMock(return_value='お気に入りも増えて楽しいな！')))
        store.favorite = Mock(return_value=('relink', card, 1))
        store.batch_counts = Mock(return_value={})
        register_gacha_commands(bot, store)
        interaction = SimpleNamespace(id=100, user=SimpleNamespace(id=10), response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await bot.tree.get_command('ガチャ').callback(interaction, 'relink', 1)
        facts = bot.george_chat.collection_comment.call_args.args[0]
        self.assertEqual(facts['favorite_relation'], 'exact_card')
        self.assertEqual(facts['new_count'], 1)
        self.assertEqual(facts['cards'][0]['character'], card.character)
        self.assertEqual(interaction.followup.send.call_args.kwargs['embed'].fields[0].value, 'お気に入りも増えて楽しいな！')
        bot.george_chat.collection_comment.side_effect = ValueError('invalid')
        await bot.tree.get_command('ガチャ').callback(interaction, 'relink', 1)
        self.assertIn(card.character, interaction.followup.send.call_args.kwargs['embed'].fields[0].value)
        command = bot.tree.get_command('お気に入り')
        bot.george_chat.collection_comment.side_effect = None
        await command.callback(interaction)
        self.assertEqual(bot.george_chat.collection_comment.call_args.args[0]['action'], 'favorite_view')
        await client.close()

    async def test_favorite_candidates_sort_by_game_then_descending_rarity(self):
        expected = [('vierge', rarity) for rarity in ('UR', 'SR', 'HR', 'R')] + [('relink', rarity) for rarity in ('★3', '★2', '★1')]
        rows = [(game, Card(str(index), 'ロザリー', 'ロザリー', rarity), 1)
                for index, (game, rarity) in enumerate(expected)]
        store = SimpleNamespace(url='test', owned=Mock(return_value=list(reversed(rows))))
        client, tree, interaction = self.objects(store)
        autocomplete = tree.get_command('お気に入り')._params['カード'].autocomplete
        for query in ('', 'ロザリー'):
            choices = await autocomplete(interaction, query)
            self.assertEqual([choice.value for choice in choices], [f'{game}:{card.id}' for game, card, _ in rows])
        interaction.namespace = SimpleNamespace(作品='relink', プログレス='ロザ')
        choices = await autocomplete(interaction, '')
        self.assertEqual([choice.value for choice in choices], [f'{game}:{card.id}' for game, card, _ in rows if game == 'relink'])
        interaction.namespace.プログレス = '該当なし'
        self.assertEqual(await autocomplete(interaction, ''), [])
        await client.close()

    async def test_favorite_registration_view_removal_and_pinning(self):
        engine = Gacha()
        cards = [card for pool in engine.pools['vierge'].values() for card in pool]
        picked = cards[-1]
        chosen = ('vierge', picked, 2)
        store = SimpleNamespace(url='test', owned=Mock(return_value=[('vierge', card, 2) for card in cards]),
                                favorite=Mock(return_value=chosen), set_favorite=Mock(return_value=chosen), clear_favorite=Mock(return_value=True))
        client, tree, interaction = self.objects(store)
        command = tree.get_command('お気に入り')
        await command.callback(interaction, f'vierge:{picked.id}')
        store.set_favorite.assert_called_once_with(10, 'vierge', picked.id)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        await command.callback(interaction)
        store.favorite.assert_called_with(10)
        self.assertEqual([field.name for field in interaction.followup.send.call_args.kwargs['embed'].fields],
                         ['ジョージのプログレス紹介', 'ジョージの一言'])
        await tree.get_command('所持カード').callback(interaction)
        first = interaction.followup.send.call_args.kwargs['embed'].description.splitlines()[0]
        self.assertTrue(first.startswith('⭐ '))
        self.assertIn(picked.name, first)
        await command.callback(interaction, 解除=True)
        store.clear_favorite.assert_called_once_with(10)
        self.assertIn('所持カードはそのまま', interaction.followup.send.call_args.args[0])
        await command.callback(interaction, 'unknown-card')
        self.assertIn('候補から', interaction.followup.send.call_args.args[0])
        await command.callback(interaction, f'vierge:{picked.id}', True)
        self.assertEqual(store.set_favorite.call_count, 1)
        autocomplete = command._params['カード'].autocomplete
        choices = await autocomplete(interaction, picked.character)
        store.owned.assert_called_with(10)
        self.assertLessEqual(len(choices), 25)
        self.assertTrue(all(choice.value.startswith('vierge:') and len(choice.name) <= 100 for choice in choices))
        await client.close()

    def objects(self, store):
        if not hasattr(store, 'batch_counts'):
            store.batch_counts = Mock(return_value={})
        if not hasattr(store, 'favorite'):
            store.favorite = Mock(return_value=None)
        client = discord.Client(intents=discord.Intents.default())
        bot = SimpleNamespace(tree=app_commands.CommandTree(client))
        register_gacha_commands(bot, store)
        interaction = SimpleNamespace(id=100, user=SimpleNamespace(id=10),
                                      response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        return client, bot.tree, interaction

    async def test_draw_persists_before_result_and_failure_is_private(self):
        engine = Gacha()
        card = engine.pools['relink']['★1'][0]
        saved = [dict(card=asdict(card), quantity=1, new=True)]
        store = SimpleNamespace(url='test', save_draw=Mock(return_value=saved))
        client, tree, interaction = self.objects(store)
        await tree.get_command('ガチャ').callback(interaction, 'relink', 1)
        self.assertEqual(store.save_draw.call_args.args[:3], (10, 'relink', 100))
        self.assertIn('（NEW）', interaction.followup.send.call_args.kwargs['embed'].description)
        store.favorite.side_effect = MemoryUnavailable('offline')
        await tree.get_command('ガチャ').callback(interaction, 'relink', 1)
        self.assertIn('（NEW）', interaction.followup.send.call_args.kwargs['embed'].description)
        store.save_draw.side_effect = MemoryUnavailable('offline')
        interaction.followup.send.reset_mock()
        await tree.get_command('ガチャ').callback(interaction, 'relink', 1)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        self.assertNotIn('embed', interaction.followup.send.call_args.kwargs)
        await client.close()

    async def test_private_filtered_paginated_inventory_and_completion(self):
        engine = Gacha()
        cards = [card for pool in engine.pools['vierge'].values() for card in pool]
        rosaries = [card for card in cards if card.character == 'ロザリー' and card.rarity == 'UR']
        rows = [('vierge', card, 2) for card in cards]
        store = SimpleNamespace(url='test', owned=Mock(return_value=rows))
        client, tree, interaction = self.objects(store)
        await tree.get_command('所持カード').callback(interaction, 'vierge', 'ロザリー', 'UR', 1)
        store.owned.assert_called_with(10, 'vierge')
        call = interaction.followup.send.call_args
        self.assertTrue(call.kwargs['ephemeral'])
        self.assertEqual(len(call.kwargs['embed'].description.splitlines()), min(10, len(rosaries)))
        self.assertNotIn('ヴィエルジュ', call.kwargs['embed'].description)
        self.assertNotIn('リリンク', call.kwargs['embed'].description)
        self.assertFalse(call.kwargs['embed'].footer.text)
        await tree.get_command('所持カード').callback(interaction, ページ=2)
        self.assertEqual(len(interaction.followup.send.call_args.kwargs['embed'].description.splitlines()), 10)
        await tree.get_command('収集率').callback(interaction)
        embed = interaction.followup.send.call_args.kwargs['embed']
        self.assertIn('100.0%', embed.fields[0].value)
        self.assertIn('0.0%', embed.fields[1].value)
        self.assertLess(len(embed), 6000)
        await client.close()

    async def test_unavailable_inventory_reports_without_exposing_db_details(self):
        store = SimpleNamespace(url='', owned=Mock(side_effect=MemoryUnavailable('保存先を利用できません')))
        client, tree, interaction = self.objects(store)
        for name in ('所持カード', '未所持カード', '収集率'):
            await tree.get_command(name).callback(interaction)
            self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        await client.close()

    async def test_unowned_filter_pagination_complete_and_invalid_page(self):
        engine = Gacha()
        cards = [card for pool in engine.pools['vierge'].values() for card in pool]
        rosaries = [card for card in cards if card.character == 'ロザリー' and card.rarity == 'UR']
        store = SimpleNamespace(url='test', owned=Mock(return_value=[('vierge', rosaries[0], 3)]))
        client, tree, interaction = self.objects(store)
        command = tree.get_command('未所持カード')
        await command.callback(interaction, 'vierge', 'ロザリー', 'UR', 1)
        store.owned.assert_called_with(10, 'vierge')
        call = interaction.followup.send.call_args
        self.assertTrue(call.kwargs['ephemeral'])
        embed = call.kwargs['embed']
        self.assertFalse(embed.footer.text)
        self.assertNotIn(rosaries[0].label, embed.description)
        await command.callback(interaction, ページ=2)
        embed = interaction.followup.send.call_args.kwargs['embed']
        self.assertEqual(len(embed.description.splitlines()), 10)
        self.assertLess(len(embed), 6000)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
        await command.callback(interaction, 'vierge', ページ=1000000)
        self.assertNotIn('embed', interaction.followup.send.call_args.kwargs)
        store.owned.return_value = [('vierge', card, 1) for card in cards]
        await command.callback(interaction, 'vierge')
        embed = interaction.followup.send.call_args.kwargs['embed']
        self.assertIn('全部そろってる', embed.description)
        self.assertFalse(embed.footer.text)
        await command.callback(interaction, 'vierge', '存在しない名前')
        self.assertIn('この条件', interaction.followup.send.call_args.kwargs['embed'].description)
        await client.close()
