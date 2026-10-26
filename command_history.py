"""Bounded slash-command audit records; no message or DM bodies."""
import asyncio
from contextlib import contextmanager
import json
import logging
import discord
from database import DatabaseStore, MemoryUnavailable
from operation_logging import event as log_event


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


class CommandHistoryStore(DatabaseStore):
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
            deleted = connection.execute("DELETE FROM george_command_history WHERE created_at < now() - interval '30 days'").rowcount
        return deleted



class CommandHistory:
    label = 'Command history'
    feature = 'コマンド履歴DB'
    def __init__(self, store=None):
        self.store = store if store is not None else CommandHistoryStore()
        self.slots = asyncio.Semaphore(2)
        self.tasks = set()

    def observe(self, interaction):
        if interaction.type != discord.InteractionType.application_command or not self.store.url:
            return
        self.schedule(command_record(interaction))

    def schedule(self, record):
        if not self.store.url:
            return
        if len(self.tasks) >= 32:
            log_event(self.feature, '保存見送り', reason='保存待ちが上限32件に到達', 記録ID=record[0])
            return

        async def save():
            try:
                async with self.slots:
                    deleted = await asyncio.to_thread(self.store.save, record)
                log_event(self.feature, '保存完了', 記録ID=record[0])
                if isinstance(deleted, int) and deleted > 0:
                    log_event(self.feature, '30日を過ぎた履歴を削除', 削除件数=deleted)
            except Exception as exc:
                log_event(self.feature, '保存失敗', error=exc, 記録ID=record[0])

        task = asyncio.create_task(save())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self):
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
