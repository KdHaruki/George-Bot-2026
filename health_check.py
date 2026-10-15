"""Shared, rate-limited active checks without credentials or user content."""
import asyncio
import time
from datetime import timezone, timedelta
import discord
from google.genai import types
from george_chat import describe_chat_error


class HealthCheck:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.checked_at = None
        self.results = None

    async def gemini_check(self, chat):
        if chat.client is None:
            return "未設定：GEMINI_API_KEYが必要"
        try:
            await asyncio.wait_for(chat.client.aio.models.generate_content(
                model=chat.model, contents="Reply OK.",
                config=types.GenerateContentConfig(max_output_tokens=128)), timeout=20)
            return "正常：テストリクエストにAPI応答あり"
        except Exception as exc:
            diagnostic, _ = describe_chat_error(exc)
            return "接続テスト失敗：" + diagnostic

    async def database_check(self, store):
        if not store.url:
            return "未設定：共有記憶・永続予定は利用不可"
        try:
            ok = await asyncio.wait_for(asyncio.to_thread(store.ping), timeout=20)
            return "正常：接続・SELECT確認済み" if ok else "異常：接続確認の結果が不正"
        except Exception:
            return "接続テスト失敗：DATABASE_URL・DBの稼働状態を確認"

    async def report(self, bot):
        async with self.lock:
            if self.checked_at is None or time.monotonic() - self.checked_at >= 300:
                self.results = await asyncio.gather(self.gemini_check(bot.george_chat), self.database_check(bot.memories))
                self.checked_at = time.monotonic()
        age = int(time.monotonic() - self.checked_at)
        embed = discord.Embed(title="ジョージの健康診断", description=f"API・DBの確認結果：{age}秒前（5分間共用キャッシュ）", color=0xE2AD48)
        embed.add_field(name="Discord", value="接続中" if bot.is_ready() else "接続準備中", inline=False)
        embed.add_field(name="Gemini", value=self.results[0], inline=False)
        embed.add_field(name="データベース", value=self.results[1], inline=False)
        scheduler = bot.reminders
        if not scheduler.store.url:
            status = "無効：DATABASE_URL未設定"
        elif scheduler.task is None or scheduler.task.done():
            status = "停止：予定の監視タスクが動いていない"
        else:
            status = "監視タスク稼働中"
        if scheduler.last_check_at:
            stamp = scheduler.last_check_at.astimezone(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M:%S")
            status += f"\n最終確認：{stamp}（日本時間）／" + ("DB確認成功" if scheduler.last_check_ok else "確認失敗")
        else:
            status += "\n予定のDB確認：まだ未実施"
        if scheduler.last_delivery_failed:
            status += "\n直近の確認で通知送信に失敗あり"
        next_check = getattr(scheduler, "next_check_at", None)
        if next_check:
            stamp = next_check.astimezone(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M:%S")
            status += f"\n次回確認予定：{stamp}（日本時間・変更時は読み直し）"
        status += "\n※各チャンネルへの実際の通知到達は未検証"
        embed.add_field(name="予定通知", value=status, inline=False)
        embed.add_field(name="短時間タイマー", value=f"このBot全体で稼働中：{len(bot.timers.tasks)}件", inline=False)
        seasonal = getattr(bot, "seasonal", None)
        if seasonal is not None:
            enabled = bool(seasonal.store.url)
            running = seasonal.task is not None and not seasonal.task.done()
            text = "未設定：DATABASE_URLが必要" if not enabled else ("監視中：投稿先の指定は /季節通知 設定" if running else "監視タスク停止")
            if seasonal.calendar.refresh_failed:
                text += "\n祝日データの更新失敗（利用できる保存済みデータで継続）"
            if seasonal.last_delivery_failed or seasonal.last_check_ok is False:
                text += "\n直近の確認・送信に失敗あり（ログを確認）"
            embed.add_field(name="季節通知（日本時間10:00）", value=text, inline=False)
        embed.set_footer(text="Gemini接続テストは利用枠を消費します。会話本文・登録記憶はテストに送りません。")
        return embed
