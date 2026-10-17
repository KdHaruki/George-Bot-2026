import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import discord

from command_help import command_help, HELP_CATEGORIES


class HelpTests(unittest.TestCase):
    def test_dm_archive_is_removed_but_dm_conversation_is_available(self):
        from main import client
        self.assertIsNone(client.tree.get_command('dm履歴'))
        self.assertFalse(hasattr(client, 'dm_store'))
        self.assertIn('DMではそのまま', str(command_help(False, 'chat').to_dict()))

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
        text = '\n'.join(str(command_help(True, key).to_dict()) for key in HELP_CATEGORIES)
        for command in client.tree.walk_commands():
            if command.qualified_name.split()[0] in ('季節通知', '状態', 'ヘルプ'):
                continue  # Administrator seasonal commands are intentionally outside help.
            self.assertIn('/' + command.qualified_name, text)

    def test_category_views_fit_discord_limits_and_explain_dm_scope(self):
        for in_guild in (True, False):
            for key in HELP_CATEGORIES:
                embed = command_help(in_guild, key)
                self.assertLessEqual(len(embed), 6000)
                self.assertLessEqual(len(embed.fields), 25)
                self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
                if not in_guild and key != 'overview':
                    self.assertIn('サーバー専用', str(embed.to_dict()))
        overview = str(command_help(True).to_dict())
        self.assertNotIn('/記憶削除', overview)
        self.assertNotIn('seasonal', HELP_CATEGORIES)
        self.assertNotIn('system', HELP_CATEGORIES)
        self.assertNotIn('/未所持カード', overview)
        for example in ('/プログレス ロザリー', '/ガチャ アンジュ・ヴィエルジュ', '/ガチャ アンジュ・リリンク', '/所持カード ロザリー', '/お気に入り ロザリー'):
            self.assertIn('`' + example + '`', overview)
        embed = command_help(True)
        self.assertFalse(embed.title)
        self.assertEqual(embed.fields[0].value, '面白そうな話題にはリアクションしたり、口を挟むぜ！')
        self.assertEqual([field.name for field in embed.fields], ['【ジョージの機能一覧】', '【スラッシュコマンド】', '【DM・メンション】'])
        self.assertNotIn('> ', '\n'.join(field.value for field in embed.fields))
        self.assertIn('`/所持カード ロザリー`\nプログレス', embed.fields[1].value)
        self.assertNotIn('- ', '\n'.join(field.value for field in embed.fields))
        gacha = str(command_help(True, 'gacha').to_dict())
        self.assertIn('/所持カード', gacha)
        self.assertIn('両作品合わせて1人1枚', gacha)
        self.assertNotIn('/予定取消', gacha)


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
        interaction = SimpleNamespace(guild_id=123, response=SimpleNamespace(send_message=AsyncMock()))
        await show_help.callback(interaction)
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        await show_help.callback(interaction, 'gacha')
        embed = interaction.response.send_message.call_args.kwargs['embed']
        self.assertIn('ガチャ・コレクション', embed.title)
