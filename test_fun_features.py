import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import asyncio
from fun_features import parse_duration, TimerManager, FeedbackView, MoodMeter


class DurationTests(unittest.TestCase):
    def test_mood_changes_bounds_and_channel_isolation(self):
        meter = MoodMeter()
        meter.update(1, "cushion")
        meter.update(1, "cushion")
        self.assertEqual(meter.status(1), "ドヤ顔モード")
        self.assertEqual(meter.values(2), (50, 0))
        for _ in range(10):
            meter.update(1, "what")
        self.assertEqual(meter.values(1), (0, 100))
        self.assertEqual(meter.status(1), "空回り気味")
        for _ in range(30):
            meter.update(1, "cushion")
        self.assertEqual(meter.values(1), (100, 0))
    def test_units_and_bounds(self):
        self.assertEqual(parse_duration("1時間30分"), 5400)
        self.assertEqual(parse_duration("10m"), 600)
        self.assertEqual(parse_duration("24時間"), 86400)
        for invalid in ("0秒", "25時間", "10", "-1分", "10分abc"):
            with self.assertRaises(ValueError):
                parse_duration(invalid)


class TimerTests(unittest.IsolatedAsyncioTestCase):
    async def test_button_cooldown_does_not_change_mood(self):
        view = FeedbackView()
        interaction = SimpleNamespace(user=SimpleNamespace(id=1), channel_id=10, response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await view.respond(interaction, ["座布団いただき！"], "cushion")
        self.assertEqual(view.mood.values(10), (65, 0))
        await view.respond(interaction, ["座布団いただき！"], "cushion")
        self.assertEqual(view.mood.values(10), (65, 0))
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_mood_restore_and_failed_save_rollback(self):
        view = FeedbackView()
        from unittest.mock import Mock
        view.store = SimpleNamespace(load=Mock(return_value=[(10, 80, 20)]),
                                     get=Mock(return_value=None), save=Mock(side_effect=RuntimeError("secret URL")))
        await view.restore_mood()
        self.assertEqual(view.mood.values(10), (80, 20))
        interaction = SimpleNamespace(user=SimpleNamespace(id=1), channel_id=10,
                                      response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await view.respond(interaction, ["座布団！"], "cushion")
        self.assertEqual(view.mood.values(10), (80, 20))
        self.assertNotIn("secret", interaction.followup.send.call_args.args[0])

    async def test_saved_mood_survives_view_recreation(self):
        from unittest.mock import Mock
        data = {}
        store = SimpleNamespace(load=lambda: [(key, *value) for key, value in data.items()],
                                get=lambda key: data.get(key), save=lambda key, *values: data.update({key: values}))
        first = FeedbackView()
        first.store = store
        interaction = SimpleNamespace(user=SimpleNamespace(id=1), channel_id=10,
                                      response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await first.respond(interaction, ["座布団！"], "cushion")
        second = FeedbackView()
        second.store = store
        await second.restore_mood()
        self.assertEqual(second.mood.values(10), (65, 0))
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
        view = FeedbackView()
        self.assertTrue(view.is_persistent())
        self.assertEqual([item.label for item in view.children], ["そうだよ", "違う", "何言ってんだ", "座布団一枚"])


if __name__ == "__main__":
    unittest.main()
