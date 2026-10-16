import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from command_help import command_help, HELP_CATEGORIES


class HelpTests(unittest.TestCase):
    def test_all_uploaded_command_and_option_names_are_lowercase(self):
        from main import client
        def check(payload):
            name = payload['name']
            self.assertEqual(name, name.lower(), name)
            self.assertTrue(1 <= len(name) <= 32, name)
            for option in payload.get('options', []):
                check(option)
        for command in client.tree.get_commands():
            check(command.to_dict(client.tree))

    def test_every_registered_command_has_a_help_entry(self):
        from main import client
        text = '\n'.join(str(command_help(True, key).to_dict()) for key in HELP_CATEGORIES)
        for command in client.tree.walk_commands():
            self.assertIn('/' + command.qualified_name, text)

    def test_category_views_fit_discord_limits_and_explain_dm_scope(self):
        for in_guild in (True, False):
            for key in HELP_CATEGORIES:
                embed = command_help(in_guild, key)
                self.assertLessEqual(len(embed), 6000)
                self.assertLessEqual(len(embed.fields), 25)
                self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
                if not in_guild:
                    self.assertIn('サーバー専用', str(embed.to_dict()))
        overview = str(command_help(True).to_dict())
        self.assertNotIn('/記憶削除', overview)
        self.assertEqual(len(command_help(True).fields), 4)
        for field in command_help(True).fields:
            self.assertIn('詳しく：`/ヘルプ 分類:', field.value)
            self.assertGreater(len(field.value.splitlines()[0]), 10)
        gacha = str(command_help(True, 'gacha').to_dict())
        self.assertIn('/所持カード', gacha)
        self.assertIn('両作品合わせて1人1枚', gacha)
        self.assertNotIn('/予定取消', gacha)


class HelpCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_and_selected_category_are_private(self):
        from main import show_help
        interaction = SimpleNamespace(guild_id=123, response=SimpleNamespace(send_message=AsyncMock()))
        await show_help.callback(interaction)
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        await show_help.callback(interaction, 'gacha')
        embed = interaction.response.send_message.call_args.kwargs['embed']
        self.assertIn('ガチャ・コレクション', embed.title)
