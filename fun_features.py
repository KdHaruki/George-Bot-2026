import asyncio
import random
import re
import time
from collections import OrderedDict

import discord
from mood_store import MoodStore


class MoodMeter:
    DELTAS = {"agree": (5, -5), "disagree": (-10, 10), "what": (-15, 20), "cushion": (15, -10)}

    def __init__(self):
        self.channels = OrderedDict()

    def values(self, channel_id):
        return self.channels.get(channel_id, (50, 0))

    def update(self, channel_id, action):
        confidence, confusion = self.values(channel_id)
        dc, df = self.DELTAS[action]
        self.channels[channel_id] = (max(0, min(100, confidence + dc)), max(0, min(100, confusion + df)))
        self.channels.move_to_end(channel_id)
        if len(self.channels) > 512:
            self.channels.popitem(last=False)

    def status(self, channel_id):
        confidence, confusion = self.values(channel_id)
        if confusion >= 60:
            return "空回り気味"
        if confidence >= 70:
            return "ドヤ顔モード"
        if confidence <= 30:
            return "ちょっとしおらしい"
        return "いつものジョージ"

    def display(self, channel_id):
        confidence, confusion = self.values(channel_id)
        def bar(value):
            return "■" * (value // 10) + "□" * (10 - value // 10)
        return f"🎩 {self.status(channel_id)}\nドヤ度 {bar(confidence)} {confidence}/100\n空回り度 {bar(confusion)} {confusion}/100"

    def instruction(self, channel_id):
        return f"\n【台詞の演出】現在は「{self.status(channel_id)}」。軽い雑談にだけ控えめに反映します。空回りは少し照れる演出で、内容をでたらめにしません。真剣な相談、事実の正確さ、機能説明は調子によって変えません。"


class FeedbackView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.last_click = OrderedDict()
        self.mood = MoodMeter()
        self.store = MoodStore()
        self.mood_lock = asyncio.Lock()

    async def restore_mood(self):
        try:
            rows = await asyncio.to_thread(self.store.load)
        except Exception:
            raise RuntimeError("調子メーターの保存先に接続できません。DATABASE_URLを確認してください。") from None
        for channel_id, confidence, confusion in reversed(rows):
            self.mood.channels[channel_id] = (confidence, confusion)

    async def ensure_mood(self, channel_id):
        async with self.mood_lock:
            if channel_id not in self.mood.channels:
                stored = await asyncio.to_thread(self.store.get, channel_id)
                if stored is not None:
                    self.mood.channels[channel_id] = tuple(stored)
                    if len(self.mood.channels) > 512:
                        self.mood.channels.popitem(last=False)

    async def respond(self, interaction, replies, action):
        now = time.monotonic()
        if now - self.last_click.get(interaction.user.id, -100) < 5:
            await interaction.response.send_message("ちょっと待ってくれ、連打は目が回るぜ！", ephemeral=True)
            return
        self.last_click[interaction.user.id] = now
        self.last_click.move_to_end(interaction.user.id)
        if len(self.last_click) > 1024:
            self.last_click.popitem(last=False)
        await interaction.response.defer(thinking=True)
        async with self.mood_lock:
            previous = self.mood.values(interaction.channel_id)
            try:
                if interaction.channel_id not in self.mood.channels:
                    stored = await asyncio.to_thread(self.store.get, interaction.channel_id)
                    if stored is not None:
                        previous = tuple(stored)
                        self.mood.channels[interaction.channel_id] = previous
                self.mood.update(interaction.channel_id, action)
                await asyncio.to_thread(self.store.save, interaction.channel_id, *self.mood.values(interaction.channel_id))
            except Exception:
                self.mood.channels[interaction.channel_id] = previous
                await interaction.followup.send("調子を保存できなかったぜ。今回は変更せずにおくな。", ephemeral=True)
                return
        confidence, confusion = self.mood.values(interaction.channel_id)
        await interaction.followup.send(random.choice(replies) + f"\n🎩 {self.mood.status(interaction.channel_id)}｜ドヤ度 {confidence}・空回り度 {confusion}", allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label="そうだよ", style=discord.ButtonStyle.success, custom_id="george:agree")
    async def agree(self, interaction, button):
        await self.respond(interaction, ["だろ？ 話が合うじゃねえか！", "そう言ってもらえるとうれしいぜ！"], "agree")

    @discord.ui.button(label="違う", style=discord.ButtonStyle.danger, custom_id="george:disagree")
    async def disagree(self, interaction, button):
        await self.respond(interaction, ["おっと、どこが違ったか教えてくれ！", "早とちりしたかもしれねえな。正しいところを教えてくれ！"], "disagree")

    @discord.ui.button(label="何言ってんだ", style=discord.ButtonStyle.secondary, custom_id="george:what")
    async def what(self, interaction, button):
        await self.respond(interaction, ["今のは俺もちょっと空回りしたぜ……！", "ツッコミが鋭いじゃねえか。いったん落ち着くぜ！"], "what")

    @discord.ui.button(label="座布団一枚", style=discord.ButtonStyle.primary, custom_id="george:cushion")
    async def cushion(self, interaction, button):
        await self.respond(interaction, ["座布団一枚いただきだぜ！", "へへ、俺の渋さが伝わったか！"], "cushion")


FORTUNES = [
    ("大吉", "今日はいい流れが来そうだぜ！ やりたかったことを一つ試してみな。"),
    ("中吉", "焦らずいけばいい感じだな。小さな楽しみを見つけようぜ！"),
    ("小吉", "小さなラッキーも見逃すなよ。好きなものでひと息だぜ！"),
    ("吉", "いつもの一日にも楽しみはあるぜ。気楽にいこうな！"),
    ("末吉", "楽しみは後から来るかもな。今日はじっくりいこうぜ！"),
    ("凶", "そんな日もあるぜ。これは遊びのおみくじだ、気にしすぎず休もうな！"),
]


def draw_fortune():
    fortune, comment = random.choice(FORTUNES)
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
