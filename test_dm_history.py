import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from contextlib import contextmanager
import discord
from discord import app_commands
from dm_history import DMStore, archive_dm, register_dm_history


class DMTests(unittest.IsolatedAsyncioTestCase):
    async def test_application_owner_fallback(self):
        client = discord.Client(intents=discord.Intents.none())
        bot = SimpleNamespace(tree=app_commands.CommandTree(client), application_info=AsyncMock(return_value=SimpleNamespace(team=SimpleNamespace(owner_id=7))))
        store = SimpleNamespace(history=Mock(return_value=[]))
        register_dm_history(bot, store)
        interaction = SimpleNamespace(user=SimpleNamespace(id=7), response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.dict('os.environ', {'BOT_OWNER_IDS': ''}):
            await bot.tree.get_command('dm履歴').callback(interaction)
        store.history.assert_called_once_with(None, 1)
        await client.close()

    async def test_store_preserves_body_and_uses_parameterized_filters(self):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = None
        connection.execute.return_value.fetchall.return_value = []
        @contextmanager
        def connect():
            yield connection
        store = DMStore('test')
        message = SimpleNamespace(id=100, author=SimpleNamespace(id=42), created_at=datetime.now(timezone.utc), content="private ' text")
        with patch.object(store, 'connect', connect):
            self.assertTrue(store.save(message))
            self.assertIn('ON CONFLICT(message_id) DO NOTHING', connection.execute.call_args.args[0])
            self.assertEqual(connection.execute.call_args.args[1][-1], message.content)
            store.history(42, 2)
            self.assertEqual(connection.execute.call_args.args[1], (42, 42, 5))

    async def test_owner_only_and_private_full_body(self):
        client = discord.Client(intents=discord.Intents.none())
        bot = SimpleNamespace(tree=app_commands.CommandTree(client), application_info=AsyncMock())
        store = SimpleNamespace(history=Mock(return_value=[(42, 'sender', datetime.now(timezone.utc), 'x' * 2000)]))
        register_dm_history(bot, store)
        command = bot.tree.get_command('dm履歴')
        interaction = SimpleNamespace(user=SimpleNamespace(id=9), response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.dict('os.environ', {'BOT_OWNER_IDS': '1'}):
            await command.callback(interaction)
            store.history.assert_not_called()
            interaction.user.id = 1
            await command.callback(interaction, '42', 2)
            store.history.assert_called_once_with(42, 2)
            result = interaction.followup.send.call_args.kwargs
            self.assertTrue(result['ephemeral'])
            self.assertLess(len(result['embed']), 6000)
            self.assertIn(b'x' * 2000, result['files'][0].fp.getvalue())
        await client.close()

    async def test_only_incoming_dm_and_first_notice(self):
        store = SimpleNamespace(save=Mock(return_value=True))
        message = SimpleNamespace(guild=object(), author=SimpleNamespace(bot=False), channel=SimpleNamespace(send=AsyncMock()))
        await archive_dm(store, message)
        store.save.assert_not_called()
        message.guild = None
        await archive_dm(store, message)
        message.channel.send.assert_awaited_once()
        store.save.return_value = False
        await archive_dm(store, message)
        message.channel.send.assert_awaited_once()

