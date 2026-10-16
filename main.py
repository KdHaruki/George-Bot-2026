import discord
from discord import app_commands
import random
import os
import logging
import re
import asyncio
from threading import Thread
from ambient_chat import AmbientChat, PARTICIPATION_CHANCE
from ambient_history import load_ambient_history
from george_chat import GeorgeChat, ChatBusy, ChatUnavailable, describe_chat_error
import progress as progress_module
from keep_alive import keep_alive
from fun_features import draw_fortune, FORTUNES
from registered_memory import MemoryUnavailable
from reply_context import george_reply_target
from command_help import command_help, HELP_CATEGORIES
from health_check import HealthCheck
from image_inputs import ImageSource, load_images, ambient_image_sources
from seasonal_notifications import SeasonalStore, SeasonalScheduler
from seasonal_commands import register_seasonal_commands
from gacha_commands import register_gacha_commands
from dm_history import DMStore, archive_dm, register_dm_history
from command_permissions import require_administrator

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
        self.seasonal_store = SeasonalStore()
        self.seasonal = SeasonalScheduler(self.seasonal_store)
        self.cleaned_guilds = set()
        self.health = HealthCheck()
        self.dm_store = DMStore()

    async def setup_hook(self):
        commands = await self.tree.sync()
        print("Commands synced globally: " + ", ".join(command.name for command in commands), flush=True)
        self.seasonal.start(self)

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
            await self.seasonal.close()
            await self.george_chat.close()
        finally:
            await super().close()


client = MyClient()
register_seasonal_commands(client)
register_gacha_commands(client)
register_dm_history(client, client.dm_store)

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

@client.tree.command(name="ヘルプ", description="やりたいことからコマンドを探す（分類で詳しい使い方）")
@app_commands.describe(分類="会話・ガチャ・季節通知など、やりたいことを選ぶ")
@app_commands.choices(分類=[app_commands.Choice(name=label, value=key) for key, label in HELP_CATEGORIES.items()])
async def show_help(interaction: discord.Interaction, 分類: str = 'overview'):
    await interaction.response.send_message(embed=command_help(interaction.guild_id is not None, 分類),
                                            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="状態", description="Gemini・DB・季節通知の健康診断（管理者用）")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def show_health(interaction: discord.Interaction):
    if not await require_administrator(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    embed = await client.health.report(client)
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="おみくじ", description="ジョージのおみくじで運試し")
async def omikuji(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    fortune = random.choice(FORTUNES)[0]
    try:
        comment, item = await client.george_chat.fortune_details(fortune)
        result = f"🎍 今日のおみくじ：**{fortune}**\n{comment}\nラッキーアイテム：{item}"
    except Exception as exc:
        diagnostic, _ = describe_chat_error(exc)
        logging.warning("Fortune generation failed: %s", diagnostic)
        result = draw_fortune(fortune) + "\n※今回はAIの返事を用意できなかったので、定型の結果だぜ。"
    await interaction.followup.send(result, allowed_mentions=discord.AllowedMentions.none())


@client.event
async def on_message(message):
    if not message.author.bot and message.guild is None:
        await archive_dm(client.dm_store, message)

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

    target = await george_reply_target(message, client.user.id)
    # Replies to George work even when Discord's reply mention is disabled.
    if client.user in message.mentions or target is not None or isinstance(message.channel, discord.DMChannel):
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
            attachments = tuple(getattr(message, "attachments", ()))
            key = (message.channel.id, message.author.id)
            try:
                if text.lower() in ("reset", "リセット"):
                    client.george_chat.reset(key)
                    answer = "会話をリセットしたぜ。"
                elif not text and not attachments:
                    answer = "何を話そうか？ メンションに続けて話しかけてくれ！ 検索は /progress、会話のリセットは「リセット」だぜ。"
                else:
                    async with message.channel.typing():
                        bundle = await load_images([ImageSource(item, f"今回の発言の添付画像{index + 1}") for index, item in enumerate(attachments)])
                        if attachments and not bundle.images and not text:
                            answer = "\n".join(bundle.notices)
                        else:
                            notes = []
                            image_options = {"images": bundle.images, "image_notice": " ".join(bundle.notices)} if attachments else {}
                            answer = await client.george_chat.reply(key, text or "添付画像について一言お願い。", notes,
                                                                   reply_to=target.content if target is not None else "", **image_options)
                            if bundle.notices:
                                answer += "\n※" + " ".join(bundle.notices)
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
    state = client.ambient.observe(message.channel.id, message.author.id, message.content, directed=directed,
                                   attachments=tuple(getattr(message, "attachments", ())))
    if state is None or client.george_chat.client is None or random.random() >= PARTICIPATION_CHANCE:
        return
    client.ambient.reserve(state)
    snapshot = list(state.messages)
    try:
        context = await load_ambient_history(message)
        if not context or not client.ambient.still_current(message.channel.id, state) or list(state.messages) != snapshot:
            return
        sources = ambient_image_sources(context)
        bundle = await load_images(sources)
        if sources and not bundle.images:
            return
        if not client.ambient.still_current(message.channel.id, state) or list(state.messages) != snapshot:
            return
        notes = []
        image_options = {"images": bundle.images, "image_notice": " ".join(bundle.notices)} if sources else {}
        answer = await client.george_chat.ambient_reply(context, notes, **image_options)
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
