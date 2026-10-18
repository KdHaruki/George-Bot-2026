import unittest
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

from gacha import Card, Gacha, RULES, vierge_character_card
from gacha_collection import CollectionStore, collection_summary, unowned_cards
from gacha_commands import CardListView, favorite_details, gacha_comment, register_gacha_commands, result_embed
from registered_memory import MemoryUnavailable


class StoreTests(unittest.TestCase):
    def test_same_favorite_toggle_deletes_only_registration(self):
        card = vierge_character_card('ロザリー', 'UR')
        current = [None]
        connection = Mock()
        def execute(sql, params):
            if sql.startswith('SELECT card,quantity'):
                return SimpleNamespace(fetchone=lambda: (asdict(card), 3))
            if sql.startswith('SELECT game,card_id'):
                return SimpleNamespace(fetchone=lambda: current[0])
            if sql.startswith('INSERT INTO george_gacha_favorites'):
                current[0] = (params[1], params[2])
            if sql.startswith('DELETE FROM george_gacha_favorites'):
                self.assertEqual(params, (10,))
                current[0] = None
            return Mock()
        connection.execute.side_effect = execute
        @contextmanager
        def connect():
            yield connection
        store = CollectionStore('test')
        with patch.object(store, 'connect', connect):
            self.assertIsNotNone(store.set_favorite(10, 'vierge', card.id, toggle=True))
            self.assertIsNone(store.set_favorite(10, 'vierge', card.id, toggle=True))
            self.assertIsNone(current[0])
            current[0] = ('relink', card.id)
            self.assertIsNotNone(store.set_favorite(10, 'vierge', card.id, toggle=True))
        self.assertFalse(any('DELETE FROM george_gacha_cards' in call.args[0] for call in connection.execute.call_args_list))

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
        self.assertTrue(embed.description.splitlines()[0].endswith('**✨ NEW**'))
        self.assertTrue(embed.description.splitlines()[1].startswith('【UR】'))
        self.assertNotIn('NEW', embed.description.splitlines()[1])
        self.assertNotIn('`01`', embed.description)
        self.assertNotIn('【所持', embed.description)


class ResultCommentTests(unittest.TestCase):
    def test_result_sorts_rarity_stably_without_moving_new_to_another_card(self):
        engine = Gacha()
        for game, rarities in [('vierge', ['R', 'SR', 'UR', 'HR', 'SR']), ('relink', ['★1', '★2', '★3', '★2'])]:
            cards = [Card(str(index), f'子{index}', f'子{index}', rarity) for index, rarity in enumerate(rarities)]
            saved = [dict(new=index == 1) for index in range(len(cards))]
            original = list(cards)
            lines = result_embed(engine, game, cards, saved).description.splitlines()
            rank = {rarity: index for index, (rarity, _) in enumerate(RULES[game].normal)}
            expected = sorted(range(len(cards)), key=lambda index: rank[rarities[index]])
            for line, index in zip(lines, expected):
                self.assertIn(f'子{index}', line)
                self.assertEqual('✨ NEW' in line, index == 1)
            self.assertEqual(cards, original)

    def test_only_selected_game_counter_and_next_draw_message(self):
        engine = Gacha()
        for counts in ({'vierge': 3, 'relink': 90}, {'vierge': 7, 'relink': 190}):
            for game, expected in [('vierge', '3/4回：**次回7連でUR1枚確定！**'), ('relink', '90/100：**次回10連で★3確定！**')]:
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
            self.assertTrue(line.startswith('`【★2】` '))
            self.assertNotIn(f'`{index:02d}`', line)
        self.assertNotIn('【確定枠】', embed.description)
        self.assertEqual(embed.description.count('**✨ NEW**'), 1)
        self.assertLessEqual(len(embed), 6000)


class CollectionCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_and_empty_lists_omit_view_instead_of_passing_none(self):
        card = Gacha().pools['vierge']['UR'][0]
        store = SimpleNamespace(url='test', owned=Mock(return_value=[]))
        client, tree, interaction = self.objects(store)
        async def validate_send(**kwargs):
            if 'view' in kwargs and not isinstance(kwargs['view'], discord.ui.View):
                raise TypeError('Discord rejects explicit view=None')
        interaction.followup.send.side_effect = validate_send
        for rows in ([], [('vierge', card, 1)]):
            store.owned.return_value = rows
            await tree.get_command('所持カード').callback(interaction, 'ロザリー')
            self.assertNotIn('view', interaction.followup.send.call_args.kwargs)
        store.owned.return_value = [('vierge', value, 1) for value in [card for card in Gacha().pools['vierge']['UR'] if 'ア' in card.character][:11]]
        await tree.get_command('所持カード').callback(interaction, 'ア')
        view = interaction.followup.send.call_args.kwargs['view']
        self.assertIsInstance(view, CardListView)
        view.stop()
        await client.close()

    async def test_draw_always_saves_game_batch_size(self):
        def save(uid, game, interaction_id, cards):
            return [dict(card=asdict(card), quantity=2, new=False) for card in cards]
        store = SimpleNamespace(url='test', save_draw=Mock(side_effect=save))
        client, tree, interaction = self.objects(store)
        for game, size in [('vierge', 7), ('relink', 10)]:
            await tree.get_command('ガチャ').callback(interaction, game)
            self.assertEqual(len(store.save_draw.call_args.args[3]), size)
        await client.close()

    async def test_list_buttons_are_owner_only_and_page_argument_is_removed(self):
        client, tree, _ = self.objects(SimpleNamespace(url='test'))
        for name in ('所持カード',):
            self.assertNotIn('ページ', [parameter.name for parameter in tree.get_command(name).parameters])
        view = CardListView(10, [f'カード{index}' for index in range(21)], '所持カード')
        interaction = SimpleNamespace(user=SimpleNamespace(id=20), response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()))
        await view.go_next(interaction)
        self.assertEqual(view.page, 0)
        interaction.user.id = 10
        await view.go_next(interaction)
        self.assertEqual(view.embed().description.splitlines()[0], 'カード10')
        await view.go_next(interaction)
        self.assertTrue(view.next.disabled)
        self.assertEqual(view.embed().description, 'カード20')
        await view.go_previous(interaction)
        self.assertFalse(view.next.disabled)
        view.stop()
        await client.close()

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
        await bot.tree.get_command('ガチャ').callback(interaction, 'relink')
        facts = bot.george_chat.collection_comment.call_args.args[0]
        self.assertEqual(facts['favorite_relation'], 'exact_card')
        self.assertEqual(facts['new_count'], 1)
        self.assertEqual(facts['cards'][0]['character'], card.character)
        self.assertEqual(interaction.followup.send.call_args.kwargs['embed'].fields[0].value, 'お気に入りも増えて楽しいな！')
        bot.george_chat.collection_comment.side_effect = ValueError('invalid')
        await bot.tree.get_command('ガチャ').callback(interaction, 'relink')
        self.assertIn(card.character, interaction.followup.send.call_args.kwargs['embed'].fields[0].value)
        command = bot.tree.get_command('お気に入り')
        bot.george_chat.collection_comment.side_effect = None
        await command.callback(interaction)
        self.assertEqual(bot.george_chat.collection_comment.call_args.args[0]['action'], 'favorite_view')
        facts = bot.george_chat.collection_comment.call_args.args[0]
        self.assertNotIn('cards', facts)
        self.assertNotIn('saved', facts)
        details = next(call.kwargs['embed'] for call in reversed(interaction.followup.send.call_args_list) if 'embed' in call.kwargs)
        self.assertFalse(details.footer.text)
        self.assertTrue(interaction.followup.send.call_args.kwargs['files'])
        await client.close()

    async def test_favorite_name_only_selects_highest_and_repeating_name_removes(self):
        engine = Gacha()
        low = next(card for card in engine.pools['vierge']['R'] if card.character == 'ロザリー')
        high = next(card for card in engine.pools['relink']['★3'] if card.character == 'ロザリー')
        state = [None]
        rows = [('vierge', low, 1), ('relink', high, 2)]
        def set_favorite(uid, game, card_id, toggle=False):
            chosen = next(row for row in rows if row[0] == game and row[1].id == card_id)
            state[0] = None if state[0] == chosen else chosen
            return state[0]
        store = SimpleNamespace(url='test', owned=Mock(return_value=rows), favorite=Mock(side_effect=lambda uid: state[0]), set_favorite=Mock(side_effect=set_favorite))
        client, tree, interaction = self.objects(store)
        command = tree.get_command('お気に入り')
        self.assertEqual([p.name for p in command.parameters], ['プログレス'])
        autocomplete = command._params['プログレス'].autocomplete
        choices = await autocomplete(interaction, 'ロザ')
        self.assertEqual([choice.value for choice in choices], ['ロザリー'])
        await command.callback(interaction, 'ロザリー')
        self.assertEqual(state[0], ('relink', high, 2))
        await command.callback(interaction)
        self.assertEqual(state[0], ('relink', high, 2))
        await command.callback(interaction, 'ロザリー')
        self.assertIsNone(state[0])
        self.assertIn('解除', interaction.followup.send.call_args.args[0])
        await command.callback(interaction, '未所持の名前')
        self.assertIn('まだ持っていない', interaction.followup.send.call_args.args[0])
        self.assertIsNone(tree.get_command('未所持カード'))
        self.assertIn('プログレス', [p.name for p in tree.get_command('所持カード').parameters])
        self.assertTrue(tree.get_command('所持カード').parameters[0].required)
        self.assertEqual(tree.get_command('収集率').parameters, [])
        self.assertNotIn('キャラ', [p.name for p in tree.get_command('所持カード').parameters])
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
        await tree.get_command('ガチャ').callback(interaction, 'relink')
        self.assertEqual(store.save_draw.call_args.args[:3], (10, 'relink', 100))
        self.assertIn('**✨ NEW**', interaction.followup.send.call_args.kwargs['embed'].description)
        store.favorite.side_effect = MemoryUnavailable('offline')
        await tree.get_command('ガチャ').callback(interaction, 'relink')
        self.assertIn('**✨ NEW**', interaction.followup.send.call_args.kwargs['embed'].description)
        store.save_draw.side_effect = MemoryUnavailable('offline')
        interaction.followup.send.reset_mock()
        await tree.get_command('ガチャ').callback(interaction, 'relink')
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
        await tree.get_command('所持カード').callback(interaction, 'ロザリー')
        store.owned.assert_called_with(10)
        call = interaction.followup.send.call_args
        self.assertTrue(call.kwargs['ephemeral'])
        self.assertEqual(len(call.kwargs['embed'].description.splitlines()), 4)
        self.assertNotIn('ヴィエルジュ', call.kwargs['embed'].description)
        self.assertNotIn('リリンク', call.kwargs['embed'].description)
        self.assertFalse(call.kwargs['embed'].footer.text)
        await tree.get_command('所持カード').callback(interaction, 'ロザリー')
        self.assertEqual(len(interaction.followup.send.call_args.kwargs['embed'].description.splitlines()), 4)
        await tree.get_command('収集率').callback(interaction)
        embed = interaction.followup.send.call_args.kwargs['embed']
        self.assertIn('100.0%', embed.fields[0].value)
        self.assertFalse(embed.footer.text)
        self.assertIn('0.0%', embed.fields[1].value)
        self.assertLess(len(embed), 6000)
        await client.close()

    async def test_unavailable_inventory_reports_without_exposing_db_details(self):
        store = SimpleNamespace(url='', owned=Mock(side_effect=MemoryUnavailable('保存先を利用できません')))
        client, tree, interaction = self.objects(store)
        for name in ('所持カード', '収集率'):
            await tree.get_command(name).callback(interaction, *(['ロザリー'] if name == '所持カード' else []))
            self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        await client.close()
