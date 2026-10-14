import discord
from discord import app_commands
import random
import os
import logging
import re
from threading import Thread
from ambient_chat import AmbientChat, PARTICIPATION_CHANCE
from george_chat import GeorgeChat, ChatBusy, ChatUnavailable, describe_chat_error
import progress as progress_module
from keep_alive import keep_alive
from fun_features import FeedbackView, TimerManager, draw_fortune, parse_duration

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
        self.feedback = FeedbackView()
        self.timers = TimerManager()
        self.synced_guilds = set()

    async def setup_hook(self):
        await self.feedback.restore_mood()
        self.add_view(self.feedback)
        commands = await self.tree.sync()
        print("Commands synced globally: " + ", ".join(command.name for command in commands), flush=True)
        print("Feedback buttons registered: 4", flush=True)

    async def sync_guild_commands(self, guild):
        if guild.id in self.synced_guilds:
            return
        self.synced_guilds.add(guild.id)
        try:
            self.tree.copy_global_to(guild=guild)
            commands = await self.tree.sync(guild=guild)
            print(f"Commands synced to guild {guild.id}: " + ", ".join(command.name for command in commands), flush=True)
        except discord.HTTPException as exc:
            self.synced_guilds.discard(guild.id)
            logging.warning("Guild command sync failed: guild=%s type=%s status=%s", guild.id, type(exc).__name__, exc.status)

    async def close(self):
        try:
            await self.timers.close()
            await self.george_chat.close()
        finally:
            await super().close()

client = MyClient()

########################################
# 起動確認
########################################

@client.event
async def on_ready():
    print("ログインしました", flush=True)
    for guild in client.guilds:
        await client.sync_guild_commands(guild)


@client.event
async def on_guild_join(guild):
    await client.sync_guild_commands(guild)


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


@client.tree.command(name="調子", description="このチャンネルのジョージの調子メーターを見る")
async def mood(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        await client.feedback.ensure_mood(interaction.channel_id)
    except Exception:
        await interaction.followup.send("保存した調子を読み込めなかったぜ。少し待って試してくれ。", ephemeral=True)
        return
    await interaction.followup.send(client.feedback.mood.display(interaction.channel_id), allowed_mentions=discord.AllowedMentions.none())


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
                        answer = await client.george_chat.reply(key, text, client.feedback.mood.instruction(message.channel.id))
            except ChatUnavailable:
                answer = "会話機能はまだ準備中だぜ。管理者にGEMINI_API_KEYの設定をお願いしてくれ！"
            except ChatBusy:
                answer = "今、返事を考えてるぜ！ 少し待ってから話しかけてくれ。"
            except Exception as exc:
                # Do not log API keys, message contents, or provider error bodies.
                diagnostic, answer = describe_chat_error(exc)
                logging.warning("Gemini request failed: %s", diagnostic)
            for offset in range(0, len(answer), 1900):
                await message.channel.send(answer[offset:offset + 1900], allowed_mentions=discord.AllowedMentions.none(),
                                           view=client.feedback if offset + 1900 >= len(answer) else None)
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
        answer = await client.george_chat.ambient_reply(snapshot, client.feedback.mood.instruction(message.channel.id))
        # If users have moved on or the context was evicted, stay quiet.
        if answer and client.ambient.still_current(message.channel.id, state) and list(state.messages) == snapshot:
            await message.channel.send(answer, allowed_mentions=discord.AllowedMentions.none(), view=client.feedback)
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
