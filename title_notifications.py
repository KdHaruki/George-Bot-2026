"""Private, interaction-only delivery of committed title unlocks."""
import asyncio
import logging
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
            logging.warning('Title notification lookup unavailable')
            return
        if not rows:
            return
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
        except discord.HTTPException:
            logging.warning('Private title notification delivery failed')
        finally:
            try:
                await asyncio.to_thread(store.finish_title_notifications, interaction.user.id, token, delivered)
            except MemoryUnavailable:
                logging.warning('Title notification acknowledgement unavailable')
                return
        if not delivered:
            return
