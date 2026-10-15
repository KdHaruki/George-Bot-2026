import collections
import random
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord import app_commands

from gacha import Gacha, RULES, choose_rarity
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
        allowed = {p['progressName'] for p in progressData}
        cards = [card for group in self.engine.pools['vierge'].values() for card in group]
        self.assertTrue(all(card.character in allowed for card in cards))
        self.assertEqual(len({card.id for card in cards}), len(cards))
        rosaries = {card.rarity for card in cards if card.character == 'ロザリー'}
        self.assertTrue({'UR', 'SR', 'HR'} <= rosaries)
        missing = set(self.engine.catalog['games']['vierge']['missing_characters'])
        self.assertEqual(allowed, {card.character for card in cards} | missing)
        self.assertFalse({card.character for card in cards} & missing)
        self.assertEqual({rarity: len(pool) for rarity, pool in self.engine.pools['relink'].items()}, {'★3': 17, '★2': 10, '★1': 10})
        self.assertEqual(self.engine.pools['relink']['★3'][0].name, 'ナクル')

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
        autocomplete = bot.tree.get_command('ガチャ')._params['回数'].autocomplete
        for game, expected in [('vierge', [1, 7]), ('relink', [1, 10]), (None, [1])]:
            choices = await autocomplete(SimpleNamespace(namespace=SimpleNamespace(作品=game)), 0)
            self.assertEqual([choice.value for choice in choices], expected)
        self.assertEqual({command.name for command in bot.tree.get_commands()}, {'ガチャ', 'ガチャ確率', '所持カード', '未所持カード', '収集率', 'お気に入り'})
        interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await bot.tree.get_command('ガチャ').callback(interaction, 'relink', 7)
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        interaction.response.send_message.reset_mock()
        await bot.tree.get_command('ガチャ').callback(interaction, 'relink', 10)
        self.assertEqual(len(interaction.followup.send.call_args.kwargs['embed'].description.splitlines()), 10)
        await client.close()


if __name__ == '__main__':
    unittest.main()
