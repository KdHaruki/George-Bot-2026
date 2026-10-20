"""First occurrence milestones; dates are displayed in Japan time."""
from datetime import datetime, timedelta, timezone

from progress_profiles import character_key
from functools import lru_cache


JST = timezone(timedelta(hours=9))


def ensure_album(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS george_character_completions (
        user_id BIGINT NOT NULL, character TEXT NOT NULL,
        achieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id,character))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_favorite_album (
        user_id BIGINT NOT NULL, character TEXT NOT NULL,
        first_registered_at TIMESTAMPTZ, first_gift_at TIMESTAMPTZ, max_affection_at TIMESTAMPTZ,
        PRIMARY KEY(user_id,character))''')


@lru_cache(maxsize=1)
def collection_targets():
    from gacha import Gacha
    targets = {}
    for game, pools in Gacha().pools.items():
        for cards in pools.values():
            for card in cards:
                targets.setdefault(character_key(card.character), set()).add((game, card.id))
    return targets


def record_completions(connection, user_id, characters):
    targets = collection_targets()
    people = {character_key(name) for name in characters}
    if not people:
        return
    owned = set(connection.execute('SELECT game,card_id FROM george_gacha_cards WHERE user_id=%s', (user_id,)).fetchall())
    for person in people:
        required = targets.get(person)
        if required and required <= owned:
            connection.execute('''INSERT INTO george_character_completions(user_id,character)
                VALUES (%s,%s) ON CONFLICT(user_id,character) DO NOTHING''', (user_id, person))


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
    milestones = ((0, 'お気に入り登録日'), (4, 'カード全種類収集'), (3, 'パーフェクトリンク達成'))
    lines = []
    for index, label in milestones:
        value = dates[index] if index < len(dates) else None
        day = value.astimezone(JST).strftime('%Y年%m月%d日') if isinstance(value, datetime) else '未記録'
        lines.append(f'{label}：{day}')
    return '\n'.join(lines)
