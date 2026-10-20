"""Settle JST calendar-day affection without a polling task."""
from datetime import datetime, time, timedelta

from favorite_album import JST
from progress_profiles import character_key


MAX_AFFECTION = 100


def link_level(connection, user_id, character):
    params = (user_id, character_key(character))
    row = connection.execute('SELECT level FROM george_perfect_link_levels WHERE user_id=%s AND character=%s', params).fetchone()
    if row:
        return row[0]
    return int(connection.execute('SELECT 1 FROM george_perfect_links WHERE user_id=%s AND character=%s', params).fetchone() is not None)


def affection_limit(level):
    return (int(level) + 1) * MAX_AFFECTION


def today(connection):
    return connection.execute("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date").fetchone()[0]


def ensure_daily(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS george_perfect_links (
        user_id BIGINT NOT NULL, character TEXT NOT NULL,
        achieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id,character))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_perfect_link_levels (
        user_id BIGINT NOT NULL, character TEXT NOT NULL, level BIGINT NOT NULL CHECK(level>=1),
        achieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id,character))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_affection (
        user_id BIGINT NOT NULL, character TEXT NOT NULL, points BIGINT NOT NULL CHECK(points>=0),
        PRIMARY KEY(user_id,character))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_daily_affection (
        user_id BIGINT PRIMARY KEY, character TEXT NOT NULL, last_day DATE NOT NULL)''')


def seed_daily(connection):
    key = ('favorite-daily-v1',)
    query = 'SELECT 1 FROM george_gacha_migrations WHERE name=%s'
    if connection.execute(query, key).fetchone():
        return
    connection.execute("SELECT pg_advisory_xact_lock(hashtext('george-favorite-daily-v1'))")
    if connection.execute(query, key).fetchone():
        return
    day = today(connection)
    rows = connection.execute('''SELECT f.user_id,c.card FROM george_gacha_favorites f
        JOIN george_gacha_cards c ON (c.user_id,c.game,c.card_id)=(f.user_id,f.game,f.card_id)''').fetchall()
    for user_id, payload in rows:
        connection.execute('''INSERT INTO george_daily_affection VALUES (%s,%s,%s)
            ON CONFLICT(user_id) DO NOTHING''', (user_id, character_key(payload['character']), day))
    connection.execute('INSERT INTO george_gacha_migrations(name) VALUES (%s)', key)


def start_daily(connection, user_id, character):
    if character is None:
        connection.execute('DELETE FROM george_daily_affection WHERE user_id=%s', (user_id,))
        return
    connection.execute('''INSERT INTO george_daily_affection VALUES (%s,%s,%s)
        ON CONFLICT(user_id) DO UPDATE SET
        last_day=CASE WHEN george_daily_affection.character=EXCLUDED.character
            THEN george_daily_affection.last_day ELSE EXCLUDED.last_day END,
        character=EXCLUDED.character''', (user_id, character_key(character), today(connection)))


def settle_daily(connection, user_id):
    # All callers hold the same user transaction lock as gifts and favorite changes.
    row = connection.execute('SELECT character,last_day FROM george_daily_affection WHERE user_id=%s', (user_id,)).fetchone()
    if row is None:
        favorite = connection.execute('''SELECT c.card FROM george_gacha_favorites f
            JOIN george_gacha_cards c ON (c.user_id,c.game,c.card_id)=(f.user_id,f.game,f.card_id)
            WHERE f.user_id=%s''', (user_id,)).fetchone()
        if favorite:
            start_daily(connection, user_id, favorite[0]['character'])
        return 0
    character, previous = character_key(row[0]), row[1]
    day = today(connection)
    days = (day - previous).days
    if days <= 0:
        return 0
    points_row = connection.execute('SELECT points FROM george_affection WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
    limit = affection_limit(link_level(connection, user_id, character))
    before = min(limit, points_row[0]) if points_row else 0
    gain = min(days, limit - before)
    if gain:
        connection.execute('''INSERT INTO george_affection VALUES (%s,%s,%s)
            ON CONFLICT(user_id,character) DO UPDATE SET points=EXCLUDED.points''', (user_id, character, before + gain))
        if before < MAX_AFFECTION <= before + gain:
            reached = datetime.combine(previous + timedelta(days=MAX_AFFECTION - before), time.min, JST)
            connection.execute('''INSERT INTO george_favorite_album(user_id,character,max_affection_at)
                VALUES (%s,%s,%s) ON CONFLICT(user_id,character) DO UPDATE SET
                max_affection_at=COALESCE(george_favorite_album.max_affection_at,EXCLUDED.max_affection_at)''',
                (user_id, character, reached))
    connection.execute('UPDATE george_daily_affection SET last_day=%s WHERE user_id=%s', (day, user_id))
    return gain
