"""Japan holiday data from the Cabinet Office, shared across all guilds."""
import csv
import io
import logging
from datetime import datetime, timedelta, timezone

import httpx

HOLIDAY_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"
JST = timezone(timedelta(hours=9))
DEFAULT_EVENTS = {(1, 1): "元日", (1, 7): "七草",
                  (2, 14): "バレンタイン", (2, 22): "猫の日",
                  (3, 3): "ひな祭り", (3, 14): "ホワイトデー",
                  (4, 1): "エイプリルフール",
                  (7, 7): "七夕", (10, 31): "ハロウィン",
                  (11, 15): "七五三", (12, 24): "クリスマスイブ",
                  (12, 25): "クリスマス", (12, 31): "大晦日"}



def parse_holidays(data):
    if len(data) > 256 * 1024:
        raise ValueError("Holiday data too large")
    rows = csv.reader(io.StringIO(data.decode("utf-8-sig") if data.startswith(b"\xef\xbb\xbf") else data.decode("cp932")))
    next(rows, None)
    holidays = {}
    for row in rows:
        if not row:
            continue
        if len(row) != 2:
            raise ValueError("Invalid holiday row")
        day = datetime.strptime(row[0], "%Y/%m/%d").date()
        name = row[1].strip()
        if not 1 <= len(name) <= 60 or not 1955 <= day.year <= 2100:
            raise ValueError("Invalid holiday data")
        holidays[day.isoformat()] = name
    if len(holidays) < 16:
        raise ValueError("Incomplete holiday data")
    return holidays


class HolidayCalendar:
    def __init__(self, store):
        self.store = store
        self.holidays = {}
        self.loaded = False
        self.next_refresh = None
        self.refresh_failed = False

    async def refresh(self, now=None):
        import asyncio
        now = now or datetime.now(timezone.utc)
        if self.next_refresh and now < self.next_refresh:
            return
        if not self.loaded:
            cached = await asyncio.to_thread(self.store.load_calendar)
            if isinstance(cached, dict):
                self.holidays = cached
            self.loaded = True
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                async with client.stream("GET", HOLIDAY_URL) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 256 * 1024:
                            raise ValueError("Holiday data too large")
            holidays = parse_holidays(bytes(data))
            await asyncio.to_thread(self.store.save_calendar, holidays)
            self.holidays = holidays
            self.refresh_failed = False
            self.next_refresh = now + timedelta(days=1)
        except Exception as exc:
            logging.warning("Holiday refresh failed: type=%s", type(exc).__name__)
            self.refresh_failed = True
            self.next_refresh = now + timedelta(hours=1)

    def covers(self, day):
        return any(key.startswith(f"{day.year}-") for key in self.holidays)


def events_for(day, holidays, overrides):
    # Overrides: (name, month, day, enabled); a null date only toggles a common event.
    muted = {name for name, _, _, enabled in overrides if not enabled}
    result = []
    if (day.month, day.day) in DEFAULT_EVENTS:
        result.append(DEFAULT_EVENTS[day.month, day.day])
    holiday = holidays.get(day.isoformat())
    if holiday:
        result.append(holiday)
    result.extend(name for name, month, number, enabled in overrides
                  if enabled and (month, number) == (day.month, day.day))
    return list(dict.fromkeys(name for name in result if name not in muted))
