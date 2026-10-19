"""First occurrence milestones; dates are displayed in Japan time."""
from datetime import datetime, timedelta, timezone

from progress_profiles import character_key


JST = timezone(timedelta(hours=9))


def ensure_album(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS george_favorite_album (
        user_id BIGINT NOT NULL, character TEXT NOT NULL,
        first_registered_at TIMESTAMPTZ, first_gift_at TIMESTAMPTZ, max_affection_at TIMESTAMPTZ,
        PRIMARY KEY(user_id,character))''')


def record_registration(connection, user_id, character):
    connection.execute('''INSERT INTO george_favorite_album(user_id,character,first_registered_at)
        VALUES (%s,%s,CURRENT_TIMESTAMP) ON CONFLICT(user_id,character) DO UPDATE SET
        first_registered_at=COALESCE(george_favorite_album.first_registered_at,EXCLUDED.first_registered_at)''',
        (user_id, character_key(character)))


def record_gift(connection, user_id, character, reached_max):
    connection.execute('''INSERT INTO george_favorite_album(user_id,character,first_gift_at,max_affection_at)
        VALUES (%s,%s,CURRENT_TIMESTAMP,CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END)
        ON CONFLICT(user_id,character) DO UPDATE SET
        first_gift_at=COALESCE(george_favorite_album.first_gift_at,EXCLUDED.first_gift_at),
        max_affection_at=COALESCE(george_favorite_album.max_affection_at,EXCLUDED.max_affection_at)''',
        (user_id, character_key(character), reached_max))


def album_display(dates):
    labels = ('初登録日', '初プレゼント', '好感度100達成')
    lines = []
    for label, value in zip(labels, dates):
        day = value.astimezone(JST).strftime('%Y年%m月%d日') if isinstance(value, datetime) else '未記録'
        lines.append(f'{label}：{day}')
    return '\n'.join(lines)
