import unittest
import discord
from discord_layout import space_headings, GAP
from gacha import Gacha, RULES
from gacha_commands import rates_embed, result_embed

class LayoutTests(unittest.TestCase):
    def test_spacers_are_idempotent_and_fit_discord_limits(self):
        embed=discord.Embed(description='A'*4096)
        embed.add_field(name='first',value='B'*1024,inline=False)
        embed.add_field(name='second',value='C',inline=False)
        space_headings(embed)
        snapshot=embed.to_dict()
        space_headings(embed)
        self.assertEqual(embed.to_dict(),snapshot)
        self.assertLessEqual(len(embed.description),4096)
        self.assertLessEqual(len(embed.fields[0].value),1024)
        self.assertTrue(embed.description.endswith(GAP))
        self.assertTrue(embed.fields[0].value.endswith(GAP))

    def test_gacha_result_and_rates_have_spaced_headings(self):
        engine=Gacha()
        for game in ('vierge','relink'):
            cards=engine.draw(game,RULES[game].batch_size)
            result=result_embed(engine,game,cards,batch_counts={})
            self.assertEqual(result.fields[0].name,'【ジョージの一言】')
            self.assertEqual(result.fields[1].name,'【ガチャカウント】')
            for embed in (result,rates_embed(engine,game)):
                self.assertTrue(embed.description.endswith(GAP))
                self.assertTrue(all(field.value.endswith(GAP) for field in embed.fields[:-1]))
                self.assertLessEqual(len(embed),6000)
