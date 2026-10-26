"""Incoming messages addressed to George; no public reader or AI retrieval."""
from contextlib import contextmanager

from command_history import CommandHistory
from database import DatabaseStore


class MessageHistoryStore(DatabaseStore):
    @contextmanager
    def connect(self):
        with super().connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS george_message_history (
                message_id BIGINT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
                user_id BIGINT NOT NULL, user_name TEXT NOT NULL,
                guild_id BIGINT, channel_id BIGINT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('dm','mention','reply')),
                content TEXT NOT NULL, reply_to_message_id BIGINT)''')
            connection.execute('''CREATE INDEX IF NOT EXISTS george_message_history_date
                ON george_message_history(created_at)''')
            yield connection

    def save(self, record):
        with self.connect() as connection:
            connection.execute('''INSERT INTO george_message_history
                (message_id,created_at,user_id,user_name,guild_id,channel_id,kind,content,reply_to_message_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(message_id) DO NOTHING''', record)
            deleted = connection.execute("DELETE FROM george_message_history WHERE created_at < now() - interval '30 days'").rowcount
        return deleted


class MessageHistory(CommandHistory):
    label = 'Message history'
    feature = '受信メッセージDB'

    def __init__(self, store=None):
        super().__init__(store if store is not None else MessageHistoryStore())

    def observe(self, message, kind):
        if not self.store.url or message.author.bot:
            return
        if kind not in ('dm', 'mention', 'reply'):
            raise ValueError('Invalid addressed-message kind')
        guild = getattr(message, 'guild', None)
        reference = getattr(message, 'reference', None)
        self.schedule((message.id, message.created_at, message.author.id, str(message.author)[:100],
                       guild.id if guild is not None else None, message.channel.id, kind,
                       message.content or '', getattr(reference, 'message_id', None)))
