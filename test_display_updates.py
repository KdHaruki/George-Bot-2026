import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

class DisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_world_search_and_choices(self):
        import main
        from progress import progressData
        interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        for color in '青黒赤白緑':
            choices = await main.progress_autocomplete(interaction, color + 'の世界')
            self.assertIn(color + 'の世界', [choice.value for choice in choices])
            await main.progress.callback(interaction, color + 'の世界')
            text = interaction.response.send_message.call_args.args[0]
            for person in progressData:
                if person['progressWorld'] == color:
                    self.assertIn(person['progressName'], text)
        await main.progress.callback(interaction, '全ての世界')
        self.assertLessEqual(len(interaction.response.send_message.call_args.args[0]), 2000)
        self.assertTrue(all(len(call.args[0]) <= 2000 for call in interaction.followup.send.call_args_list))

    async def test_fortune_layout(self):
        from fun_features import fortune_embed
        embed = fortune_embed('大吉', '今日はいい調子だぜ！', '帽子')
        self.assertIn('大吉', embed.description)
        self.assertEqual(embed.fields[0].value, '今日はいい調子だぜ！')
        self.assertEqual(embed.fields[1].value, '帽子')
