import unittest
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
from health_check import HealthCheck


class HealthTests(unittest.IsolatedAsyncioTestCase):
    def bot(self):
        generate = AsyncMock(return_value=SimpleNamespace(text="OK"))
        return SimpleNamespace(
            george_chat=SimpleNamespace(client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))), model="test-model"),
            seasonal_store=SimpleNamespace(url="secret-db-url", ping=Mock(return_value=True)),
            is_ready=lambda: True)


    async def test_checks_cached_and_no_credentials_in_report(self):
        bot = self.bot()
        health = HealthCheck()
        await health.report(bot)
        report = await health.report(bot)
        bot.george_chat.client.aio.models.generate_content.assert_awaited_once()
        bot.seasonal_store.ping.assert_called_once()
        self.assertNotIn("secret-db-url", str(report.to_dict()))
        self.assertNotIn("予定通知", str(report.to_dict()))

    async def test_unconfigured_and_stopped_are_distinct(self):
        bot = self.bot()
        bot.george_chat.client = None
        bot.seasonal_store.url = ""
        report = await HealthCheck().report(bot)
        text = str(report.to_dict())
        self.assertIn("GEMINI_API_KEY", text)
        self.assertIn("季節通知・コレクションは利用不可", text)
        bot.seasonal_store.ping.assert_not_called()

    async def test_database_error_is_redacted(self):
        bot = self.bot()
        bot.seasonal_store.ping.side_effect = RuntimeError("secret-password")
        report = await HealthCheck().report(bot)
        self.assertNotIn("secret-password", str(report.to_dict()))
        self.assertIn("接続テスト失敗", str(report.to_dict()))


if __name__ == "__main__":
    unittest.main()
