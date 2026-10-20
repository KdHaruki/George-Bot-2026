"""Private, interaction-only delivery of committed title unlocks."""
import asyncio
import logging
import uuid

import discord

from registered_memory import MemoryUnavailable
from title_core import COMMON


def title_icon(key):
    return '👑' if key in ('triple_rare', 'bond100', 'special_agent') or key.startswith('anniversary:') else '🎖️'


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
            text = '**称号獲得！**\n' + '\n'.join(f'{title_icon(key)} **{discord.utils.escape_markdown(COMMON.get(key, name))}**' for key, name in rows)
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
