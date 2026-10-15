import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from reminders import parse_schedule, ReminderScheduler, ReminderStore, JST
import sys


class ScheduleTests(unittest.TestCase):
    def test_database_scope_and_durable_job_claim(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.rowcount = 1
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=Mock(return_value=connection))}):
            store = ReminderStore("postgresql://test-only")
            self.assertTrue(store.cancel(10, 20, 30))
            self.assertEqual(connection.execute.call_args.args[1], (30, 10, 20))
            store.claim_due()
            sql = connection.execute.call_args.args[0]
            self.assertIn("FOR UPDATE SKIP LOCKED", sql)
            self.assertIn("lease_until<NOW()", sql)
            self.assertIn("attempts<5", sql)

    def test_japan_time_and_relative_days(self):
        now = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(parse_schedule("明日21時", now), datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(parse_schedule("明後日9時15分", now).astimezone(JST).day, 17)
        self.assertEqual(parse_schedule("2026-10-16 21:30", now).astimezone(JST).minute, 30)
        for invalid in ("今日9時", "明日25時", "2026-02-30 12:00", "いつか", "2028-01-01 00:00"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_schedule(invalid, now)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def objects(self):
        row = (42, 1, 2, 3, datetime(2026, 10, 15, tzinfo=timezone.utc), "集合 @everyone")
        store = SimpleNamespace(claim_due=Mock(return_value=[row]), active=Mock(return_value=True), finish=Mock())
        channel = SimpleNamespace(guild=SimpleNamespace(id=1), send=AsyncMock())
        bot = SimpleNamespace(get_channel=Mock(return_value=channel), fetch_channel=AsyncMock())
        return store, channel, bot

    async def test_persisted_due_job_delivers_in_original_channel(self):
        store, channel, bot = self.objects()
        await ReminderScheduler(store).deliver_due(bot)
        channel.send.assert_awaited_once()
        mentions = channel.send.call_args.kwargs["allowed_mentions"]
        self.assertEqual(mentions.users[0].id, 3)
        self.assertFalse(mentions.everyone)
        store.finish.assert_called_once_with(42, True)

    async def test_cancelled_and_wrong_guild_do_not_send(self):
        store, channel, bot = self.objects()
        store.active.return_value = False
        await ReminderScheduler(store).deliver_due(bot)
        channel.send.assert_not_awaited()
        channel.guild.id = 99
        await ReminderScheduler(store).deliver_due(bot)
        channel.send.assert_not_awaited()
        store.finish.assert_called_once_with(42, False)

    async def test_failed_delivery_is_not_marked_sent(self):
        store, channel, bot = self.objects()
        channel.send.side_effect = RuntimeError("test")
        await ReminderScheduler(store).deliver_due(bot)
        store.finish.assert_called_once_with(42, False)
