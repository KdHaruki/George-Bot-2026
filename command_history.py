"""Bounded slash-command audit records; no message or DM bodies."""
import asyncio
from contextlib import contextmanager
import json
import logging
import discord
from discord import app_commands
from registered_memory import MemoryStore, MemoryUnavailable


def command_record(interaction):
    data = interaction.data or {}
    names = [data.get('name', '')]
    arguments = {}

    def visit(options):
        for option in options or []:
            if option.get('type') in (1, 2):
                names.append(option['name'])
                visit(option.get('options'))
            elif 'value' in option:
                arguments[option['name'][:32]] = str(option['value'])[:200]

    visit(data.get('options'))
    return (interaction.id, interaction.created_at, interaction.user.id,
            str(interaction.user)[:100], interaction.guild_id, interaction.channel_id,
            ' '.join(names)[:100], json.dumps(arguments, ensure_ascii=False))


class CommandHistoryStore(MemoryStore):
    @contextmanager
    def connect(self):
        if not self.url:
            raise MemoryUnavailable('履歴の保存にはDATABASE_URLが必要だぜ。')
        try:
            import psycopg
            with psycopg.connect(self.url, connect_timeout=10) as connection:
                connection.execute("SET LOCAL statement_timeout = '10s'")
                connection.execute('''CREATE TABLE IF NOT EXISTS george_command_history (
                    interaction_id BIGINT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
                    user_id BIGINT NOT NULL, user_name TEXT NOT NULL,
                    guild_id BIGINT, channel_id BIGINT, command TEXT NOT NULL, arguments JSONB NOT NULL)''')
                connection.execute('CREATE INDEX IF NOT EXISTS george_command_history_date ON george_command_history(created_at DESC,interaction_id DESC)')
                yield connection
        except MemoryUnavailable:
            raise
        except Exception:
            raise MemoryUnavailable('コマンド履歴の保存先を利用できなかったぜ。') from None

    def save(self, record):
        with self.connect() as connection:
            connection.execute('''INSERT INTO george_command_history VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(interaction_id) DO NOTHING''', record)
            connection.execute("DELETE FROM george_command_history WHERE created_at < now() - interval '30 days'")

    def recent(self, user_id=None):
        with self.connect() as connection:
            return connection.execute('''SELECT created_at,user_id,user_name,guild_id,channel_id,command,arguments
                FROM george_command_history WHERE created_at >= now() - interval '30 days'
                AND (%s::bigint IS NULL OR user_id=%s)
                ORDER BY created_at DESC,interaction_id DESC LIMIT 10''', (user_id, user_id)).fetchall()


class CommandHistory:
    def __init__(self, store=None):
        self.store = store if store is not None else CommandHistoryStore()
        self.slots = asyncio.Semaphore(2)
        self.tasks = set()

    def observe(self, interaction):
        if interaction.type != discord.InteractionType.application_command or not self.store.url:
            return
        if len(self.tasks) >= 32:
            logging.warning('Command history skipped: queue full')
            return
        record = command_record(interaction)

        async def save():
            try:
                async with self.slots:
                    await asyncio.to_thread(self.store.save, record)
            except Exception as exc:
                logging.warning('Command history save failed: type=%s', type(exc).__name__)

        task = asyncio.create_task(save())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self):
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


def register_command_history(bot):
    @bot.tree.command(name='コマンド履歴', description='コマンドの受付履歴を最新10件確認（Bot管理者用）')
    @app_commands.describe(ユーザー='指定したユーザーの履歴に絞り込む')
    async def history(interaction: discord.Interaction, ユーザー: discord.User = None):
        await interaction.response.defer(ephemeral=True)
        try:
            application = bot.application or await bot.application_info()
            owner_id = application.team.owner_id if application.team else application.owner.id
            if interaction.user.id != owner_id:
                await interaction.followup.send('Botの所有者だけが確認できるぜ。', ephemeral=True)
                return
            rows = await asyncio.to_thread(bot.command_history.store.recent, ユーザー.id if ユーザー else None)
            embed = discord.Embed(title='コマンド履歴（最新10件）', color=0xE2AD48)
            for created, uid, name, guild, channel, command, arguments in rows:
                arguments = arguments if isinstance(arguments, dict) else json.loads(arguments)
                options = ' '.join(f'{key}:{value}' for key, value in arguments.items())[:240]
                place = f'サーバー:{guild}／チャンネル:{channel}' if guild else 'DM'
                text = f'<t:{int(created.timestamp())}:f>\n/{command} {options}\n{place}'
                embed.add_field(name=discord.utils.escape_markdown(f'{name}（{uid}）')[:120],
                                value=discord.utils.escape_markdown(text)[:400], inline=False)
            if not rows:
                embed.description = '履歴はまだないぜ。'
            embed.set_footer(text='過去30日間の受付履歴。実行の成功・失敗を表すものではありません。')
            await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except MemoryUnavailable as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
