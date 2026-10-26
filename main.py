from ambient_logging import logger as ambient_logger
from operation_logging import event as log_event, command_finished
from message_history import MessageHistory
import discord
from discord import app_commands
import random
import time
import os
import logging
import re
import asyncio
from threading import Thread
from ambient_chat import AmbientChat, REACTION_CHANCE, SERIOUS
from ambient_history import load_ambient_history
from george_chat import GeorgeChat, ChatBusy, ChatUnavailable, describe_chat_error, is_management_question, MANAGEMENT_REPLY
import progress as progress_module
from keep_alive import keep_alive
from fun_features import FORTUNES, LUCKY_PROGRESS, fortune_embed
from database import MemoryUnavailable
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
from progress_profiles import profile_for, george_name
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
        self.message_history = MessageHistory()
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
            await self.message_history.close()
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
            return {'character': card.character, 'profile': favorite_details(card)}
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
            log_event('AI・ヘルプの挨拶', '定型文に切り替え', error=exc)
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
    for cleanup in (client.title_roles.retire_exchange, client.title_roles.retire_collections, client.title_roles.retire_removed):
        try:
            await cleanup(guild)
        except (MemoryUnavailable, ValueError, discord.HTTPException) as exc:
            logging.warning('Retired title cleanup failed: guild=%s type=%s', guild.id, type(exc).__name__)


@client.event
async def on_interaction(interaction):
    client.command_history.observe(interaction)
    if interaction.type == discord.InteractionType.application_command:
        log_event('コマンド', '受付', 操作ID=interaction.id)


@client.event
async def on_app_command_completion(interaction, command):
    command_finished(interaction, command)


@client.tree.error
async def on_command_error(interaction, error):
    command = interaction.command
    if command is not None:
        command_finished(interaction, command, error)
    else:
        log_event('コマンド', '失敗', error=error, 操作ID=interaction.id)
    if not interaction.response.is_done():
        await interaction.response.send_message('処理を完了できなかったぜ。少し待ってからもう一度試してくれ。', ephemeral=True)
    else:
        await interaction.followup.send('処理を完了できなかったぜ。少し待ってからもう一度試してくれ。', ephemeral=True)

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
    elif result.startswith('【名前】') and profile_for(name) is not None:
        character = result.splitlines()[0].removeprefix('【名前】').strip()
        try:
            await asyncio.to_thread(client.title_store.named_profile_search, interaction.user.id, interaction.id, character)
        except MemoryUnavailable:
            logging.warning('Named profile title update failed')
            await interaction.followup.send('プロフィールは表示したが、称号の記録を確認できなかったぜ。あとでもう一度試してくれ。', ephemeral=True)
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
        fortune = reward.get('fortune', fortune)
        lucky_progress = reward.get('lucky_progress') or lucky_progress
    except MemoryUnavailable:
        log_event('おみくじの贈り物', 'DB保存・受け取りを確認できない', 操作ID=interaction.id)
    try:
        comment = await client.george_chat.fortune_details(fortune, lucky_progress)
    except Exception as exc:
        log_event('AI・おみくじの一言', '定型文に切り替え', error=exc, 操作ID=interaction.id)
        comment = dict(FORTUNES)[fortune] + f' {george_name(lucky_progress)}のことも思い浮かべて、小さな楽しみを探してみな！'
    embed = fortune_embed(fortune, comment, lucky_progress)
    gift_heading = '【今日の贈り物】'
    if reward is None:
        gift_heading = '【贈り物の受け取り確認】'
        text = '保存先との通信で、受け取りを確認できなかったぜ。あとでもう一度試してくれ。'
    elif reward['granted']:
        emoji, label = ITEMS[reward['item']]
        text = f'{emoji} **{label} ×1** を受け取ったぜ！\n`/お気に入り プレゼント`で贈れるぞ。'
    else:
        gift_heading = '【贈り物は受け取り済み】'
        text = '今日の分は受け取り済みだぜ！ 次は明日の0時（日本時間）からだ。'
    if reward and reward.get('bonus_item'):
        if not reward['granted']:
            gift_heading = '【今日の贈り物】'
            text = '通常の贈り物は受け取り済みだぜ。'
        emoji, label = ITEMS[reward['bonus_item']]
        text += f'\n\n**応援ボーナス！**\nお気に入りと一致！ {emoji} **{label}** ×1を追加したぜ！'
    elif reward and reward.get('support_matched'):
        text += '\n\nお気に入りからの応援が届いたぜ！ 追加の贈り物は今日は受け取り済みだ。'
    embed.add_field(name=gift_heading, value=text, inline=False)
    await interaction.followup.send(embed=space_headings(embed, space_first=False), allowed_mentions=discord.AllowedMentions.none())
    await notify_titles(interaction, client.present_store)


async def reply_to_addressed_message(message, target, reacted, feature):
    outcome = '返信完了'
    history = getattr(client, 'message_history', None)
    if history is not None:
        kind = 'dm' if message.guild is None else 'reply' if target is not None else 'mention'
        history.observe(message, kind)
    if reacted:
        ambient_logger.info('skip reason=direct_conversation channel=%s message=%s', message.channel.id, getattr(message, 'id', None))
    help_text = re.sub(rf"<@!?{client.user.id}>", "", message.content).strip()
    if is_management_question(help_text):
        await message.channel.send(MANAGEMENT_REPLY, allowed_mentions=discord.AllowedMentions.none())
        client.ambient.note_reply(message.channel.id)
        return '管理情報への回答を見送り・案内返信完了'
    if help_text.lower() in ('ヘルプ', 'help'):
        await message.channel.send(embed=await help_embed(client, message.guild is not None),
                                   allowed_mentions=discord.AllowedMentions.none())
        client.ambient.note_reply(message.channel.id)
        return 'ヘルプ表示完了'
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
        outcome = 'プログレス検索の返信完了'
    else:
        text = re.sub(rf"<@!?{client.user.id}>", "", message.content).strip()
        key = (message.channel.id, message.author.id)
        try:
            if not text:
                outcome = '入力案内の返信完了'
                answer = "何を話そうか？ メンションに続けて話しかけてくれ！ 検索は /プログレス だぜ。"
            else:
                async with message.channel.typing():
                    favorite = await conversation_favorite(client, message.author.id)
                    options = {'favorite': favorite} if favorite else {}
                    answer = await client.george_chat.reply(key, text,
                                                           reply_to=target.content if target is not None else '', **options)
        except MemoryUnavailable as exc:
            outcome = '案内返信完了'
            log_event(feature, '通常の返答を見送り', reason='DB利用不可', メッセージID=getattr(message, 'id', None))
            answer = str(exc)
        except ChatUnavailable:
            outcome = '案内返信完了'
            log_event(feature, '通常の返答を見送り', reason='AI利用不可', メッセージID=getattr(message, 'id', None))
            answer = "会話機能はまだ準備中だぜ。管理者にGEMINI_API_KEYの設定をお願いしてくれ！"
        except ChatBusy:
            outcome = '案内返信完了'
            log_event(feature, '通常の返答を見送り', reason='返答を生成中', メッセージID=getattr(message, 'id', None))
            answer = "今、返事を考えてるぜ！ 少し待ってから話しかけてくれ。"
        except Exception as exc:
            # Do not log API keys, message contents, or provider error bodies.
            outcome = 'エラー案内の返信完了'
            _, answer = describe_chat_error(exc)
            log_event('AI・会話', '返答生成に失敗', error=exc, メッセージID=message.id)
        for offset in range(0, len(answer), 1900):
            await message.channel.send(answer[offset:offset + 1900], allowed_mentions=discord.AllowedMentions.none())
    client.ambient.note_reply(message.channel.id)
    return outcome


@client.event
async def on_message(message):

    if message.author.bot:
        return

    reacted = False
    if random.random() < REACTION_CHANCE:
        emojis = ["😆", "😂", "😍", "😭", "🤔", "😎", "🥺", "👍", "🎉", "👀"]
        try:
            await message.add_reaction(random.choice(emojis))
            reacted = True
            ambient_logger.info('reaction_added channel=%s message=%s', message.channel.id, getattr(message, 'id', None))
        except discord.HTTPException:
            # Missing reaction permissions must not prevent conversation replies.
            logging.warning("Random reaction could not be added")

    target = await george_reply_target(message, client.user.id)
    # Replies to George work even when Discord's reply mention is disabled.
    if client.user in message.mentions or target is not None or isinstance(message.channel, discord.DMChannel):
        kind = 'DM' if message.guild is None else 'ジョージへの返信' if target is not None else 'メンション'
        feature = '会話・' + kind
        started = time.monotonic()
        ids = dict(メッセージID=getattr(message, 'id', None), チャンネルID=message.channel.id)
        log_event(feature, '受付', **ids)
        try:
            outcome = await reply_to_addressed_message(message, target, reacted, feature)
        except Exception as exc:
            log_event(feature, '処理失敗・返信未完了', error=exc,
                      秒=round(time.monotonic() - started, 2), **ids)
        else:
            log_event(feature, outcome, 秒=round(time.monotonic() - started, 2), **ids)
        return

    if message.guild is None:
        if reacted:
            ambient_logger.info('skip reason=no_guild channel=%s', message.channel.id)
        return
    directed = bool(message.mentions or message.role_mentions or message.mention_everyone or message.reference)
    state = client.ambient.observe(message.channel.id, message.author.id, message.content, directed=directed,
                                   attachments=tuple(getattr(message, "attachments", ())))
    if not reacted:
        return
    if state is None:
        observed = client.ambient.states.get(message.channel.id)
        reason = observed.skip_reason if observed is not None else 'channel_capacity'
        ambient_logger.info('skip reason=%s channel=%s message=%s', reason, message.channel.id, getattr(message, 'id', None))
        return
    if client.george_chat.client is None:
        ambient_logger.info('skip reason=ai_unavailable channel=%s message=%s', message.channel.id, getattr(message, 'id', None))
        return
    ambient_logger.info('attempt_started channel=%s message=%s', message.channel.id, getattr(message, 'id', None))
    client.ambient.reserve(state)
    revision = state.revision
    try:
        context = await load_ambient_history(message)
        if not context:
            ambient_logger.info('skip reason=history_unavailable channel=%s', message.channel.id)
            return
        if not client.ambient.still_current(message.channel.id, state) or state.revision != revision:
            ambient_logger.info('skip reason=context_invalidated channel=%s', message.channel.id)
            return
        answer = await client.george_chat.ambient_reply(context)
        # Ordinary new messages do not cancel a reply; directed conversations do.
        if not answer:
            ambient_logger.info('skip reason=generation_declined channel=%s', message.channel.id)
        elif not client.ambient.still_current(message.channel.id, state) or state.revision != revision:
            ambient_logger.info('skip reason=context_invalidated channel=%s', message.channel.id)
        elif any(word in item[2] for item in state.messages for word in SERIOUS):
            ambient_logger.info('skip reason=serious_context channel=%s', message.channel.id)
        else:
            await message.channel.send(answer, allowed_mentions=discord.AllowedMentions.none())
            client.ambient.note_auto_reply(message.channel.id)
            ambient_logger.info('reply_sent channel=%s message=%s', message.channel.id, getattr(message, 'id', None))
    except Exception as exc:
        diagnostic, _ = describe_chat_error(exc)
        ambient_logger.warning('skip reason=exception channel=%s diagnostic=%s', message.channel.id, diagnostic)
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
