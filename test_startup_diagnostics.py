import os
import unittest
from unittest.mock import patch, AsyncMock, Mock
from types import SimpleNamespace

from main import start_gemini_diagnostics, MyClient


class StartupDiagnosticsTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"GEMINI_DIAGNOSTICS": "0"}), patch("main.Thread") as thread:
            self.assertIsNone(start_gemini_diagnostics())
            thread.assert_not_called()

    def test_enabled_starts_one_background_check(self):
        with patch.dict(os.environ, {"GEMINI_DIAGNOSTICS": "1"}), patch("main.Thread") as thread:
            result = start_gemini_diagnostics()
            self.assertEqual(thread.call_args.kwargs["kwargs"], {"test": True})
            self.assertTrue(thread.call_args.kwargs["daemon"])
            result.start.assert_called_once_with()


class GuildSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_once_and_register_all_commands(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            bot = MyClient()
        guild = SimpleNamespace(id=123)
        with patch.object(bot.tree, "copy_global_to") as copy, patch.object(bot.tree, "sync", new=AsyncMock(return_value=[SimpleNamespace(name="調子"), SimpleNamespace(name="おみくじ")])) as sync:
            await bot.sync_guild_commands(guild)
            await bot.sync_guild_commands(guild)
            copy.assert_called_once_with(guild=guild)
            sync.assert_awaited_once_with(guild=guild)


if __name__ == "__main__":
    unittest.main()
