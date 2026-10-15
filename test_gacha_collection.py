import unittest
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

from gacha import Card, Gacha
from gacha_collection import CollectionStore, collection_summary, unowned_cards
from gacha_commands import register_gacha_commands, result_embed
from registered_memory import MemoryUnavailable


class StoreTests(unittest.TestCase):
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
        card = Card('id', 'ロザリー', 'ロザリー', 'UR')
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
        self.assertTrue(embed.description.splitlines()[0].startswith('**NEW** '))
        self.assertFalse(embed.description.splitlines()[1].startswith('**NEW** '))
        self.assertIn('【所持2枚】', embed.description)


class CollectionCommandTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertTrue(interaction.followup.send.call_args.kwargs['embed'].description.startswith('**NEW** '))
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
        self.assertIn(f'該当{len(rosaries) - 1}種類', embed.footer.text)
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
        self.assertIn('該当0種類', embed.footer.text)
        await command.callback(interaction, 'vierge', '存在しない名前')
        self.assertIn('この条件', interaction.followup.send.call_args.kwargs['embed'].description)
        await client.close()
