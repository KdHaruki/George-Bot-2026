import asyncio
import random
import re

import discord


FORTUNES = [
    ("大吉", "今日はいい流れが来そうだぜ！ やりたかったことを一つ試してみな。"),
    ("中吉", "焦らずいけばいい感じだな。小さな楽しみを見つけようぜ！"),
    ("小吉", "小さなラッキーも見逃すなよ。好きなものでひと息だぜ！"),
    ("吉", "いつもの一日にも楽しみはあるぜ。気楽にいこうな！"),
    ("末吉", "楽しみは後から来るかもな。今日はじっくりいこうぜ！"),
    ("凶", "そんな日もあるぜ。これは遊びのおみくじだ、気にしすぎず休もうな！"),
]


def draw_fortune(fortune=None):
    if fortune is None:
        fortune, comment = random.choice(FORTUNES)
    else:
        comment = dict(FORTUNES)[fortune]
    return f"🎍 今日のおみくじ：**{fortune}**\n{comment}\nラッキーアイテム：{random.choice(['温かい飲み物', 'お気に入りの曲', 'ハンカチ', 'おやつ', '本', '帽子'])}"


def parse_duration(value):
    value = value.strip().replace(" ", "").replace("　", "")
    matches = list(re.finditer(r"(\d+)(時間|分|秒|h|m|s)", value.lower()))
    if not matches or "".join(m.group(0) for m in matches) != value.lower():
        raise ValueError("「10分」「1時間30分」「30秒」のように指定してくれ！")
    units = {"時間": 3600, "分": 60, "秒": 1, "h": 3600, "m": 60, "s": 1}
    seconds = sum(int(m.group(1)) * units[m.group(2)] for m in matches)
    if not 1 <= seconds <= 86400:
        raise ValueError("時間は1秒から24時間までだぜ！")
    return seconds


class TimerManager:
    def __init__(self):
        self.tasks = {}

    def start(self, channel, user_id, seconds, label):
        if len(self.tasks) >= 100 or sum(uid == user_id for _, uid in self.tasks.values()) >= 3:
            raise ValueError("タイマーの上限だぜ。1人3件までで、Bot全体では100件までだ。")
        task = asyncio.create_task(self._notify(channel, user_id, seconds, label))
        self.tasks[task] = (channel.id, user_id)
        task.add_done_callback(lambda finished: self.tasks.pop(finished, None))
        return task

    async def _notify(self, channel, user_id, seconds, label):
        await asyncio.sleep(seconds)
        try:
            await channel.send(f"⏰ <@{user_id}> 時間だぜ！\n{discord.utils.escape_mentions(label)}",
                               allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=user_id)], roles=False, everyone=False))
        except discord.HTTPException:
            import logging
            logging.warning("Timer notification could not be delivered")

    def cancel(self, channel_id, user_id):
        matches = [task for task, owner in self.tasks.items() if owner == (channel_id, user_id)]
        for task in matches:
            self.tasks.pop(task, None)
            task.cancel()
        return len(matches)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
