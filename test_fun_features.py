import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import asyncio
from fun_features import parse_duration, TimerManager


class DurationTests(unittest.TestCase):
    def test_units_and_bounds(self):
        self.assertEqual(parse_duration("1時間30分"), 5400)
        self.assertEqual(parse_duration("10m"), 600)
        self.assertEqual(parse_duration("24時間"), 86400)
        for invalid in ("0秒", "25時間", "10", "-1分", "10分abc"):
            with self.assertRaises(ValueError):
                parse_duration(invalid)


class TimerTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_and_owner_only_cancellation(self):
        manager = TimerManager()
        channel = SimpleNamespace(id=1, send=AsyncMock())
        with patch("fun_features.asyncio.sleep", new=AsyncMock()):
            task = manager.start(channel, 10, 1, "休憩 @everyone")
            await task
        channel.send.assert_awaited_once()
        self.assertEqual(channel.send.call_args.kwargs["allowed_mentions"].users[0].id, 10)
        other = manager.start(channel, 20, 3600, "他の人")
        mine = manager.start(channel, 10, 3600, "自分")
        self.assertEqual(manager.cancel(1, 10), 1)
        self.assertIn(other, manager.tasks)
        await manager.close()
        self.assertFalse(manager.tasks)

    async def test_limits_and_buttons(self):
        manager = TimerManager()
        channel = SimpleNamespace(id=1, send=AsyncMock())
        for _ in range(3):
            manager.start(channel, 10, 3600, "待機")
        with self.assertRaises(ValueError):
            manager.start(channel, 10, 3600, "上限")
        await manager.close()


if __name__ == "__main__":
    unittest.main()
