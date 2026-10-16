"""Private incoming DM archive, accessible only to the application owner."""
import asyncio
import logging
import os
from contextlib import contextmanager
from datetime import timezone, timedelta

import discord
from discord import app_commands
from registered_memory import MemoryStore, MemoryUnavailable


class DMStore(MemoryStore):
    @contextmanager
    def connect(self):
        with super().connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS george_dm_messages (
                message_id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL,
                user_name TEXT NOT NULL, received_at TIMESTAMPTZ NOT NULL, content TEXT NOT NULL)''')
            connection.execute('CREATE INDEX IF NOT EXISTS george_dm_owner_date ON george_dm_messages(user_id,received_at DESC)')
            yield connection

    def save(self, message):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (message.author.id,))
            first = connection.execute('SELECT 1 FROM george_dm_messages WHERE user_id=%s LIMIT 1', (message.author.id,)).fetchone() is None
            connection.execute('''INSERT INTO george_dm_messages VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(message_id) DO NOTHING''',
                (message.id, message.author.id, str(message.author), message.created_at, message.content))
        return first

    def history(self, user_id, page):
        with self.connect() as connection:
            return connection.execute('''SELECT user_id,user_name,received_at,content FROM george_dm_messages
                WHERE (%s::bigint IS NULL OR user_id=%s) ORDER BY received_at DESC,message_id DESC
                LIMIT 5 OFFSET %s''', (user_id, user_id, (page - 1) * 5)).fetchall()


async def archive_dm(store, message):
    if message.guild is not None or message.author.bot:
        return
    try:
        first = await asyncio.to_thread(store.save, message)
        if first:
            await message.channel.send('このDMの本文・送信者・日時は保存され、Bot管理者が確認できるぜ。添付ファイル本体は保存しないぞ。')
    except MemoryUnavailable:
        logging.warning('DM archive unavailable')
        await message.channel.send('今はdm履歴を保存できなかったぜ。')
    except discord.HTTPException:
        logging.warning('DM archive notice unavailable')


def register_dm_history(bot, store):
    @bot.tree.command(name='dm履歴', description='Bot管理者専用：受信したDM本文を確認する')
    @app_commands.rename(ユーザーID='ユーザーid')
    @app_commands.describe(ユーザーID='省略で全員。DiscordのユーザーID', ページ='1ページ5件、新しい順')
    async def history(interaction: discord.Interaction, ユーザーID: str = None,
                      ページ: app_commands.Range[int, 1, 1000000] = 1):
        await interaction.response.defer(ephemeral=True)
        try:
            # Guild administrator privileges never grant access to private DMs.
            owners = {int(value.strip()) for value in os.getenv('BOT_OWNER_IDS', '').split(',') if value.strip().isdigit()}
            if not owners:
                application = await bot.application_info()
                owners = {application.team.owner_id if application.team else application.owner.id}
            if interaction.user.id not in owners:
                await interaction.followup.send('Bot管理者だけが確認できるコマンドだぜ。', ephemeral=True)
                return
            user_id = int(ユーザーID) if ユーザーID is not None else None
            if user_id is not None and not 0 < user_id < 2**63:
                raise ValueError()
            rows = await asyncio.to_thread(store.history, user_id, ページ)
        except ValueError:
            await interaction.followup.send('ユーザーIDはDiscordの数値IDで指定してくれ。', ephemeral=True)
            return
        except (MemoryUnavailable, discord.HTTPException):
            await interaction.followup.send('dm履歴を確認できなかったぜ。設定や接続を確認してくれ。', ephemeral=True)
            return
        embed = discord.Embed(title=f'dm履歴｜{ページ}ページ', description='新しい順・受信した本文のみ' if rows else '該当するDMはないぜ。')
        for uid, name, timestamp, content in rows:
            when = timestamp.astimezone(timezone(timedelta(hours=9))).strftime('%Y/%m/%d %H:%M')
            escaped = discord.utils.escape_mentions(discord.utils.escape_markdown(content or '（本文なし）'))
            if len(escaped) > 850:
                escaped = escaped[:850] + '\n（表示を省略。全文は添付）'
            embed.add_field(name=f'{name[:60]}｜{uid}｜{when}', value=escaped, inline=False)
        # Full bodies are provided as plain text, without activating links or mentions.
        import io
        attachments = []
        if rows:
            text = '\n\n'.join(f'{uid} {name} {timestamp.isoformat()}\n{content}' for uid, name, timestamp, content in rows)
            attachments = [discord.File(io.BytesIO(text.encode('utf-8')), filename='dm-history.txt')]
        await interaction.followup.send(embed=embed, files=attachments, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())
