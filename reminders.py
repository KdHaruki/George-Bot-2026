"""Durable scheduled notifications. UTC storage, explicit Japan-time input."""
import asyncio
import logging
import re
import calendar
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import discord
from registered_memory import MemoryStore, MemoryUnavailable

JST = timezone(timedelta(hours=9))
REPEAT_LABELS = {"none": "繰り返しなし", "daily": "毎日", "weekly": "毎週", "monthly": "毎月"}


def next_occurrence(due_at, repeat, anchor_day=None, now=None):
    """Keep the original local clock/day; skip missed repeats without flooding."""
    if repeat == "none":
        return None
    if repeat not in REPEAT_LABELS:
        raise ValueError("繰り返しは、なし・毎日・毎週・毎月から選んでくれ。")
    due = due_at.astimezone(JST)
    now = (now or datetime.now(timezone.utc)).astimezone(JST)
    if repeat == "daily":
        candidate = due + timedelta(days=max(1, (now.date() - due.date()).days))
        if candidate <= now:
            candidate += timedelta(days=1)
    elif repeat == "weekly":
        candidate = due + timedelta(weeks=max(1, (now.date() - due.date()).days // 7))
        if candidate <= now:
            candidate += timedelta(weeks=1)
    else:
        day = anchor_day or due.day
        if not 1 <= day <= 31:
            raise ValueError("Invalid monthly anchor day")
        offset = max(1, (now.year - due.year) * 12 + now.month - due.month)
        def month_at(delta):
            index = due.year * 12 + due.month - 1 + delta
            year, month_index = divmod(index, 12)
            month = month_index + 1
            return due.replace(year=year, month=month, day=min(day, calendar.monthrange(year, month)[1]))
        candidate = month_at(offset)
        if candidate <= now:
            candidate = month_at(offset + 1)
    return candidate.astimezone(timezone.utc)


def parse_schedule(text, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(JST)
    text = text.strip()
    relative = re.fullmatch(r"(今日|明日|明後日)\s*(\d{1,2})(?::(\d{2})|時(?:(\d{1,2})分)?)", text)
    try:
        if relative:
            day, hour, minute, jp_minute = relative.groups()
            date = now.date() + timedelta(days={"今日": 0, "明日": 1, "明後日": 2}[day])
            scheduled = datetime(date.year, date.month, date.day, int(hour), int(minute or jp_minute or 0), tzinfo=JST)
        else:
            scheduled = datetime.strptime(text.replace("/", "-"), "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    except ValueError:
        raise ValueError("日時は「明日21時」「明日21:30」「2026-10-16 21:00」の形式で頼むぜ。日本時間で受け付けるぞ！") from None
    if not now < scheduled <= now + timedelta(days=365):
        raise ValueError("予定は今より後、365日以内で頼むぜ！")
    return scheduled.astimezone(timezone.utc)


class ReminderStore(MemoryStore):
    @contextmanager
    def connect(self):
        try:
            with super().connect() as connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS george_reminders (
                    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
                    due_at TIMESTAMPTZ NOT NULL, content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    lease_until TIMESTAMPTZ)""")
                connection.execute("CREATE INDEX IF NOT EXISTS george_reminders_due_idx ON george_reminders (status, due_at)")
                connection.execute("ALTER TABLE george_reminders ADD COLUMN IF NOT EXISTS repeat_kind TEXT NOT NULL DEFAULT 'none'")
                connection.execute("ALTER TABLE george_reminders ADD COLUMN IF NOT EXISTS anchor_day INTEGER")
                yield connection
        except MemoryUnavailable:
            raise MemoryUnavailable("予定の保存先を利用できなかったぜ。管理者にDATABASE_URLを確認してもらってくれ。") from None

    def add(self, guild_id, channel_id, user_id, due_at, content, repeat="none"):
        content = content.strip()
        if not 1 <= len(content) <= 300:
            raise ValueError("予定の内容は1〜300文字で頼むぜ。")
        if repeat not in REPEAT_LABELS:
            raise ValueError("繰り返しは、なし・毎日・毎週・毎月から選んでくれ。")
        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"george-reminders:{user_id}",))
            count = connection.execute("SELECT COUNT(*) FROM george_reminders WHERE user_id=%s AND status IN ('pending','processing')", (user_id,)).fetchone()[0]
            if count >= 20:
                raise ValueError("未通知の予定は1人20件までだぜ。不要な予定を取り消してくれ。")
            return connection.execute("""INSERT INTO george_reminders (guild_id,channel_id,user_id,due_at,content,repeat_kind,anchor_day)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (guild_id, channel_id, user_id, due_at, content, repeat, due_at.astimezone(JST).day)).fetchone()[0]

    def list(self, guild_id, user_id):
        with self.connect() as connection:
            return connection.execute("""SELECT id, due_at, content, status, channel_id, repeat_kind FROM george_reminders
                WHERE guild_id=%s AND user_id=%s AND status IN ('pending','processing','failed')
                ORDER BY due_at LIMIT 50""", (guild_id, user_id)).fetchall()

    def cancel(self, guild_id, user_id, reminder_id):
        with self.connect() as connection:
            return connection.execute("""UPDATE george_reminders SET status='cancelled' WHERE id=%s
                AND guild_id=%s AND user_id=%s AND status IN ('pending','processing','failed')""",
                                      (reminder_id, guild_id, user_id)).rowcount > 0

    def claim_due(self):
        with self.connect() as connection:
            connection.execute("UPDATE george_reminders SET status='failed' WHERE status='processing' AND lease_until<NOW() AND attempts>=5")
            return connection.execute("""WITH due AS (
                SELECT id FROM george_reminders WHERE due_at<=NOW() AND attempts<5
                AND (status='pending' OR (status='processing' AND lease_until<NOW()))
                ORDER BY due_at FOR UPDATE SKIP LOCKED LIMIT 10)
                UPDATE george_reminders r SET status='processing', attempts=r.attempts+1,
                lease_until=NOW()+INTERVAL '5 minutes' FROM due WHERE r.id=due.id
                RETURNING r.id,r.guild_id,r.channel_id,r.user_id,r.due_at,r.content,r.repeat_kind""").fetchall()

    def active(self, reminder_id):
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM george_reminders WHERE id=%s AND status='processing'", (reminder_id,)).fetchone() is not None

    def finish(self, reminder_id, success):
        with self.connect() as connection:
            if success:
                row = connection.execute("SELECT due_at, repeat_kind, anchor_day FROM george_reminders WHERE id=%s AND status='processing' FOR UPDATE", (reminder_id,)).fetchone()
                if row is None:
                    return
                next_due = next_occurrence(*row)
                if next_due is None:
                    connection.execute("UPDATE george_reminders SET status='sent' WHERE id=%s AND status='processing'", (reminder_id,))
                else:
                    connection.execute("UPDATE george_reminders SET status='pending', due_at=%s, attempts=0, lease_until=NULL WHERE id=%s AND status='processing'", (next_due, reminder_id))
            else:
                connection.execute("UPDATE george_reminders SET status='failed' WHERE id=%s AND status='processing' AND attempts>=5", (reminder_id,))


class ReminderScheduler:
    def __init__(self, store):
        self.store = store
        self.task = None
        self.last_check_at = None
        self.last_check_ok = None
        self.last_delivery_failed = False

    def start(self, bot):
        if self.store.url and self.task is None:
            self.task = asyncio.create_task(self.run(bot))

    async def run(self, bot):
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                await self.deliver_due(bot)
                self.last_check_ok = True
            except Exception as exc:
                self.last_check_ok = False
                logging.warning("Reminder check failed: type=%s", type(exc).__name__)
            self.last_check_at = datetime.now(timezone.utc)
            await asyncio.sleep(60)

    async def deliver_due(self, bot):
        self.last_delivery_failed = False
        for row in await asyncio.to_thread(self.store.claim_due):
            rid, guild_id, channel_id, user_id, due_at, content = row[:6]
            repeat = row[6] if len(row) > 6 else "none"
            try:
                channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                if getattr(getattr(channel, "guild", None), "id", None) != guild_id:
                    raise ValueError("Reminder channel does not match guild")
                if not await asyncio.to_thread(self.store.active, rid):
                    continue
                stamp = due_at.astimezone(JST).strftime("%Y/%m/%d %H:%M")
                await channel.send(f"📅 <@{user_id}> 予定のお知らせだぜ！\n{stamp}（日本時間）｜{REPEAT_LABELS.get(repeat, '不明')}\n{discord.utils.escape_mentions(content)}\n予定ID：{rid}",
                                   allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=user_id)], roles=False, everyone=False))
            except Exception as exc:
                self.last_delivery_failed = True
                logging.warning("Reminder delivery failed: type=%s", type(exc).__name__)
                await asyncio.to_thread(self.store.finish, rid, False)
            else:
                await asyncio.to_thread(self.store.finish, rid, True)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
