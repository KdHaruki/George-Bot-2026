"""スラッシュコマンドの実行日時・利用者・引数をデータベースに記録する。"""

from contextlib import contextmanager
import json
import discord
from database import DatabaseStore, MemoryUnavailable
from history_writer import HistoryWriter


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
            # 接続・タイムアウトは他の保存処理と同じ DatabaseStore に統一する。
            with super().connect() as connection:
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



class CommandHistory(HistoryWriter):
    """履歴保存を非同期化し、DB障害や混雑で会話を止めない。"""
    feature = 'コマンド履歴DB'
    def __init__(self, store=None):
        super().__init__(store if store is not None else CommandHistoryStore())

    def observe(self, interaction):
        if interaction.type != discord.InteractionType.application_command or not self.store.url:
            return
        self.schedule(command_record(interaction))
