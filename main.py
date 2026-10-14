import discord
from discord import app_commands
import random
import os
import logging
import re
import asyncio
from threading import Thread
from ambient_chat import AmbientChat, PARTICIPATION_CHANCE
from george_chat import GeorgeChat, ChatBusy, ChatUnavailable, describe_chat_error
import progress as progress_module
from keep_alive import keep_alive
from fun_features import TimerManager, draw_fortune, parse_duration
from registered_memory import MemoryStore, MemoryUnavailable

########################################
# Botクラス
########################################

class MyClient(discord.Client):

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.george_chat = GeorgeChat()
        self.ambient = AmbientChat()
        self.timers = TimerManager()
        self.memories = MemoryStore()
        self.cleaned_guilds = set()

    async def setup_hook(self):
        commands = await self.tree.sync()
        print("Commands synced globally: " + ", ".join(command.name for command in commands), flush=True)

    async def clear_guild_commands(self, guild):
        if guild.id in self.cleaned_guilds:
            return
        self.cleaned_guilds.add(guild.id)
        try:
            self.tree.clear_commands(guild=guild)
            commands = await self.tree.sync(guild=guild)
            print(f"Guild command duplicates cleared: guild={guild.id} remaining={len(commands)}", flush=True)
        except discord.HTTPException as exc:
            self.cleaned_guilds.discard(guild.id)
            logging.warning("Guild command sync failed: guild=%s type=%s status=%s", guild.id, type(exc).__name__, exc.status)

    async def close(self):
        try:
            await self.timers.close()
            await self.george_chat.close()
        finally:
            await super().close()

    def clear_server_context(self, guild):
        for key in list(self.george_chat.sessions):
            channel = self.get_channel(key[0])
            if getattr(getattr(channel, "guild", None), "id", None) == guild.id:
                self.george_chat.sessions.pop(key, None)
        for channel in [*guild.channels, *guild.threads]:
            self.ambient.states.pop(channel.id, None)

client = MyClient()

########################################
# 起動確認
########################################

@client.event
async def on_ready():
    print("ログインしました", flush=True)
    for guild in client.guilds:
        await client.clear_guild_commands(guild)


@client.event
async def on_guild_join(guild):
    await client.clear_guild_commands(guild)


@client.event
async def on_interaction(interaction):
    # Never log interaction tokens or message contents.
    print(f"Interaction received: type={interaction.type.name}", flush=True)

########################################
# progress オートコンプリート
########################################

async def progress_autocomplete(interaction: discord.Interaction, current: str):

    current = current.lower()

    starts = []
    contains = []

    for p in progress_module.progressData:

        name = p["progressName"]
        name_lower = name.lower()

        if current == "":
            starts.append(name)

        elif name_lower.startswith(current):
            starts.append(name)

        elif current in name_lower:
            contains.append(name)

    results = starts + contains

    return [
        app_commands.Choice(name=r, value=r)
        for r in results[:25]
    ]
########################################
# /progress プログレス検索
########################################

@client.tree.command(
    name="progress",
    description="プログレス検索"
)
@app_commands.describe(name="名前または世界")
@app_commands.autocomplete(name=progress_autocomplete)

async def progress(interaction: discord.Interaction, name: str):

    name = name.strip()

    world_map = {
        "青":0,"青の":0,"青世界":0,"青の世界":0,
        "黒":1,"黒の":1,"黒世界":1,"黒の世界":1,
        "赤":2,"赤の":2,"赤世界":2,"赤の世界":2,
        "白":3,"白の":3,"白世界":3,"白の世界":3,
        "緑":4,"緑の":4,"緑世界":4,"緑の世界":4,
        "全":5,"全ての":5,"全世界":5,"全ての世界":5
    }

    if name in world_map:
        result = progress_module.progressSearchAll(world_map[name])
    else:
        result = progress_module.progressSearch(name)

    await interaction.response.send_message(result)

########################################
# メッセージイベント
########################################

@client.tree.command(name="おみくじ", description="ジョージのおみくじで運試し")
async def omikuji(interaction: discord.Interaction):
    await interaction.response.send_message(draw_fortune(), allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="記憶登録", description="サーバー全員で共有する設定を登録・更新（管理者用）")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(タイトル="1〜40文字。同じタイトルなら更新", 内容="覚えてほしい設定。1〜300文字")
async def register_memory(interaction: discord.Interaction, タイトル: str, 内容: str):
    if not interaction.permissions.manage_guild:
        await interaction.response.send_message("サーバー管理権限が必要だぜ。", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        await asyncio.to_thread(client.memories.save, interaction.guild_id, 0, タイトル, 内容)
        client.clear_server_context(interaction.guild)
        answer = "共有設定を保存したぜ！ このサーバーの会話で参照するぞ。反映のため、このサーバーの短期会話履歴もクリアしたぜ。"
    except (MemoryUnavailable, ValueError) as exc:
        answer = str(exc)
    await interaction.followup.send(answer, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="記憶一覧", description="このサーバーの共有登録設定を確認")
@app_commands.guild_only()
async def list_memory(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        notes = await asyncio.to_thread(client.memories.list, interaction.guild_id, 0)
        text = "共有登録設定：\n" + "\n\n".join(f"【{title}】\n{content}" for title, content in notes) if notes else "まだ共有設定は登録されてないぜ。"
    except MemoryUnavailable as exc:
        text = str(exc)
    for offset in range(0, len(text), 1800):
        await interaction.followup.send(text[offset:offset + 1800], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="記憶削除", description="共有登録設定をタイトルで削除（管理者用）")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def delete_memory(interaction: discord.Interaction, タイトル: str):
    if not interaction.permissions.manage_guild:
        await interaction.response.send_message("サーバー管理権限が必要だぜ。", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await asyncio.to_thread(client.memories.delete, interaction.guild_id, 0, タイトル)
        if deleted:
            client.clear_server_context(interaction.guild)
        answer = "共有設定を削除して、このサーバーの短期会話履歴もクリアしたぜ。" if deleted else "そのタイトルの設定は見つからなかったぜ。"
    except MemoryUnavailable as exc:
        answer = str(exc)
    await interaction.followup.send(answer, ephemeral=True)


@client.tree.command(name="タイマー", description="指定した時間にジョージが呼びかける（再起動で解除）")
@app_commands.describe(時間="例：10分、1時間30分、30秒（最大24時間）", 内容="何のタイマーか（省略可）")
async def timer(interaction: discord.Interaction, 時間: str, 内容: str = "タイマー終了"):
    try:
        seconds = parse_duration(時間)
        if interaction.channel is None:
            raise ValueError("この場所ではタイマーを使えないぜ。")
        if len(内容) > 200:
            raise ValueError("内容は200文字以内で頼むぜ！")
        task = client.timers.start(interaction.channel, interaction.user.id, seconds, 内容)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    try:
        await interaction.response.send_message(f"⏰ {seconds}秒後に呼ぶぜ！ 内容：{内容}\n再起動や停止で解除されるぞ。取消は /タイマー取消 だ。", allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        task.cancel()
        raise


@client.tree.command(name="タイマー取消", description="このチャンネルで自分が設定したタイマーをすべて取り消す")
async def cancel_timer(interaction: discord.Interaction):
    count = client.timers.cancel(interaction.channel_id, interaction.user.id)
    await interaction.response.send_message(f"自分のタイマーを{count}件取り消したぜ。", ephemeral=True)

@client.event
async def on_message(message):

    if message.author.bot:
        return

    # Keep the original random reactions independent of ambient participation.
    if random.random() < 0.2:
        emojis = ["😆", "😂", "😍", "😭", "🤔", "😎", "🥺", "👍", "🎉", "👀"]
        try:
            await message.add_reaction(random.choice(emojis))
        except discord.HTTPException:
            # Missing reaction permissions must not prevent conversation replies.
            logging.warning("Random reaction could not be added")

    # メンションされた場合
    if client.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        parts = message.content.split()
        if len(parts) >= 3 and parts[1].lower() in ["pro", "progress", "プロ", "プログレス"]:
            keyword = parts[2]
            world_map = {
                "青":0,"青の":0,"青世界":0,"青の世界":0,
                "黒":1,"黒の":1,"黒世界":1,"黒の世界":1,
                "赤":2,"赤の":2,"赤世界":2,"赤の世界":2,
                "白":3,"白の":3,"白世界":3,"白の世界":3,
                "緑":4,"緑の":4,"緑世界":4,"緑の世界":4,
                "全":5,"全ての":5,"全世界":5,"全ての世界":5
            }

            if keyword in world_map:
                result = progress_module.progressSearchAll(world_map[keyword])
            else:
                result = progress_module.progressSearch(keyword)
            await message.channel.send(result)
        else:
            text = re.sub(rf"<@!?{client.user.id}>", "", message.content).strip()
            key = (message.channel.id, message.author.id)
            try:
                if text.lower() in ("reset", "リセット"):
                    client.george_chat.reset(key)
                    answer = "会話をリセットしたぜ。"
                elif not text:
                    answer = "何を話そうか？ メンションに続けて話しかけてくれ！ 検索は /progress、会話のリセットは「リセット」だぜ。"
                else:
                    async with message.channel.typing():
                        notes = await asyncio.to_thread(client.memories.list, message.guild.id, 0) if message.guild and client.memories.url else []
                        answer = await client.george_chat.reply(key, text, notes)
            except MemoryUnavailable as exc:
                answer = str(exc)
            except ChatUnavailable:
                answer = "会話機能はまだ準備中だぜ。管理者にGEMINI_API_KEYの設定をお願いしてくれ！"
            except ChatBusy:
                answer = "今、返事を考えてるぜ！ 少し待ってから話しかけてくれ。"
            except Exception as exc:
                # Do not log API keys, message contents, or provider error bodies.
                diagnostic, answer = describe_chat_error(exc)
                logging.warning("Gemini request failed: %s", diagnostic)
            for offset in range(0, len(answer), 1900):
                await message.channel.send(answer[offset:offset + 1900], allowed_mentions=discord.AllowedMentions.none())
        client.ambient.note_reply(message.channel.id)
        return

    if message.guild is None:
        return
    directed = bool(message.mentions or message.role_mentions or message.mention_everyone or message.reference)
    state = client.ambient.observe(message.channel.id, message.author.id, message.content, directed=directed)
    if state is None or client.george_chat.client is None or random.random() >= PARTICIPATION_CHANCE:
        return
    client.ambient.reserve(state)
    snapshot = list(state.messages)
    try:
        notes = await asyncio.to_thread(client.memories.list, message.guild.id, 0) if client.memories.url else []
        answer = await client.george_chat.ambient_reply(snapshot, notes)
        # If users have moved on or the context was evicted, stay quiet.
        if answer and client.ambient.still_current(message.channel.id, state) and list(state.messages) == snapshot:
            await message.channel.send(answer, allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        diagnostic, _ = describe_chat_error(exc)
        logging.warning("Ambient chat skipped: %s", diagnostic)
    finally:
        state.busy = False

########################################
# サーバ起動
########################################

def start_gemini_diagnostics():
    """Opt-in one diagnostic per process, without delaying Discord login."""
    if os.getenv("GEMINI_DIAGNOSTICS", "").strip() != "1":
        return None
    from check_gemini import main as check_gemini
    thread = Thread(target=check_gemini, kwargs={"test": True}, daemon=True,
                    name="gemini-startup-diagnostic")
    thread.start()
    return thread


if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKENを環境変数に設定してください")
    keep_alive()
    start_gemini_diagnostics()
    client.run(TOKEN)

__all__ = ["progressData","progressSearch","progressSearchAll"]
