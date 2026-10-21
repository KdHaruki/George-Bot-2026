import asyncio
import discord
from discord import app_commands
from database import MemoryUnavailable
from seasonal_calendar import DEFAULT_EVENTS
from command_permissions import require_administrator


def register_seasonal_commands(bot):
    group = app_commands.Group(name="季節通知", description="季節・祝日の自動投稿を設定（管理者用）", guild_only=True,
                              default_permissions=discord.Permissions(administrator=True))

    async def manager(interaction, administrator=True):
        if administrator:
            if not await require_administrator(interaction):
                return False
        elif not interaction.permissions.manage_guild:
            await interaction.response.send_message("サーバー管理権限が必要だぜ。", ephemeral=True)
            return False
        await interaction.response.defer(ephemeral=True)
        return True

    async def send(interaction, text):
        for offset in range(0, len(text), 1800):
            await interaction.followup.send(text[offset:offset + 1800], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def event_listing(guild_id):
        try:
            overrides = await asyncio.to_thread(bot.seasonal_store.events, guild_id)
            muted = {name for name, _, _, enabled in overrides if not enabled}
            text = "【共通の季節行事】\n" + "\n".join(f"{month}月{day}日 {name}" + ('｜無効' if name in muted else '') for (month, day), name in DEFAULT_EVENTS.items())
            text += "\n\n【日本の祝日・休日】\n内閣府の公開データをBot全体で自動取得するぜ。振替休日なども公表名で扱うぞ。"
            if overrides:
                text += "\n\n【このサーバーの追加・切替】\n" + "\n".join(f"{f'{month}月{day}日' if month is not None else '共通行事・祝日'} {name}" + ('' if enabled else '｜無効') for name, month, day, enabled in overrides)
        except MemoryUnavailable as exc:
            text = str(exc)
        return text

    @group.command(name="設定", description="季節通知のON・OFFを切替（ON時はこのチャンネルへ通知・管理者用）")
    async def configure(interaction: discord.Interaction):
        if not await manager(interaction):
            return
        thread = isinstance(interaction.channel, discord.Thread)
        can_send = interaction.app_permissions.view_channel and (interaction.app_permissions.send_messages_in_threads if thread else interaction.app_permissions.send_messages)
        try:
            enabled = await asyncio.to_thread(bot.seasonal_store.toggle, interaction.guild_id, interaction.channel_id, can_send)
            bot.seasonal.notify_changed()
            text = ('季節通知をONにしたぜ！ このチャンネルに日本時間10:00に投稿するぞ。当日10時以降なら当日中に通知する場合があるぜ。'
                    if enabled else '季節通知をOFFにしたぜ。送信直前の通知は届く場合があるぞ。再開するには投稿先で /季節通知 設定 を実行してくれ。')
        except (MemoryUnavailable, ValueError) as exc:
            text = str(exc)
        await send(interaction, text)

    @group.command(name="確認", description="投稿先・通知状態・行事一覧を確認（管理者用）")
    async def status(interaction: discord.Interaction):
        if not await manager(interaction):
            return
        try:
            row = await asyncio.to_thread(bot.seasonal_store.settings, interaction.guild_id)
            text = f"投稿先：<#{row[1]}>\n日本時間10:00固定｜{'有効' if row[2] else '停止中'}\n祝日と共通行事は自動判定するぜ。" if row else "まだ投稿先が未設定だぜ。管理者が投稿先で /季節通知 設定 を実行してくれ。"
        except MemoryUnavailable as exc:
            text = str(exc)
        text += "\n\n" + await event_listing(interaction.guild_id)
        await send(interaction, text)

    bot.tree.add_command(group)
