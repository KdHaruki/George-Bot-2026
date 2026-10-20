import discord
from discord import app_commands
import random
import os
import logging
import re
import asyncio
from threading import Thread
from ambient_chat import AmbientChat, PARTICIPATION_CHANCE, REACTION_CHANCE
from ambient_history import load_ambient_history
from george_chat import GeorgeChat, ChatBusy, ChatUnavailable, describe_chat_error, is_management_question, MANAGEMENT_REPLY
import progress as progress_module
from keep_alive import keep_alive
from fun_features import FORTUNES, LUCKY_PROGRESS, fortune_embed
from registered_memory import MemoryUnavailable
from reply_context import george_reply_target
from command_help import command_help, annotate_private_commands
from health_check import HealthCheck
from seasonal_notifications import SeasonalStore, SeasonalScheduler
from seasonal_commands import register_seasonal_commands
from gacha_commands import register_gacha_commands, favorite_details
from command_permissions import require_administrator
from command_history import CommandHistory
from ange_quiz import register_quiz_commands
from presents import ITEMS
from title_store import TitleStore
from title_roles import TitleRoles
from title_commands import register_title_commands
from title_notifications import notify_titles
from discord_layout import space_headings

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
        self.command_history = CommandHistory()
        self.present_store = TitleStore()
        self.title_store = self.present_store
        self.title_roles = TitleRoles(self.title_store)

    async def setup_hook(self):
        annotate_private_commands(self.tree)
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
            await self.command_history.close()
            await self.george_chat.close()
        finally:
            await super().close()


client = MyClient()
register_seasonal_commands(client)
register_gacha_commands(client)
register_quiz_commands(client)
register_title_commands(client)


async def conversation_favorite(bot, user_id):
    store = getattr(bot, 'collection_store', None)
    if store is None or not store.url:
        return None
    try:
        selected = await asyncio.wait_for(asyncio.to_thread(store.favorite, user_id), timeout=12)
        if selected:
            _, card, _ = selected
            return {'character': card.character, 'profile': favorite_details(card)[0]}
    except Exception as exc:
        logging.warning('Conversation favorite skipped: type=%s', type(exc).__name__)
    return None


async def help_embed(bot, in_guild):
    introduction = None
    chat = getattr(bot, 'george_chat', None)
    if chat is not None and hasattr(chat, 'help_comment'):
        try:
            introduction = await asyncio.wait_for(chat.help_comment(), timeout=12)
        except Exception as exc:
            logging.warning('Help introduction fallback: type=%s', type(exc).__name__)
    return command_help(in_guild, introduction or None)

########################################
# 起動確認
########################################

@client.event
async def on_ready():
    print("ログインしました", flush=True)
    for guild in client.guilds:
        await client.clear_guild_commands(guild)
        await cleanup_retired_title(guild)


@client.event
async def on_guild_join(guild):
    await client.clear_guild_commands(guild)
    await cleanup_retired_title(guild)


async def cleanup_retired_title(guild):
    try:
        await client.title_roles.retire_exchange(guild)
    except (MemoryUnavailable, ValueError, discord.HTTPException) as exc:
        logging.warning('Retired title cleanup failed: guild=%s type=%s', guild.id, type(exc).__name__)


@client.event
async def on_interaction(interaction):
    client.command_history.observe(interaction)
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

    worlds = [color + 'の世界' for color in '青黒赤白緑']
    results = [world for world in worlds if current.strip() in world] + starts + contains

    return [
        app_commands.Choice(name=r, value=r)
        for r in results[:25]
    ]
########################################
# /プログレス プログレス検索
########################################

@client.tree.command(
    name="プログレス",
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
    }

    if name in world_map:
        result = progress_module.progressSearchAll(world_map[name])
    else:
        result = progress_module.progressSearch(name)

    # Discord limits a plain message to 2,000 characters.
    chunks = []
    chunk = ''
    for line in result.splitlines(keepends=True):
        if len(chunk) + len(line) > 1900:
            chunks.append(chunk)
            chunk = ''
        chunk += line
    chunks.append(chunk)
    await interaction.response.send_message(chunks[0], ephemeral=True)
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    if name in world_map:
        try:
            await asyncio.to_thread(client.title_store.world_search, interaction.user.id, interaction.id,
                                    '青黒赤白緑'[world_map[name]])
        except MemoryUnavailable:
            logging.warning('World search title update failed')
            await interaction.followup.send('検索結果は表示したが、称号の記録を確認できなかったぜ。あとでもう一度試してくれ。', ephemeral=True)
        await notify_titles(interaction, client.title_store)

########################################
# メッセージイベント
########################################

@client.tree.command(name="ヘルプ", description="ジョージの機能とコマンドの使い方を表示")
async def show_help(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=await help_embed(client, interaction.guild_id is not None),
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
    lucky_progress = random.choice(LUCKY_PROGRESS)
    reward = None
    try:
        reward = await asyncio.to_thread(client.present_store.claim, interaction.user.id, interaction.id, fortune, lucky_progress)
        if reward['granted']:
            fortune = reward['fortune']
            lucky_progress = reward.get('lucky_progress') or lucky_progress
    except MemoryUnavailable:
        logging.warning('Fortune present save failed')
    try:
        comment = await client.george_chat.fortune_details(fortune)
    except Exception as exc:
        diagnostic, _ = describe_chat_error(exc)
        logging.warning("Fortune generation failed: %s", diagnostic)
        comment = dict(FORTUNES)[fortune]
    embed = fortune_embed(fortune, comment, lucky_progress)
    if reward is None:
        text = '保存先との通信で、受け取りを確認できなかったぜ。あとでもう一度試してくれ。'
    elif reward['granted']:
        emoji, label = ITEMS[reward['item']]
        text = f'{emoji} **{label}** ×1\n`/お気に入り プレゼント`から贈れるぜ！'
        if reward.get('bonus_item'):
            emoji, label = ITEMS[reward['bonus_item']]
            text += f'\n\n**応援ボーナス！**\nお気に入りと一致！ {emoji} **{label}** ×1を追加したぜ！'
    else:
        text = '今日の分は受け取り済みだぜ。次は日本時間の0時から！'
    embed.add_field(name='【プレゼント】', value=text, inline=False)
    await interaction.followup.send(embed=space_headings(embed), allowed_mentions=discord.AllowedMentions.none())
    await notify_titles(interaction, client.present_store)


@client.event
async def on_message(message):

    if message.author.bot:
        return

    # Keep the original random reactions independent of ambient participation.
    if random.random() < REACTION_CHANCE:
        emojis = ["😆", "😂", "😍", "😭", "🤔", "😎", "🥺", "👍", "🎉", "👀"]
        try:
            await message.add_reaction(random.choice(emojis))
        except discord.HTTPException:
            # Missing reaction permissions must not prevent conversation replies.
            logging.warning("Random reaction could not be added")

    target = await george_reply_target(message, client.user.id)
    # Replies to George work even when Discord's reply mention is disabled.
    if client.user in message.mentions or target is not None or isinstance(message.channel, discord.DMChannel):
        help_text = re.sub(rf"<@!?{client.user.id}>", "", message.content).strip()
        if is_management_question(help_text):
            await message.channel.send(MANAGEMENT_REPLY, allowed_mentions=discord.AllowedMentions.none())
            client.ambient.note_reply(message.channel.id)
            return
        if help_text.lower() in ('ヘルプ', 'help'):
            await message.channel.send(embed=await help_embed(client, message.guild is not None),
                                       allowed_mentions=discord.AllowedMentions.none())
            client.ambient.note_reply(message.channel.id)
            return
        parts = message.content.split()
        if len(parts) >= 3 and parts[1].lower() in ["pro", "progress", "プロ", "プログレス"]:
            keyword = parts[2]
            world_map = {
                "青":0,"青の":0,"青世界":0,"青の世界":0,
                "黒":1,"黒の":1,"黒世界":1,"黒の世界":1,
                "赤":2,"赤の":2,"赤世界":2,"赤の世界":2,
                "白":3,"白の":3,"白世界":3,"白の世界":3,
                "緑":4,"緑の":4,"緑世界":4,"緑の世界":4,
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
                if not text:
                    answer = "何を話そうか？ メンションに続けて話しかけてくれ！ 検索は /プログレス だぜ。"
                else:
                    async with message.channel.typing():
                        favorite = await conversation_favorite(client, message.author.id)
                        options = {'favorite': favorite} if favorite else {}
                        answer = await client.george_chat.reply(key, text, [],
                                                               reply_to=target.content if target is not None else '', **options)
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
        if not client.ambient.still_current(message.channel.id, state) or list(state.messages) != snapshot:
            return
        answer = await client.george_chat.ambient_reply(context, [])
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
