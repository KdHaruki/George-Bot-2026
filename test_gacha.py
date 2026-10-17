import collections
import random
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord import app_commands

from gacha import Gacha, RULES, choose_rarity, RELINK_OUTFITS, current_card, Card, outfit_display_name, VIERGE_CHARACTERS
from gacha_commands import register_gacha_commands, rates_embed, result_embed
from command_help import command_help
from progress import progressData


class Ticket:
    def __init__(self, value):
        self.value = value

    def randrange(self, maximum):
        assert maximum == 10000
        return self.value

    def choice(self, values):
        return values[0]


class GachaTests(unittest.TestCase):
    def test_birthday_is_exactly_half_and_shared_birthdays_split_pool(self):
        engine = Gacha()
        self.assertTrue({card.character for card in engine.pools['relink']['★3']} <= engine.birthdays.keys())
        for value, featured in ((0, True), (4999, True), (5000, False), (9999, False)):
            card = engine.choose_card('relink', '★3', Ticket(value), date(2026, 11, 26))
            self.assertEqual(card.character == 'ロザリー', featured)
        class InspectPool(Ticket):
            def choice(self, values):
                self.names = {card.character for card in values}
                if not hasattr(self, 'seen'):
                    self.seen = []
                self.seen.append(self.names)
                return values[0]
        rng = InspectPool(0)
        engine.choose_card('relink', '★3', rng, date(2026, 3, 24))
        self.assertEqual(rng.seen[0], {'ナクル', 'ラウラ'})
        engine.choose_card('relink', '★3', rng, date(2026, 10, 16))
        self.assertEqual(rng.names, {card.character for card in engine.pools['relink']['★3']})
        engine.choose_card('relink', '★2', rng, date(2026, 11, 26))
        self.assertEqual(len(rng.names), 10)

    @classmethod
    def setUpClass(cls):
        cls.engine = Gacha()

    def test_exact_probability_mass_and_zero_weight(self):
        for rules in RULES.values():
            for table in (rules.normal, rules.guaranteed):
                counts = collections.Counter(choose_rarity(table, Ticket(i)) for i in range(10000))
                self.assertEqual(dict(counts), {rarity: weight for rarity, weight in table if weight})
        with self.assertRaises(ValueError):
            choose_rarity((('UR', 9999),), Ticket(0))

    def test_guarantee_is_one_slot_with_its_own_probability(self):
        # 2% selects SR in the normal Vierge slot and UR in the seventh slot.
        cards = self.engine.draw('vierge', 7, Ticket(200))
        self.assertEqual([card.rarity for card in cards], ['SR'] * 6 + ['UR'])
        # A 99% ticket selects R normally, HR guaranteed; ★1 normally, ★2 guaranteed.
        self.assertEqual([card.rarity for card in self.engine.draw('vierge', 7, Ticket(9900))], ['R'] * 6 + ['HR'])
        self.assertEqual([card.rarity for card in self.engine.draw('relink', 10, Ticket(9900))], ['★1'] * 9 + ['★2'])
        self.assertEqual(self.engine.draw('vierge', 1, Ticket(9900))[0].rarity, 'R')

    def test_invalid_count_never_draws(self):
        for game, count in [('vierge', 10), ('relink', 7), ('vierge', 0), ('relink', 100)]:
            with self.assertRaises(ValueError):
                self.engine.draw(game, count)

    def test_card_membership_and_distinct_rarities_for_one_character(self):
        allowed = {p['progressName'] for p in VIERGE_CHARACTERS}
        self.assertEqual(len(allowed), 209)
        self.assertFalse({'久遠空', '久遠 空', 'シンシア', 'ヒメガミノミコト', 'ナクル・クルルシファー'} & allowed)
        cards = [card for group in self.engine.pools['vierge'].values() for card in group]
        self.assertTrue(all(card.character in allowed for card in cards))
        self.assertEqual(len({card.id for card in cards}), len(cards))
        rosaries = {card.rarity for card in cards if card.character == 'ロザリー'}
        self.assertTrue({'UR', 'SR', 'HR'} <= rosaries)
        missing = set(self.engine.catalog['games']['vierge']['missing_characters'])
        self.assertEqual(allowed, {card.character for card in cards} | missing)
        self.assertFalse({card.character for card in cards} & missing)
        self.assertFalse(missing)
        self.assertEqual(len(cards), 209 * 4)
        self.assertTrue(all(card.name == card.character and card.cost is None and not card.skill for card in cards))
        for pool in self.engine.pools['vierge'].values():
            self.assertEqual({card.character for card in pool}, allowed)
        self.assertEqual({rarity: len(pool) for rarity, pool in self.engine.pools['relink'].items()}, {'★3': 46, '★2': 10, '★1': 10})
        cards = self.engine.pools['relink']['★3']
        limited = [card for card in cards if '（' in RELINK_OUTFITS[card.id]['wiki_name']]
        self.assertEqual(len(limited), 29)
        theo = next(card for card in limited if RELINK_OUTFITS[card.id]['wiki_name'] == 'テオ（バレンタイン）')
        self.assertEqual(theo.character, 'テオドーチェ')
        import hashlib
        for card in [card for pool in self.engine.pools['relink'].values() for card in pool]:
            original_name = RELINK_OUTFITS[card.id]['wiki_name']
            old_id = 'relink-' + hashlib.sha256((original_name + card.rarity).encode()).hexdigest()[:16]
            self.assertEqual(card.id, old_id)
            self.assertEqual(card.name, outfit_display_name(card.character, RELINK_OUTFITS[card.id]['outfit']))
            old = Card(card.id, card.character, original_name, card.rarity)
            self.assertEqual(current_card('relink', old).name, card.name)

    def test_embeds_fit_discord_limits_and_disclose_scope(self):
        for game, rules in RULES.items():
            self.assertNotIn('https://', str(rates_embed(self.engine, game).to_dict()))
            for embed in (rates_embed(self.engine, game), result_embed(self.engine, game, self.engine.draw(game, rules.batch_size, random.Random(7)))):
                self.assertLessEqual(len(embed), 6000)
                self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
                self.assertLessEqual(len(embed.description), 4096)
        for guild in (True, False):
            self.assertLessEqual(len(command_help(guild)), 6000)
            self.assertTrue(all(len(field.value) <= 1024 for field in command_help(guild).fields))


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_register_once_and_wrong_batch_is_private(self):
        client = discord.Client(intents=discord.Intents.none())
        bot = SimpleNamespace(tree=app_commands.CommandTree(client))
        register_gacha_commands(bot, store=SimpleNamespace(url=''))
        self.assertEqual([p.name for p in bot.tree.get_command('ガチャ').parameters], ['作品'])
        interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await bot.tree.get_command('ガチャ').callback(interaction, 'invalid')
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        interaction.response.send_message.reset_mock()
        await bot.tree.get_command('ガチャ').callback(interaction, 'relink')
        self.assertIn('DATABASE_URL', interaction.response.send_message.call_args.args[0])
        interaction.followup.send.assert_not_called()
        await client.close()


if __name__ == '__main__':
    unittest.main()
