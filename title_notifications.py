"""Private, interaction-only delivery of committed title unlocks."""
import asyncio
import logging
from operation_logging import event as log_event
import uuid

import discord

from database import MemoryUnavailable
from title_core import COMMON, title_condition


def title_icon(key):
    return '👑' if key in ('bond10', 'all_green', 'kaguya', 'complete_vierge', 'complete_relink') or key.startswith('favorite_gift:') else '🎖️'


async def notify_titles(interaction, store):
    if store is None or not callable(getattr(store, 'claim_title_notifications', None)):
        return
    while True:
        token = uuid.uuid4().hex
        try:
            rows = await asyncio.to_thread(store.claim_title_notifications, interaction.user.id, token)
        except MemoryUnavailable:
            log_event('称号通知', '取得確認に失敗', reason='DBを利用できない', 操作ID=interaction.id)
            return
        if not rows:
            return
        log_event('称号', '未通知の獲得済み称号を確認', 件数=len(rows), 操作ID=interaction.id)
        delivered = False
        try:
            header = '**称号獲得！**\n'
            text = header
            for key, name in rows:
                block = f'{title_icon(key)} **{discord.utils.escape_markdown(COMMON.get(key, name))}**\n{discord.utils.escape_markdown(title_condition(key))}'
                if len(text) + len(block) + 2 > 1800:
                    await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
                    text = header
                text += ('\n\n' if text != header else '') + block
            await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            delivered = True
            log_event('称号通知', '本人限定で送信完了', 件数=len(rows), 操作ID=interaction.id)
        except discord.HTTPException:
            log_event('称号通知', '送信失敗', reason='Discordへの送信に失敗・再通知対象として保持', 操作ID=interaction.id)
        finally:
            try:
                await asyncio.to_thread(store.finish_title_notifications, interaction.user.id, token, delivered)
            except MemoryUnavailable:
                log_event('称号通知', '送信結果のDB保存失敗', 操作ID=interaction.id)
                return
        if not delivered:
            return
