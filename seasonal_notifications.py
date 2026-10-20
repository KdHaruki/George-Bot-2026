import asyncio
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

import discord
from registered_memory import MemoryStore, MemoryUnavailable
from seasonal_calendar import HolidayCalendar, events_for, JST


def event_header(names):
    shown = names[:10]
    return "・".join(shown) + (f" ほか{len(names) - 10}件" if len(names) > 10 else "")


class SeasonalStore(MemoryStore):
    def toggle(self, guild_id, channel_id, can_send):
        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f'george-seasonal-toggle:{guild_id}',))
            row = connection.execute('SELECT enabled FROM george_seasonal_settings WHERE guild_id=%s FOR UPDATE', (guild_id,)).fetchone()
            if row and row[0]:
                connection.execute('UPDATE george_seasonal_settings SET enabled=FALSE WHERE guild_id=%s', (guild_id,))
                return False
            if not can_send:
                raise ValueError('このチャンネルへの閲覧・送信権限をジョージに付けてくれ！')
            connection.execute('''INSERT INTO george_seasonal_settings VALUES (%s,%s,TRUE)
                ON CONFLICT(guild_id) DO UPDATE SET channel_id=EXCLUDED.channel_id,enabled=TRUE''', (guild_id, channel_id))
            return True

    @contextmanager
    def connect(self):
        try:
            with super().connect() as connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS george_seasonal_settings (
                    guild_id BIGINT PRIMARY KEY, channel_id BIGINT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE)""")
                connection.execute("""CREATE TABLE IF NOT EXISTS george_seasonal_events (
                    guild_id BIGINT NOT NULL, name TEXT NOT NULL, month INTEGER, day INTEGER,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE, PRIMARY KEY(guild_id,name))""")
                connection.execute("""CREATE TABLE IF NOT EXISTS george_seasonal_posts (
                    guild_id BIGINT NOT NULL, post_date DATE NOT NULL, channel_id BIGINT NOT NULL,
                    status TEXT NOT NULL, lease_until TIMESTAMPTZ, message_id BIGINT,
                    PRIMARY KEY(guild_id,post_date))""")
                connection.execute("""CREATE TABLE IF NOT EXISTS george_holiday_cache (
                    id INTEGER PRIMARY KEY, data JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
                yield connection
        except MemoryUnavailable:
            raise MemoryUnavailable("季節通知の保存先を利用できなかったぜ。管理者にDATABASE_URLを確認してもらってくれ。") from None

    def configure(self, guild_id, channel_id):
        with self.connect() as connection:
            connection.execute("""INSERT INTO george_seasonal_settings VALUES (%s,%s,TRUE)
                ON CONFLICT(guild_id) DO UPDATE SET channel_id=EXCLUDED.channel_id, enabled=TRUE""", (guild_id, channel_id))

    def stop(self, guild_id):
        with self.connect() as connection:
            connection.execute("UPDATE george_seasonal_settings SET enabled=FALSE WHERE guild_id=%s", (guild_id,))

    def settings(self, guild_id=None):
        with self.connect() as connection:
            if guild_id is None:
                return connection.execute("SELECT guild_id,channel_id,enabled FROM george_seasonal_settings WHERE enabled=TRUE").fetchall()
            return connection.execute("SELECT guild_id,channel_id,enabled FROM george_seasonal_settings WHERE guild_id=%s", (guild_id,)).fetchone()

    def events(self, guild_id):
        with self.connect() as connection:
            return connection.execute("SELECT name,month,day,enabled FROM george_seasonal_events WHERE guild_id=%s ORDER BY month,day,name", (guild_id,)).fetchall()

    def load_calendar(self):
        with self.connect() as connection:
            row = connection.execute("SELECT data FROM george_holiday_cache WHERE id=1").fetchone()
            return row[0] if row else {}

    def save_calendar(self, holidays):
        with self.connect() as connection:
            connection.execute("INSERT INTO george_holiday_cache VALUES (1,%s::jsonb,NOW()) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data,updated_at=NOW()", (json.dumps(holidays, ensure_ascii=False),))

    def claim(self, guild_id, channel_id, day):
        with self.connect() as connection:
            row = connection.execute("""INSERT INTO george_seasonal_posts (guild_id,post_date,channel_id,status,lease_until)
                VALUES (%s,%s,%s,'preparing',NOW()+INTERVAL '5 minutes')
                ON CONFLICT(guild_id,post_date) DO UPDATE SET channel_id=EXCLUDED.channel_id,
                lease_until=EXCLUDED.lease_until WHERE george_seasonal_posts.status='preparing'
                AND george_seasonal_posts.lease_until<NOW() RETURNING guild_id""", (guild_id, day, channel_id)).fetchone()
            return row is not None

    def begin_send(self, guild_id, channel_id, day):
        with self.connect() as connection:
            return connection.execute("""UPDATE george_seasonal_posts p SET status='sending'
                WHERE p.guild_id=%s AND p.post_date=%s AND p.channel_id=%s AND p.status='preparing'
                AND EXISTS (SELECT 1 FROM george_seasonal_settings s WHERE s.guild_id=p.guild_id
                AND s.enabled=TRUE AND s.channel_id=p.channel_id)""", (guild_id, day, channel_id)).rowcount > 0

    def finish(self, guild_id, day, message_id=None):
        with self.connect() as connection:
            connection.execute("UPDATE george_seasonal_posts SET status=%s,message_id=%s WHERE guild_id=%s AND post_date=%s AND status='sending'", ("sent" if message_id else "send_failed", message_id, guild_id, day))


class SeasonalScheduler:
    def __init__(self, store, clock=None):
        self.store = store
        self.calendar = HolidayCalendar(store)
        self.task = None
        self.last_check_ok = None
        self.last_check_at = None
        self.last_delivery_failed = False
        self.checked_day = None
        self.delivered = set()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.changed = asyncio.Event()
        self.retry_needed = False

    def notify_changed(self):
        self.changed.set()

    def wait_seconds(self):
        now = self.clock().astimezone(JST)
        tomorrow = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if tomorrow <= now:
            tomorrow += timedelta(days=1)
        # Reconcile changes from another process at most every six hours.
        delay = min(6 * 3600, (tomorrow - now).total_seconds())
        if self.retry_needed or self.last_check_ok is False:
            delay = min(delay, 3600)
        return max(0.5, delay)

    async def wait_for_change(self, seconds):
        try:
            await asyncio.wait_for(self.changed.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def start(self, bot):
        if self.store.url and self.task is None:
            self.task = asyncio.create_task(self.run(bot))

    async def run(self, bot):
        await bot.wait_until_ready()
        while not bot.is_closed():
            self.changed.clear()
            try:
                await self.tick(bot)
                self.last_check_ok = True
            except Exception as exc:
                self.last_check_ok = False
                logging.warning("Seasonal check failed: type=%s", type(exc).__name__)
            self.last_check_at = datetime.now(timezone.utc)
            await self.wait_for_change(self.wait_seconds())

    async def tick(self, bot, now=None):
        self.last_delivery_failed = False
        self.retry_needed = False
        now = (now or self.clock()).astimezone(JST)
        if now.hour < 10:
            return
        day = now.date()
        if self.checked_day != day:
            self.checked_day, self.delivered = day, set()
        settings = await asyncio.to_thread(self.store.settings)
        if not settings:
            return
        await self.calendar.refresh(now)
        if not self.calendar.covers(day):
            self.retry_needed = True
            logging.warning("Seasonal posts skipped: holiday year is unavailable")
            return
        for guild_id, channel_id, _ in settings:
            if guild_id in self.delivered:
                continue
            names = events_for(day, self.calendar.holidays, await asyncio.to_thread(self.store.events, guild_id))
            if not names:
                continue
            try:
                if not await asyncio.to_thread(self.store.claim, guild_id, channel_id, day):
                    self.retry_needed = True
                    continue
                channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                if getattr(getattr(channel, "guild", None), "id", None) != guild_id:
                    raise ValueError("Seasonal channel mismatch")
                try:
                    comment = await bot.george_chat.seasonal_comment(names)
                except Exception:
                    comment = "みんな、今日は「" + event_header(names) + "」だぜ！ 無理せず、いい一日を過ごしてくれよな！"
                # A slow generation must not post yesterday's greeting after midnight.
                if self.clock().astimezone(JST).date() != day:
                    continue
                if not await asyncio.to_thread(self.store.begin_send, guild_id, channel_id, day):
                    continue
                # Mark before sending: uncertain sends are not retried, to avoid duplicate greetings.
                self.delivered.add(guild_id)
                try:
                    message = await channel.send("🎉 " + event_header(names) + "\n" + comment,
                                                 allowed_mentions=discord.AllowedMentions.none())
                except Exception:
                    await asyncio.to_thread(self.store.finish, guild_id, day)
                    raise
                await asyncio.to_thread(self.store.finish, guild_id, day, message.id)
            except Exception as exc:
                self.last_delivery_failed = True
                self.retry_needed = True
                logging.warning("Seasonal delivery failed: type=%s", type(exc).__name__)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
