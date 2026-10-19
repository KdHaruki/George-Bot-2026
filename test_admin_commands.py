import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import discord


class AdminCommandsTests(unittest.IsolatedAsyncioTestCase):
    async def test_protected_commands_reject_non_admin_before_work(self):
        from main import client
        targets = ['状態', '季節通知', '称号設定']
        for name in targets:
            command = client.tree.get_command(name)
            self.assertTrue(command.default_permissions.administrator)
            self.assertIn('（管理者用）', command.description)
            commands = list(command.commands) if name == '季節通知' else [command]
            for item in commands:
                interaction = SimpleNamespace(guild_id=123,
                    permissions=discord.Permissions(manage_guild=True),
                    response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()))
                args = {'行事登録': ['04-01', '行事'], '行事削除': ['行事']}.get(item.name, [])
                await item.callback(interaction, *args)
                interaction.response.send_message.assert_awaited_once()
                interaction.response.defer.assert_not_called()

