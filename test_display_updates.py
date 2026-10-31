import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

class DisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_given_name_search_matches_candidates_and_title_record(self):
        import main
        from progress import progressSearch, name_search_matches
        interaction = SimpleNamespace(id=101, user=SimpleNamespace(id=42),
            response=SimpleNamespace(send_message=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        for query in ('苺', ' 苺 ', 'いちご', '　あまい　いちご　'):
            self.assertEqual([p['progressName'] for p in name_search_matches(query)], ['天井苺'])
            self.assertTrue(progressSearch(query).startswith('【名前】天井苺\n'))
            choices = await main.progress_autocomplete(interaction, query)
            self.assertIn('天井苺', [choice.value for choice in choices])
            with patch.object(main.client.title_store, 'named_profile_search', Mock()) as named, patch('main.notify_titles', AsyncMock()):
                await main.progress.callback(interaction, query)
            named.assert_called_once_with(42, 101, '天井苺')
            self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        self.assertEqual(name_search_matches(''), [])
        self.assertNotIn('【名前】', progressSearch(''))

    async def test_ambiguous_partial_name_never_records_a_random_person(self):
        import main
        from progress import name_search_matches
        self.assertGreater(len(name_search_matches('マリ')), 1)
        interaction = SimpleNamespace(id=101, user=SimpleNamespace(id=42),
            response=SimpleNamespace(send_message=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(main.client.title_store, 'named_profile_search', Mock()) as named:
            await main.progress.callback(interaction, 'マリ')
        named.assert_not_called()

    async def test_only_successful_named_search_records_person(self):
        import main
        interaction = SimpleNamespace(id=101, user=SimpleNamespace(id=42),
            response=SimpleNamespace(send_message=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(main.client.title_store, 'named_profile_search', Mock()) as named, patch.object(main.client.title_store, 'world_search', Mock()) as world, patch('main.notify_titles', AsyncMock()):
            await main.progress.callback(interaction, 'ロザリー')
            named.assert_called_once_with(42, 101, 'ロザリー')
            named.reset_mock()
            await main.progress.callback(interaction, '赤の世界')
            await main.progress.callback(interaction, '存在しない名前')
            named.assert_not_called()
            world.assert_called_once()

    async def test_world_search_and_choices(self):
        import main
        from progress import progressData
        helper = patch.object(main.client.title_store, 'world_search', Mock())
        helper.start()
        self.addCleanup(helper.stop)
        notifier = patch('main.notify_titles', AsyncMock())
        notifier.start()
        self.addCleanup(notifier.stop)
        interaction = SimpleNamespace(id=100, user=SimpleNamespace(id=42), response=SimpleNamespace(send_message=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        for color in '青黒赤白緑':
            choices = await main.progress_autocomplete(interaction, color + 'の世界')
            self.assertIn(color + 'の世界', [choice.value for choice in choices])
            await main.progress.callback(interaction, color + 'の世界')
            self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
            self.assertTrue(all(call.kwargs['ephemeral'] for call in interaction.followup.send.call_args_list))
            text = interaction.response.send_message.call_args.args[0]
            for person in progressData:
                if person['progressWorld'] == color:
                    self.assertIn(person['progressName'], text)
        choices = await main.progress_autocomplete(interaction, '')
        worlds = [choice.value for choice in choices if '世界' in choice.value]
        self.assertEqual(worlds, [color + 'の世界' for color in '青黒赤白緑'])
        with patch('main.progress_module.progressSearchAll') as search:
            for query in ('全ての世界', '全世界', '全ての', '全'):
                await main.progress.callback(interaction, query)
            search.assert_not_called()

    async def test_fortune_layout(self):
        from fun_features import fortune_embed
        embed = fortune_embed('大吉', '今日はいい調子だぜ！')
        self.assertIn('大吉', embed.description)
        self.assertEqual(embed.fields[1].value.removesuffix('\n\u200b'), '今日はいい調子だぜ！')
        self.assertEqual(embed.description, '## 【大吉】')
        self.assertEqual(len(embed.fields),2)
        from fun_features import LUCKY_PROGRESS
        self.assertEqual(embed.fields[0].name, '【ラッキープログレス】')
        self.assertIn(embed.fields[0].value.removesuffix('\n\u200b'), LUCKY_PROGRESS)

    async def test_lucky_progress_includes_relink_exclusives_once(self):
        from fun_features import LUCKY_PROGRESS, fortune_embed
        from progress import progressData
        from unittest.mock import patch
        self.assertEqual(set(LUCKY_PROGRESS), {person['progressName'] for person in progressData})
        self.assertEqual(len(LUCKY_PROGRESS), len(set(LUCKY_PROGRESS)))
        for name in ('久遠空', 'シンシア', 'ヒメガミノミコト', 'ナクル・クルルシファー'):
            self.assertIn(name, LUCKY_PROGRESS)
            with patch('fun_features.random.choice', return_value=name) as choose:
                embed = fortune_embed('凶', 'ひと息つこうぜ！')
            choose.assert_called_once_with(LUCKY_PROGRESS)
            self.assertEqual(embed.fields[0].value.removesuffix('\n\u200b'), name)

    async def test_battle_and_equipment_commands_are_removed(self):
        from main import client
        self.assertIsNone(client.tree.get_command('エクシーズバトル'))
        self.assertIsNone(client.tree.get_command('装備'))
        self.assertFalse(hasattr(client,'battle_store'))
        from command_help import command_help
        self.assertNotIn('/エクシーズバトル', str(command_help(True).to_dict()))
        self.assertNotIn('/装備', str(command_help(True).to_dict()))
