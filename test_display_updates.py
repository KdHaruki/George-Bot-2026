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
        choices = await main.progress_autocomplete(interaction, '')
        worlds = [choice.value for choice in choices if '世界' in choice.value]
        self.assertEqual(worlds, [color + 'の世界' for color in '青黒赤白緑'])
        from unittest.mock import patch
        with patch('main.progress_module.progressSearchAll') as search:
            for query in ('全ての世界', '全世界', '全ての', '全'):
                await main.progress.callback(interaction, query)
            search.assert_not_called()

    async def test_fortune_layout(self):
        from fun_features import fortune_embed
        embed = fortune_embed('大吉', '今日はいい調子だぜ！', '帽子')
        self.assertIn('大吉', embed.description)
        self.assertEqual(embed.fields[0].value, '今日はいい調子だぜ！')
        self.assertEqual(embed.fields[1].value, '帽子')
        from fun_features import LUCKY_PROGRESS
        self.assertEqual(embed.fields[2].name, '🌟 ラッキープログレス')
        self.assertIn(embed.fields[2].value, LUCKY_PROGRESS)

    async def test_lucky_progress_includes_relink_exclusives_once(self):
        from fun_features import LUCKY_PROGRESS, fortune_embed
        from progress import progressData
        from unittest.mock import patch
        self.assertEqual(set(LUCKY_PROGRESS), {person['progressName'] for person in progressData})
        self.assertEqual(len(LUCKY_PROGRESS), len(set(LUCKY_PROGRESS)))
        for name in ('久遠空', 'シンシア', 'ヒメガミノミコト', 'ナクル・クルルシファー'):
            self.assertIn(name, LUCKY_PROGRESS)
            with patch('fun_features.random.choice', return_value=name) as choose:
                embed = fortune_embed('凶', 'ひと息つこうぜ！', '帽子')
            choose.assert_called_once_with(LUCKY_PROGRESS)
            self.assertEqual(embed.fields[2].value, name)
