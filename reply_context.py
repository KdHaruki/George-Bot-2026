import discord


async def george_reply_target(message, bot_id):
    reference = message.reference
    if reference is None or reference.channel_id != message.channel.id:
        return None
    if getattr(reference, "type", discord.MessageReferenceType.reply) != discord.MessageReferenceType.reply:
        return None
    target = reference.resolved
    if getattr(target, "author", None) is None:
        if not reference.message_id:
            return None
        try:
            target = await message.channel.fetch_message(reference.message_id)
        except discord.HTTPException:
            return None
    return target if target.author.id == bot_id else None
