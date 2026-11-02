"""HTTPの稼働確認と、デプロイ時のコマンド終了待ちを検証する。"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from deployment import DeploymentState, DeploymentCommandTree
from keep_alive import app


class HealthEndpointTests(unittest.TestCase):
    def test_root_remains_available_and_readiness_endpoint_is_removed(self):
        http = app.test_client()
        self.assertEqual(http.get('/').status_code, 200)
        self.assertEqual(http.head('/').status_code, 200)
        self.assertEqual(http.get('/ready').status_code, 404)


class DeploymentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = discord.Client(intents=discord.Intents.none())
        self.bot.deployment = DeploymentState()
        self.tree = DeploymentCommandTree(self.bot)

    async def test_tracks_actual_command_until_callback_finishes(self):
        entered, release = asyncio.Event(), asyncio.Event()

        @self.tree.command(name='example')
        async def example(interaction):
            entered.set()
            await release.wait()

        interaction = SimpleNamespace(
            type=discord.InteractionType.application_command,
            data={'name': 'example', 'type': 1, 'options': []},
            guild_id=None, guild=None, command_failed=False, _state=self.bot._connection,
        )
        invocation = asyncio.create_task(self.tree._call(interaction))
        # 実際のdiscord.pyの呼出経路で、コールバック全体を待てることを確認する。
        await asyncio.wait_for(entered.wait(), timeout=1)
        self.assertIn(invocation, self.bot.deployment.tasks)
        self.bot.deployment.begin_shutdown()
        waiter = asyncio.create_task(self.bot.deployment.wait_for_commands(timeout=1))
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        release.set()
        self.assertEqual(await waiter, 0)
        await invocation
        await asyncio.sleep(0)
        self.assertFalse(self.bot.deployment.tasks)

    async def test_timeout_does_not_cancel_running_command(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def work():
            self.bot.deployment.track_command()
            entered.set()
            await release.wait()

        task = asyncio.create_task(work())
        await entered.wait()
        try:
            self.assertEqual(await self.bot.deployment.wait_for_commands(timeout=0), 1)
            self.assertFalse(task.cancelled())
            self.assertFalse(task.done())
        finally:
            release.set()
            await task

    async def test_shutdown_replies_privately_without_executing_new_command(self):
        self.bot.deployment.begin_shutdown()
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(type=discord.InteractionType.application_command, response=response)
        self.assertFalse(await self.tree.interaction_check(interaction))
        self.assertTrue(response.send_message.call_args.kwargs['ephemeral'])
        self.assertFalse(self.bot.deployment.tasks)

    async def test_shutdown_autocomplete_returns_empty_choices(self):
        self.bot.deployment.begin_shutdown()
        response = SimpleNamespace(autocomplete=AsyncMock())
        interaction = SimpleNamespace(type=discord.InteractionType.autocomplete, response=response)
        self.assertFalse(await self.tree.interaction_check(interaction))
        response.autocomplete.assert_awaited_once_with([])

    async def test_shutdown_signal_waits_before_closing_and_is_idempotent(self):
        from main import MyClient
        state = DeploymentState()
        calls = []

        async def wait():
            calls.append('wait')
            self.assertTrue(state.draining)
            return 0

        async def close():
            calls.append('close')

        bot = SimpleNamespace(deployment=state, close=close)
        bot.shutdown_for_deploy = lambda: MyClient.shutdown_for_deploy(bot)
        with patch.object(state, 'wait_for_commands', side_effect=wait):
            MyClient.request_shutdown(bot)
            first = bot._shutdown_task
            MyClient.request_shutdown(bot)
            self.assertIs(bot._shutdown_task, first)
            await first
        self.assertEqual(calls, ['wait', 'close'])
