import asyncio
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from contextlib import contextmanager
import discord
from command_history import CommandHistory, CommandHistoryStore, command_record

class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_interaction_handler_saves_fortune(self):
        import main
        interaction = self.interaction()
        interaction.data = {'name': 'おみくじ', 'options': []}
        store = SimpleNamespace(url='test', save=Mock())
        history = CommandHistory(store)
        with patch.object(main.client, 'command_history', history):
            await main.client.on_interaction(interaction)
            await history.close()
        store.save.assert_called_once()
        self.assertEqual(store.save.call_args.args[0][6], 'おみくじ')

    def interaction(self):
        return SimpleNamespace(id=123, created_at=datetime.now(timezone.utc), user=SimpleNamespace(id=7), guild_id=8,
            channel_id=9, type=discord.InteractionType.application_command,
            data={'name':'季節通知','options':[{'name':'行事登録','type':1,'options':[{'name':'行事名','type':3,'value':"test'); DROP TABLE x; --"}]}]},
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))

    async def test_records_nested_options_and_not_messages_or_autocomplete(self):
        interaction = self.interaction()
        record = command_record(interaction)
        self.assertEqual(record[6], '季節通知 行事登録')
        self.assertIn('DROP TABLE', json.loads(record[7])['行事名'])
        store = SimpleNamespace(url='test', save=Mock())
        history = CommandHistory(store)
        history.observe(interaction)
        await history.close()
        store.save.assert_called_once_with(record)
        interaction.type = discord.InteractionType.autocomplete
        history.observe(interaction)
        self.assertFalse(history.tasks)

    async def test_db_parameters_and_retention(self):
        store = CommandHistoryStore('test')
        connection = MagicMock()
        @contextmanager
        def connect():
            yield connection
        store.connect = connect
        record = command_record(self.interaction())
        store.save(record)
        sql, params = connection.execute.call_args_list[0].args
        self.assertNotIn('DROP TABLE', sql)
        self.assertEqual(params, record)
        self.assertIn('30 days', connection.execute.call_args_list[1].args[0])

    async def test_history_command_is_removed_but_recording_remains(self):
        from main import client
        self.assertIsNone(client.tree.get_command('コマンド履歴'))
        self.assertIsInstance(client.command_history, CommandHistory)

    async def test_failed_storage_does_not_propagate(self):
        history = CommandHistory(SimpleNamespace(url='test', save=Mock(side_effect=RuntimeError('private'))))
        history.observe(self.interaction())
        await history.close()
