"""Fetch bounded, same-channel context only after the participation lottery."""
import asyncio
import logging

import discord

from ambient_chat import SERIOUS

HISTORY_SCAN_LIMIT = 30
CONTEXT_LIMIT = 8


async def load_ambient_history(trigger):
    guild = getattr(trigger, 'guild', None)
    if guild is not None:
        if guild.me is None:
            return []
        permissions = trigger.channel.permissions_for(guild.me)
        if not permissions.view_channel or not permissions.read_message_history:
            return []

    async def collect():
        messages = []
        found_trigger = False
        # The upper bound prevents later messages being mixed into this attempt.
        async for message in trigger.channel.history(
                limit=HISTORY_SCAN_LIMIT, before=discord.Object(id=trigger.id + 1), oldest_first=False):
            if message.id == trigger.id:
                found_trigger = True
            if message.author.bot:
                continue
            text = message.content or ''
            attachments = tuple(message.attachments[:2])
            directed = bool(message.mentions or message.role_mentions or message.mention_everyone or message.reference)
            if directed or text.startswith(('/', '!', '?')):
                break
            if not text.strip() and not attachments:
                continue
            messages.append((message.created_at.timestamp(), message.author.id,
                             text[:500] or '[添付あり・まだ内容は未確認]', attachments))
            if len(messages) == CONTEXT_LIMIT:
                break
        messages.reverse()
        if not found_trigger or not messages:
            return []
        if any(word in item[2] for item in messages for word in SERIOUS):
            return []
        return messages

    try:
        return await asyncio.wait_for(collect(), timeout=10)
    except (discord.HTTPException, asyncio.TimeoutError) as exc:
        logging.warning('Ambient history skipped: type=%s', type(exc).__name__)
        return []
