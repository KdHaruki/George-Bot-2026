import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import main


class MemoryCommandTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, manager):
        return SimpleNamespace(permissions=SimpleNamespace(manage_guild=manager), guild_id=123,
                               guild=SimpleNamespace(id=123), response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()))

    async def test_non_manager_cannot_register_or_delete(self):
        store = SimpleNamespace(save=Mock(), delete=Mock())
        with patch.object(main.client, "memories", store):
            await main.register_memory.callback(self.interaction(False), "設定", "内容")
            await main.delete_memory.callback(self.interaction(False), "設定")
        store.save.assert_not_called()
        store.delete.assert_not_called()

    async def test_registration_is_shared_and_server_scoped(self):
        store = SimpleNamespace(save=Mock())
        with patch.object(main.client, "memories", store), patch.object(main.client, "clear_server_context") as clear:
            interaction = self.interaction(True)
            await main.register_memory.callback(interaction, "設定", "内容")
        store.save.assert_called_once_with(123, 0, "設定", "内容")
        clear.assert_called_once_with(interaction.guild)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)


if __name__ == "__main__":
    unittest.main()
