"""Shared, rate-limited active checks without credentials or user content."""
import asyncio
import time
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
            return "未設定：季節通知・コレクションは利用不可"
        try:
            ok = await asyncio.wait_for(asyncio.to_thread(store.ping), timeout=20)
            return "正常：接続・SELECT確認済み" if ok else "異常：接続確認の結果が不正"
        except Exception:
            return "接続テスト失敗：DATABASE_URL・DBの稼働状態を確認"

    async def report(self, bot):
        async with self.lock:
            if self.checked_at is None or time.monotonic() - self.checked_at >= 300:
                self.results = await asyncio.gather(self.gemini_check(bot.george_chat), self.database_check(bot.seasonal_store))
                self.checked_at = time.monotonic()
        age = int(time.monotonic() - self.checked_at)
        embed = discord.Embed(title="ジョージの健康診断", description=f"API・DBの確認結果：{age}秒前（5分間共用キャッシュ）", color=0xE2AD48)
        embed.add_field(name="Discord", value="接続中" if bot.is_ready() else "接続準備中", inline=False)
        embed.add_field(name="Gemini", value=self.results[0], inline=False)
        embed.add_field(name="データベース", value=self.results[1], inline=False)
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
        embed.set_footer(text="Gemini接続テストは利用枠を消費します。会話本文はテストに送りません。")
        return embed
