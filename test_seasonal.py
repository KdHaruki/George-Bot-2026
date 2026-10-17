import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, MagicMock, patch
import sys
from contextlib import contextmanager

from seasonal_calendar import parse_holidays, events_for, parse_event_date, HolidayCalendar, JST
from seasonal_notifications import SeasonalScheduler, SeasonalStore


class CalendarTests(unittest.TestCase):
    def test_progress_birthdays_are_not_seasonal_events(self):
        self.assertEqual(events_for(date(2026, 11, 26), {}, []), [])
        self.assertEqual(events_for(date(2026, 12, 25), {}, []), ['クリスマス'])

    def test_seasonal_toggle_turns_on_off_and_keeps_channel_on_stop(self):
        state = [None]
        connection = Mock()
        def execute(sql, params):
            if sql.startswith('SELECT enabled'):
                return SimpleNamespace(fetchone=lambda: (state[0][1],) if state[0] else None)
            if sql.startswith('INSERT INTO george_seasonal_settings'):
                state[0] = (params[1], True)
            if sql.startswith('UPDATE george_seasonal_settings'):
                state[0] = (state[0][0], False)
            return Mock()
        connection.execute.side_effect = execute
        @contextmanager
        def connect():
            yield connection
        store = SeasonalStore('test')
        with patch.object(store, 'connect', connect):
            self.assertTrue(store.toggle(1, 10, True))
            self.assertEqual(state[0], (10, True))
            self.assertFalse(store.toggle(1, 20, False))
            self.assertEqual(state[0], (10, False))
            with self.assertRaises(ValueError):
                store.toggle(1, 20, False)
            self.assertEqual(state[0], (10, False))
            self.assertTrue(store.toggle(1, 20, True))
            self.assertEqual(state[0], (20, True))

    def test_official_csv_encoding_and_dates(self):
        data = "国民の祝日・休日月日,国民の祝日・休日名称\r\n" + "\r\n".join(f"2026/1/{day},テスト行事{day}" for day in range(1, 17)) + "\r\n2026/10/12,スポーツの日\r\n"
        parsed = parse_holidays(data.encode("cp932"))
        self.assertEqual(parsed["2026-10-12"], "スポーツの日")
        with self.assertRaises(ValueError):
            parse_holidays(b"<html>error</html>")

    def test_merge_and_guild_specific_mute(self):
        day = date(2026, 1, 1)
        calendar = {day.isoformat(): "元日"}
        self.assertEqual(events_for(day, calendar, []), ["元日"])
        overrides = [("元日", None, None, False), ("設立記念日", 1, 1, True)]
        self.assertEqual(events_for(day, calendar, overrides), ["設立記念日"])
        self.assertEqual(events_for(day, calendar, []), ["元日"])
        self.assertEqual(parse_event_date("02-29"), (2, 29))
        with self.assertRaises(ValueError):
            parse_event_date("02-30")

    def test_database_scope_and_unique_daily_claim(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=Mock(return_value=connection))}):
            store = SeasonalStore("postgresql://test-only")
            store.events(123)
            self.assertEqual(connection.execute.call_args.args[1], (123,))
            store.claim(123, 456, date(2026, 10, 31))
            query, params = connection.execute.call_args.args
            self.assertIn("ON CONFLICT(guild_id,post_date)", query)
            self.assertIn("status='preparing'", query)
            self.assertEqual(params[:2], (123, date(2026, 10, 31)))
            store.stop(123)
            self.assertEqual(connection.execute.call_args.args[1], (123,))


class SeasonalTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_until_ten_and_no_longer_polls_each_minute(self):
        scheduler, store, bot, channel, clock = self.objects(datetime(2026, 10, 31, 9, 59, tzinfo=JST))
        self.assertEqual(scheduler.wait_seconds(), 60)
        clock[0] = clock[0].replace(hour=10, minute=1)
        self.assertEqual(scheduler.wait_seconds(), 21600)
        scheduler.retry_needed = True
        self.assertEqual(scheduler.wait_seconds(), 3600)
        scheduler.notify_changed()
        await scheduler.wait_for_change(21600)

    async def test_settings_require_manager_and_preserve_guild_channel_scope(self):
        import main
        bot = main.client
        store = SimpleNamespace(toggle=Mock(return_value=True))
        command = bot.tree.get_command("季節通知").get_command("設定")
        interaction = SimpleNamespace(permissions=SimpleNamespace(manage_guild=False, administrator=False),
                                      response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()), guild_id=123, channel_id=456,
                                      channel=SimpleNamespace(), app_permissions=SimpleNamespace(view_channel=True, send_messages=True))
        with patch.object(bot, "seasonal_store", store):
            await command.callback(interaction)
            store.toggle.assert_not_called()
            interaction.permissions.manage_guild = True
            interaction.permissions.administrator = True
            await command.callback(interaction)
        store.toggle.assert_called_once_with(123, 456, True)

    async def test_custom_events_use_seasonal_group_and_removed_features_are_absent(self):
        import main
        bot = main.client
        for name in ('タイマー', 'タイマー取消', '予定', '予定一覧', '予定取消', '記憶登録', '記憶一覧', '記憶削除', '行事追加', '行事一覧', '行事削除', '行事切替'):
            self.assertIsNone(bot.tree.get_command(name))
        for attribute in ('timers', 'reminders', 'reminder_store', 'memories'):
            self.assertFalse(hasattr(bot, attribute))
        group = bot.tree.get_command('季節通知')
        self.assertIsNone(group.get_command('行事切替'))
        self.assertIsNone(group.get_command('行事一覧'))
        self.assertIsNone(group.get_command('停止'))
        store = SimpleNamespace(put_event=Mock(), delete_event=Mock(return_value=True))
        scheduler = SimpleNamespace(notify_changed=Mock())
        interaction = SimpleNamespace(permissions=SimpleNamespace(administrator=True), guild_id=123,
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(bot, 'seasonal_store', store), patch.object(bot, 'seasonal', scheduler):
            await group.get_command('行事登録').callback(interaction, '04-01', '設立記念日')
            store.put_event.assert_called_once_with(123, '設立記念日', 4, 1)
            await group.get_command('行事削除').callback(interaction, '設立記念日')
            store.delete_event.assert_called_once_with(123, '設立記念日')
        self.assertEqual(scheduler.notify_changed.call_count, 2)

    async def test_status_includes_common_and_custom_events_even_without_channel(self):
        import main
        store = SimpleNamespace(settings=Mock(return_value=None), events=Mock(return_value=[('設立記念日', 4, 1, True)]))
        interaction = SimpleNamespace(guild_id=123, permissions=SimpleNamespace(administrator=True),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        command = main.client.tree.get_command('季節通知').get_command('確認')
        with patch.object(main.client, 'seasonal_store', store):
            await command.callback(interaction)
        text = ''.join(call.args[0] for call in interaction.followup.send.call_args_list)
        self.assertIn('未設定', text)
        self.assertIn('ハロウィン', text)
        self.assertIn('4月1日 設立記念日', text)
        self.assertNotIn('ロザリーの誕生日', text)
        self.assertNotIn('｜有効', text)
        self.assertTrue(all(call.kwargs['ephemeral'] for call in interaction.followup.send.call_args_list))
        store.events.assert_called_once_with(123)

    def objects(self, current=None):
        clock = [current or datetime(2026, 10, 31, 10, 0, tzinfo=JST)]
        store = SimpleNamespace(url="test", settings=Mock(return_value=[(1, 2, True)]), events=Mock(return_value=[]),
                                claim=Mock(return_value=True), begin_send=Mock(return_value=True), finish=Mock())
        scheduler = SeasonalScheduler(store, clock=lambda: clock[0])
        scheduler.calendar = SimpleNamespace(refresh=AsyncMock(), covers=Mock(return_value=True), holidays={"2026-01-01": "元日"})
        channel = SimpleNamespace(guild=SimpleNamespace(id=1), send=AsyncMock(return_value=SimpleNamespace(id=99)))
        bot = SimpleNamespace(get_channel=Mock(return_value=channel), fetch_channel=AsyncMock(), george_chat=SimpleNamespace(seasonal_comment=AsyncMock(return_value="ハロウィンを楽しもうぜ！")))
        return scheduler, store, bot, channel, clock

    async def test_not_before_ten_and_one_post_per_day(self):
        scheduler, store, bot, channel, clock = self.objects(datetime(2026, 10, 31, 9, 59, tzinfo=JST))
        await scheduler.tick(bot)
        store.settings.assert_not_called()
        clock[0] = clock[0].replace(hour=10, minute=0)
        await scheduler.tick(bot)
        await scheduler.tick(bot)
        channel.send.assert_awaited_once()
        store.finish.assert_called_once_with(1, date(2026, 10, 31), 99)
        self.assertFalse(channel.send.call_args.kwargs["allowed_mentions"].everyone)

    async def test_restart_does_not_repost_and_ai_failure_falls_back(self):
        scheduler, store, bot, channel, clock = self.objects()
        bot.george_chat.seasonal_comment.side_effect = RuntimeError("API failed")
        await scheduler.tick(bot)
        self.assertIn("ハロウィン", channel.send.call_args.args[0])
        store.claim.return_value = False  # Simulate the persisted sent row.
        restarted = SeasonalScheduler(store, clock=lambda: clock[0])
        restarted.calendar = scheduler.calendar
        await restarted.tick(bot)
        channel.send.assert_awaited_once()

    async def test_stop_mid_generation_and_midnight_do_not_send(self):
        scheduler, store, bot, channel, clock = self.objects()
        store.begin_send.return_value = False
        await scheduler.tick(bot)
        channel.send.assert_not_awaited()
        scheduler, store, bot, channel, clock = self.objects()
        async def delayed_greeting(names):
            clock[0] += timedelta(days=1)
            return "日付が変わった"
        bot.george_chat.seasonal_comment.side_effect = delayed_greeting
        await scheduler.tick(bot)
        store.begin_send.assert_not_called()
        channel.send.assert_not_awaited()

    async def test_send_failure_does_not_repeat_and_missing_year_skips(self):
        scheduler, store, bot, channel, clock = self.objects()
        channel.send.side_effect = RuntimeError("send failed")
        await scheduler.tick(bot)
        await scheduler.tick(bot)
        channel.send.assert_awaited_once()
        store.finish.assert_called_once_with(1, date(2026, 10, 31))
        scheduler, store, bot, channel, clock = self.objects()
        scheduler.calendar.covers.return_value = False
        await scheduler.tick(bot)
        store.claim.assert_not_called()

    async def test_cached_holidays_survive_download_failure(self):
        store = SimpleNamespace(load_calendar=Mock(return_value={"2026-10-12": "スポーツの日"}), save_calendar=Mock())
        calendar = HolidayCalendar(store)
        with patch("seasonal_calendar.httpx.AsyncClient", side_effect=RuntimeError("offline")):
            await calendar.refresh(datetime(2026, 10, 12, tzinfo=JST))
        self.assertTrue(calendar.covers(date(2026, 10, 12)))
        self.assertTrue(calendar.refresh_failed)
