import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from reminders import parse_schedule, ReminderScheduler, ReminderStore, JST, next_occurrence
import sys
import asyncio


class ScheduleTests(unittest.TestCase):
    def test_daily_and_weekly_skip_missed_runs_at_same_local_time(self):
        first = datetime(2026, 10, 16, 21, tzinfo=JST)
        now = datetime(2026, 10, 20, 22, tzinfo=JST)
        self.assertEqual(next_occurrence(first, "daily", now=now).astimezone(JST), datetime(2026, 10, 21, 21, tzinfo=JST))
        self.assertEqual(next_occurrence(first, "weekly", now=now).astimezone(JST), datetime(2026, 10, 23, 21, tzinfo=JST))
        self.assertIsNone(next_occurrence(first, "none", now=now))

    def test_month_end_does_not_drift_and_handles_leap_year(self):
        january = datetime(2027, 1, 31, 21, tzinfo=JST)
        february = next_occurrence(january, "monthly", 31, now=january)
        self.assertEqual(february.astimezone(JST), datetime(2027, 2, 28, 21, tzinfo=JST))
        march = next_occurrence(february, "monthly", 31, now=february)
        self.assertEqual(march.astimezone(JST), datetime(2027, 3, 31, 21, tzinfo=JST))
        leap = datetime(2028, 1, 31, 21, tzinfo=JST)
        self.assertEqual(next_occurrence(leap, "monthly", 31, now=leap).astimezone(JST).day, 29)

    def test_long_downtime_skips_to_future_month_and_year(self):
        first = datetime(2026, 12, 31, 21, tzinfo=JST)
        now = datetime(2028, 2, 29, 22, tzinfo=JST)
        self.assertEqual(next_occurrence(first, "monthly", 31, now=now).astimezone(JST), datetime(2028, 3, 31, 21, tzinfo=JST))

    def test_repeat_completion_reschedules_and_single_completion_finishes(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        due = datetime(2026, 10, 16, 21, tzinfo=JST)
        next_due = datetime(2026, 10, 17, 21, tzinfo=JST)
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=Mock(return_value=connection))}):
            store = ReminderStore("postgresql://test-only")
            connection.execute.return_value.fetchone.return_value = (due, "daily", 16)
            with patch("reminders.next_occurrence", return_value=next_due):
                store.finish(42, True)
            self.assertIn("status='pending'", connection.execute.call_args.args[0])
            self.assertIn("attempts=0", connection.execute.call_args.args[0])
            self.assertEqual(connection.execute.call_args.args[1], (next_due, 42))
            connection.execute.return_value.fetchone.return_value = (due, "none", 16)
            store.finish(42, True)
            self.assertIn("status='sent'", connection.execute.call_args.args[0])
            connection.execute.return_value.fetchone.return_value = None
            with patch("reminders.next_occurrence") as next_time:
                store.finish(42, True)
                next_time.assert_not_called()

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


class SchedulerWaitTests(unittest.IsolatedAsyncioTestCase):
    async def run_once(self, due=None, error=None, signal_during_read=False):
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        store = SimpleNamespace(claim_due=Mock(return_value=[]), next_wake_at=Mock(return_value=due))
        scheduler = ReminderScheduler(store, clock=lambda: now)
        if error:
            store.next_wake_at.side_effect = error
        elif signal_during_read:
            # The mutation signal can arrive while the read is in flight.
            async def read(_):
                scheduler.notify_changed()
                return due
        bot = SimpleNamespace(wait_until_ready=AsyncMock(), is_closed=Mock(side_effect=[False, True]))
        scheduler.wait_for_change = AsyncMock()
        if signal_during_read:
            scheduler.deliver_due = AsyncMock()
            with patch('reminders.asyncio.to_thread', side_effect=read):
                await scheduler.run(bot)
        else:
            await scheduler.run(bot)
        return scheduler, store

    async def test_no_minute_poll_and_future_deadline(self):
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        due = now.replace(hour=2)
        scheduler, store = await self.run_once(due)
        scheduler.wait_for_change.assert_awaited_once_with(7200)
        store.claim_due.assert_called_once()
        store.next_wake_at.assert_called_once()
        self.assertEqual(scheduler.next_check_at, due)

    async def test_empty_queue_reconciles_sparsely_and_db_failure_retries(self):
        scheduler, _ = await self.run_once()
        scheduler.wait_for_change.assert_awaited_once_with(21600)
        scheduler, _ = await self.run_once(error=RuntimeError('offline'))
        scheduler.wait_for_change.assert_awaited_once_with(300)
        self.assertFalse(scheduler.last_check_ok)

    async def test_mutation_signal_during_read_is_not_lost(self):
        scheduler, _ = await self.run_once(signal_during_read=True)
        self.assertTrue(scheduler.changed.is_set())

    async def test_change_wakes_wait_and_shutdown_cancels_task(self):
        scheduler = ReminderScheduler(SimpleNamespace(url='test'))
        task = asyncio.create_task(scheduler.wait_for_change(21600))
        await asyncio.sleep(0)
        scheduler.notify_changed()
        await asyncio.wait_for(task, timeout=1)
        scheduler.changed.clear()
        scheduler.task = asyncio.create_task(scheduler.wait_for_change(21600))
        await asyncio.sleep(0)
        await scheduler.close()
        self.assertIsNone(scheduler.task)

    def test_next_wake_covers_future_pending_and_processing_lease(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        due = datetime(2026, 10, 15, tzinfo=timezone.utc)
        connection.execute.return_value.fetchone.return_value = (due,)
        with patch.dict(sys.modules, {'psycopg': SimpleNamespace(connect=Mock(return_value=connection))}):
            self.assertEqual(ReminderStore('postgresql://test-only').next_wake_at(), due)
        sql = connection.execute.call_args.args[0]
        self.assertIn('MIN(wake_at)', sql)
        self.assertIn("status='pending'", sql)
        self.assertIn('lease_until', sql)

    async def test_registration_and_cancellation_wake_running_scheduler(self):
        import main
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()),
                                      guild_id=1, channel_id=2, user=SimpleNamespace(id=3))
        store = SimpleNamespace(add=Mock(return_value=42), cancel=Mock(return_value=True))
        scheduler = SimpleNamespace(notify_changed=Mock())
        due = datetime(2026, 10, 16, tzinfo=timezone.utc)
        with patch.object(main.client, 'reminder_store', store), patch.object(main.client, 'reminders', scheduler), patch('main.parse_schedule', return_value=due):
            await main.schedule_reminder.callback(interaction, '明日21時', '集合')
            scheduler.notify_changed.assert_called_once()
            await main.cancel_reminder.callback(interaction, 42)
            self.assertEqual(scheduler.notify_changed.call_count, 2)
            store.cancel.return_value = False
            await main.cancel_reminder.callback(interaction, 42)
            self.assertEqual(scheduler.notify_changed.call_count, 2)
