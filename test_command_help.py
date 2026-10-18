import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import discord

from command_help import command_help


class HelpTests(unittest.TestCase):
    def test_dm_archive_is_removed_but_dm_conversation_is_available(self):
        from main import client
        self.assertIsNone(client.tree.get_command('dm履歴'))
        self.assertFalse(hasattr(client, 'dm_store'))
        self.assertIn('DMならそのまま', str(command_help(False).to_dict()))

    def test_progress_command_uses_japanese_name(self):
        from main import client
        self.assertIsNotNone(client.tree.get_command('プログレス'))
        self.assertIsNone(client.tree.get_command('progress'))

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
        text = str(command_help(True).to_dict())
        for command in client.tree.walk_commands():
            if command.qualified_name.split()[0] in ('季節通知', '状態', 'ヘルプ'):
                continue  # Administrator seasonal commands are intentionally outside help.
            self.assertIn('/' + command.qualified_name, text)

    def test_help_has_spaced_headings_and_no_categories(self):
        from main import show_help
        self.assertEqual(show_help.parameters, [])
        for in_guild in (True, False):
            embed = command_help(in_guild)
            self.assertLessEqual(len(embed), 6000)
            self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
            self.assertEqual([field.name for field in embed.fields], ['【ジョージの機能一覧】', '【スラッシュコマンド】', '【メンション】'])
            self.assertTrue(embed.fields[0].value.endswith('\n\u200b'))
            self.assertTrue(embed.fields[1].value.endswith('\n\u200b'))
            self.assertNotIn('分類:', str(embed.to_dict()))


class HelpCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_mention_and_dm_help_send_same_embed_without_ai(self):
        import main
        bot_user = SimpleNamespace(id=99)
        fake = SimpleNamespace(user=bot_user, george_chat=SimpleNamespace(reply=AsyncMock()),
                               ambient=SimpleNamespace(note_reply=Mock()))
        for in_guild in (True, False):
            channel = Mock(spec=discord.DMChannel) if not in_guild else SimpleNamespace()
            channel.id, channel.send = 10, AsyncMock()
            message = SimpleNamespace(author=SimpleNamespace(bot=False), guild=SimpleNamespace(id=1) if in_guild else None,
                                      mentions=[bot_user] if in_guild else [], content='<@99> ヘルプ' if in_guild else 'ヘルプ', channel=channel)
            with patch.object(main, 'client', fake), patch('main.random.random', return_value=1), patch('main.george_reply_target', AsyncMock(return_value=None)):
                await main.on_message(message)
            kwargs = channel.send.call_args.kwargs
            self.assertEqual(kwargs['embed'].to_dict(), command_help(in_guild).to_dict())
            self.assertNotIn('ephemeral', kwargs)
        fake.george_chat.reply.assert_not_awaited()

    async def test_default_and_selected_category_are_private(self):
        from main import show_help
        interaction = SimpleNamespace(guild_id=123, response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch('main.help_embed', AsyncMock(return_value=command_help(True))):
            await show_help.callback(interaction)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        self.assertEqual(interaction.followup.send.call_args.kwargs['embed'].to_dict(), command_help(True).to_dict())
