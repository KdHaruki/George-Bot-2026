"""Permanent achievements, updated in the same transactions as their triggers."""
import json

from progress_profiles import character_key


COMMON = {
    'quiz10': '青蘭学園の知恵袋', 'quiz100': '青蘭学園の秘密兵器',
    'fortune10': '今日も神頼み', 'great10': '幸運を引き寄せし者',
    'support': 'エール・フレンドを受けし者', 'gift10': '想いを届ける者',
    'variety': '贈り物のソムリエ', 'exchange10': '贈り物コーディネーター',
    'bond10': 'エール・フレンドを繋ぎし者', 'bond100': 'エルエルを超えし者',
    'worlds': '世界の秘密を知る者', 'reunion': '奇跡の再会を手繰り寄せし者',
}
NORMAL_GIFTS = frozenset(('sweets', 'food', 'fashion', 'book', 'game', 'magic'))


def ensure_titles(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS george_titles (
        user_id BIGINT NOT NULL, title_key TEXT NOT NULL, name TEXT NOT NULL,
        acquired_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id,title_key))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_title_stats (
        user_id BIGINT PRIMARY KEY, data TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_title_events (
        user_id BIGINT NOT NULL, event_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id,event_key))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_title_streaks (
        user_id BIGINT PRIMARY KEY, character TEXT NOT NULL, since TIMESTAMPTZ NOT NULL)''')


def seed_existing_streaks(connection):
    key = ('title-streaks-v1',)
    query = 'SELECT 1 FROM george_gacha_migrations WHERE name=%s'
    if connection.execute(query, key).fetchone():
        return
    connection.execute("SELECT pg_advisory_xact_lock(hashtext('george-title-streaks-v1'))")
    if connection.execute(query, key).fetchone():
        return
    rows = connection.execute('''SELECT f.user_id,c.card FROM george_gacha_favorites f
        JOIN george_gacha_cards c ON (c.user_id,c.game,c.card_id)=(f.user_id,f.game,f.card_id)''').fetchall()
    for user_id, payload in rows:
        connection.execute('''INSERT INTO george_title_streaks VALUES (%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO NOTHING''', (user_id, character_key(payload['character'])))
    connection.execute('INSERT INTO george_gacha_migrations(name) VALUES (%s)', key)


def grant(connection, user_id, key, name=None):
    connection.execute('''INSERT INTO george_titles(user_id,title_key,name) VALUES (%s,%s,%s)
        ON CONFLICT(user_id,title_key) DO NOTHING''', (user_id, key, name or COMMON[key]))


def event_result(state, kind, facts):
    state = dict(state)
    unlocked = []

    def count(metric, thresholds):
        state[metric] = state.get(metric, 0) + 1
        unlocked.extend((key, COMMON[key]) for limit, key in thresholds if state[metric] >= limit)

    if kind == 'quiz' and facts['attempts'] == 1:
        count('quiz_first', ((10, 'quiz10'), (100, 'quiz100')))
    elif kind == 'fortune':
        count('fortunes', ((10, 'fortune10'),))
        if facts['fortune'] == '大吉':
            count('great', ((10, 'great10'),))
        if facts.get('bonus'):
            unlocked.append(('support', COMMON['support']))
    elif kind == 'gift':
        count('gifts', ((10, 'gift10'),))
        item = facts['item']
        kinds = set(state.get('gift_kinds', []))
        if item in NORMAL_GIFTS:
            kinds.add(item)
        state['gift_kinds'] = sorted(kinds)
        if kinds >= NORMAL_GIFTS:
            unlocked.append(('variety', COMMON['variety']))
        if facts.get('preferred') and item in NORMAL_GIFTS:
            character = character_key(facts['character'])
            unlocked.append((f'favorite_gift:{character}', f'{character}の理解者'))
    elif kind == 'exchange':
        count('exchanges', ((10, 'exchange10'),))
    elif kind == 'world':
        worlds = set(state.get('worlds', []))
        if facts['world'] in tuple('青黒赤白緑'):
            worlds.add(facts['world'])
        state['worlds'] = sorted(worlds)
        if worlds >= set('青黒赤白緑'):
            unlocked.append(('worlds', COMMON['worlds']))
    elif kind == 'reunion':
        unlocked.append(('reunion', COMMON['reunion']))
    return state, unlocked


def record_event(connection, user_id, event_key, kind, **facts):
    inserted = connection.execute('''INSERT INTO george_title_events(user_id,event_key) VALUES (%s,%s)
        ON CONFLICT(user_id,event_key) DO NOTHING RETURNING event_key''', (user_id, event_key)).fetchone()
    if not inserted:
        return
    row = connection.execute('SELECT data FROM george_title_stats WHERE user_id=%s', (user_id,)).fetchone()
    state, unlocked = event_result(json.loads(row[0]) if row else {}, kind, facts)
    connection.execute('''INSERT INTO george_title_stats VALUES (%s,%s)
        ON CONFLICT(user_id) DO UPDATE SET data=EXCLUDED.data''', (user_id, json.dumps(state, ensure_ascii=False)))
    for key, name in unlocked:
        grant(connection, user_id, key, name)
    connection.execute("DELETE FROM george_title_events WHERE user_id=%s AND created_at<CURRENT_TIMESTAMP-INTERVAL '7 days'", (user_id,))


def settle_streak(connection, user_id):
    row = connection.execute("SELECT character FROM george_title_streaks WHERE user_id=%s AND since<=CURRENT_TIMESTAMP-INTERVAL '365 days'", (user_id,)).fetchone()
    if row:
        character = character_key(row[0])
        grant(connection, user_id, f'anniversary:{character}', f'{character}の右腕')


def change_streak(connection, user_id, character):
    settle_streak(connection, user_id)
    if character is None:
        connection.execute('DELETE FROM george_title_streaks WHERE user_id=%s', (user_id,))
    else:
        connection.execute('''INSERT INTO george_title_streaks VALUES (%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
            since=CASE WHEN george_title_streaks.character=EXCLUDED.character
                THEN george_title_streaks.since ELSE EXCLUDED.since END,
            character=EXCLUDED.character''', (user_id, character_key(character)))


def refresh_affection(connection, user_id):
    rows = connection.execute('SELECT character FROM george_affection WHERE user_id=%s AND points>=100', (user_id,)).fetchall()
    characters = {character_key(row[0]) for row in rows}
    perfect = {character_key(row[0]) for row in connection.execute(
        'SELECT character FROM george_perfect_links WHERE user_id=%s', (user_id,)).fetchall()}
    existing = {row[0] for row in connection.execute('SELECT title_key FROM george_titles WHERE user_id=%s', (user_id,)).fetchall()}
    for character in perfect:
        if f'affection:{character}' not in existing:
            grant(connection, user_id, f'affection:{character}', f'{character}の良き理解者')
    for count, key in ((10, 'bond10'), (100, 'bond100')):
        if len(characters) >= count and key not in existing:
            grant(connection, user_id, key)
