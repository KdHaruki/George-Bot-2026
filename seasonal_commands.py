import asyncio
import discord
from discord import app_commands
from registered_memory import MemoryUnavailable
from seasonal_calendar import DEFAULT_EVENTS, parse_event_date


def register_seasonal_commands(bot):
    group = app_commands.Group(name="季節通知", description="季節・祝日の自動投稿を設定（日本時間10:00固定）", guild_only=True)

    async def manager(interaction):
        if not interaction.permissions.manage_guild:
            await interaction.response.send_message("サーバー管理権限が必要だぜ。", ephemeral=True)
            return False
        await interaction.response.defer(ephemeral=True)
        return True

    async def send(interaction, text):
        for offset in range(0, len(text), 1800):
            await interaction.followup.send(text[offset:offset + 1800], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="設定", description="このチャンネルを季節通知の投稿先にする（10:00固定）")
    async def configure(interaction: discord.Interaction):
        if not await manager(interaction):
            return
        thread = isinstance(interaction.channel, discord.Thread)
        if not (interaction.app_permissions.view_channel and (interaction.app_permissions.send_messages_in_threads if thread else interaction.app_permissions.send_messages)):
            await send(interaction, "このチャンネルへの閲覧・送信権限をジョージに付けてくれ！")
            return
        try:
            await asyncio.to_thread(bot.seasonal_store.configure, interaction.guild_id, interaction.channel_id)
            bot.seasonal.notify_changed()
            text = "このチャンネルを投稿先にしたぜ！ 行事・祝日の日本時間10:00に投稿するぞ。当日10時以降の起動・設定なら当日中に通知するが、翌日には持ち越さないぜ。"
        except MemoryUnavailable as exc:
            text = str(exc)
        await send(interaction, text)

    @group.command(name="確認", description="投稿先と時刻を確認")
    async def status(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            row = await asyncio.to_thread(bot.seasonal_store.settings, interaction.guild_id)
            text = f"投稿先：<#{row[1]}>\n日本時間10:00固定｜{'有効' if row[2] else '停止中'}\n祝日と共通行事は自動判定するぜ。" if row else "まだ投稿先が未設定だぜ。管理者が投稿先で /季節通知 設定 を実行してくれ。"
        except MemoryUnavailable as exc:
            text = str(exc)
        await send(interaction, text)

    @group.command(name="停止", description="このサーバーの季節通知を止める")
    async def stop(interaction: discord.Interaction):
        if not await manager(interaction):
            return
        try:
            await asyncio.to_thread(bot.seasonal_store.stop, interaction.guild_id)
            bot.seasonal.notify_changed()
            text = "季節通知を停止したぜ。再開は投稿先で /季節通知 設定 を実行してくれ。送信直前の通知は届く場合があるぞ。"
        except MemoryUnavailable as exc:
            text = str(exc)
        await send(interaction, text)

    @bot.tree.command(name="行事追加", description="このサーバー独自の毎年の行事を追加・同名更新")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(日付="月-日。例：04-01", 名前="行事名。最大60文字")
    async def add_event(interaction: discord.Interaction, 日付: str, 名前: str):
        if not await manager(interaction):
            return
        try:
            month, day = parse_event_date(日付)
            await asyncio.to_thread(bot.seasonal_store.put_event, interaction.guild_id, 名前, month, day)
            bot.seasonal.notify_changed()
            text = f"毎年{month}月{day}日の「{名前.strip()}」を登録したぜ！" + ("2月29日はうるう年だけ通知するぞ。" if (month, day) == (2, 29) else "")
        except (ValueError, MemoryUnavailable) as exc:
            text = str(exc)
        await send(interaction, text)

    @bot.tree.command(name="行事一覧", description="共通の季節行事とこのサーバーの独自行事・切替設定を確認")
    @app_commands.guild_only()
    async def list_events(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            overrides = await asyncio.to_thread(bot.seasonal_store.events, interaction.guild_id)
            muted = {name for name, _, _, enabled in overrides if not enabled}
            text = "【共通の季節行事】\n" + "\n".join(f"{month:02d}-{day:02d} {name}｜{'無効' if name in muted else '有効'}" for (month, day), name in DEFAULT_EVENTS.items())
            text += "\n\n【日本の祝日・休日】\n内閣府の公開データをBot全体で自動取得するぜ。振替休日なども公表名で扱うぞ。"
            if overrides:
                text += "\n\n【このサーバーの追加・切替】\n" + "\n".join(f"{f'{month:02d}-{day:02d}' if month is not None else '共通行事・祝日'} {name}｜{'有効' if enabled else '無効'}" for name, month, day, enabled in overrides)
        except MemoryUnavailable as exc:
            text = str(exc)
        await send(interaction, text)

    @bot.tree.command(name="行事削除", description="このサーバーで追加した独自行事を削除")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def delete_event(interaction: discord.Interaction, 名前: str):
        if not await manager(interaction):
            return
        try:
            deleted = await asyncio.to_thread(bot.seasonal_store.delete_event, interaction.guild_id, 名前)
            if deleted:
                bot.seasonal.notify_changed()
            text = "独自行事を削除したぜ。" if deleted else "追加した行事が見つからないぜ。共通行事・祝日の無効化は /行事切替 を使ってくれ。"
        except MemoryUnavailable as exc:
            text = str(exc)
        await send(interaction, text)

    @bot.tree.command(name="行事切替", description="行事・祝日を名前で個別に有効化・無効化（管理者用）")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def toggle_event(interaction: discord.Interaction, 名前: str, 有効: bool):
        if not await manager(interaction):
            return
        try:
            await asyncio.to_thread(bot.seasonal_store.put_event, interaction.guild_id, 名前, enabled=有効)
            bot.seasonal.notify_changed()
            text = f"「{名前.strip()}」を{'有効' if 有効 else '無効'}にしたぜ。共通行事・祝日は正式な名前と一致する場合だけ適用するぞ。"
        except (ValueError, MemoryUnavailable) as exc:
            text = str(exc)
        await send(interaction, text)

    bot.tree.add_command(group)
