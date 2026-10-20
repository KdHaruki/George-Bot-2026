"""Permanent achievements, updated in the same transactions as their triggers."""
import json

from progress_profiles import character_key
from present_catalog import NORMAL_ITEMS


COMMON = {
    'quiz10': '青蘭学園の知恵袋', 'quiz100': '青蘭学園の秘密兵器',
    'fortune10': '今日も神頼み', 'great10': '幸運を引き寄せし者',
    'support': 'エール・フレンドを受けし者', 'gift10': '青蘭学園のメッセンジャー',
    'variety': '青蘭学園のソムリエ',
    'bond10': 'エール・フレンドを繋ぎし者', 'bond100': 'エルエルを超えし者',
    'worlds': '世界の秘密を知る者', 'reunion': '青蘭学園の時間超越者',
    'triple_rare': '奇跡を束ねし者',
    'quiz_streak10': '青蘭学園の名探偵',
    'fortune_all': '運命を巡りし者',
    'special_agent': '青蘭学園の特命係',
    'ambassador': '青蘭学園の親善大使', 'profile30': '青蘭学園の情報通',
}
SPECIAL_AGENT_REQUIREMENTS = frozenset(('profile30', 'quiz_streak10', 'gift10'))
NORMAL_GIFTS = frozenset(NORMAL_ITEMS)
FORTUNE_TYPES = frozenset(('大吉', '吉', '中吉', '小吉', '末吉', '凶'))


def title_condition(key):
    conditions = {
        'special_agent': '「青蘭学園の情報通」「青蘭学園の名探偵」「青蘭学園のメッセンジャー」をすべて獲得する',
        'quiz10': 'クイズをヒント1回目で正解した回数を累計10回',
        'quiz100': 'クイズをヒント1回目で正解した回数を累計100回',
        'quiz_streak10': 'クイズをヒント1回目で正解して10回連続達成',
        'fortune10': 'おみくじを累計10回',
        'fortune_all': 'おみくじで6種類の運勢をすべて引く',
        'great10': '大吉を累計10回',
        'support': 'おみくじの応援ボーナスを初めて獲得',
        'gift10': 'プレゼントを累計10回贈る',
        'variety': f'通常プレゼント全{len(NORMAL_GIFTS)}種類を贈る（相手を問わず）',
        'worlds': '5つの世界を検索する',
        'reunion': 'ガチャでお気に入り本人のUR・★3を引く',
        'triple_rare': '1回のガチャでURまたは★3を3枚以上引く',
        'bond10': '異なる5人の好感度を100にする',
        'bond100': '異なる100人の好感度を100にする',
        'ambassador': '5つの世界から各1人、お気に入りに登録したことがある',
        'profile30': '異なる10人のプロフィールを名前で検索する',
    }
    kind, _, character = key.partition(':')
    if character:
        if kind == 'favorite_gift':
            return f'{character}に喜ばれる贈り物を初めて贈る（通常品）'
        if kind == 'affection':
            return f'{character}の好感度100の状態で喜ばれる贈り物を贈る'
        if kind == 'anniversary':
            return f'{character}をお気に入りに設定して1年が経つ（プログレスの変更または解除でリセット）'
    return conditions.get(key, '取得条件を確認できません。')


def pending_titles(earned, state, affection_count, character=None, days=0):
    """Display actual counters; binary milestones are represented as conditions."""
    rows = []

    def add(key, name, condition):
        if key not in earned:
            rows.append((key, name, condition))

    for key, metric, target, label in (
        ('quiz10', 'quiz_first', 10, 'クイズをヒント1回目で正解'),
        ('quiz100', 'quiz_first', 100, 'クイズをヒント1回目で正解')):
        add(key, COMMON[key], f'{label}：{min(state.get(metric, 0), target)}/{target}回')
    add('quiz_streak10', COMMON['quiz_streak10'], f'クイズをヒント1回目で正解して10回連続達成：{min(state.get("quiz_streak", 0), 10)}/10回')
    for key, metric, target, label in (
        ('fortune10', 'fortunes', 10, 'おみくじ'),
        ('great10', 'great', 10, '大吉')):
        add(key, COMMON[key], f'{label}：{min(state.get(metric, 0), target)}/{target}回')
    add('special_agent', COMMON['special_agent'], title_condition('special_agent') + f'：{len(earned & SPECIAL_AGENT_REQUIREMENTS)}/3称号')
    add('support', COMMON['support'], 'おみくじの応援ボーナスを初めて獲得')
    add('fortune_all', COMMON['fortune_all'], f'6種類の運勢をすべて引く：{len(set(state.get("fortunes_seen", [])) & FORTUNE_TYPES)}/6種類')
    add('gift10', COMMON['gift10'], f'プレゼントを贈る：{min(state.get("gifts", 0), 10)}/10回')
    add('variety', COMMON['variety'], f'通常プレゼント全{len(NORMAL_GIFTS)}種類を贈る：{len(set(state.get("gift_kinds", [])) & NORMAL_GIFTS)}/{len(NORMAL_GIFTS)}種類')
    add('worlds', COMMON['worlds'], f'5つの世界を検索：{len(set(state.get("worlds", [])) & set("青黒赤白緑"))}/5世界')
    add('reunion', COMMON['reunion'], 'ガチャで現在のお気に入り本人のUR・★3を引く')
    add('triple_rare', COMMON['triple_rare'], '1回のガチャでURまたは★3を3枚以上引く')
    add('ambassador', COMMON['ambassador'], f'5つの世界から各1人、お気に入りに登録する：{len(set(state.get("favorite_worlds", [])) & set("青黒赤白緑"))}/5世界')
    add('profile30', COMMON['profile30'], f'異なる10人のプロフィールを名前で検索する：{min(len(set(state.get("profile_names", []))), 10)}/10人')
    for target, key in ((5, 'bond10'), (100, 'bond100')):
        add(key, COMMON[key], f'異なる{target}人の好感度を100にする：{min(affection_count, target)}/{target}人')
    if character:
        add(f'favorite_gift:{character}', f'{character}の理解者', '喜ばれる贈り物を初めて贈る（通常品）')
        add(f'affection:{character}', f'{character}の良き理解者', '好感度100の状態で喜ばれる贈り物を贈る')
        add(f'anniversary:{character}', f'{character}の右腕', f'お気に入りに設定して1年が経つ：{min(days, 365)}/365日（プログレスの変更または解除でリセット）')
    return rows


def ensure_titles(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS george_quiz_rounds (
        user_id BIGINT PRIMARY KEY, round_id BIGINT NOT NULL,
        expires_at BIGINT NOT NULL, resolved BIGINT NOT NULL DEFAULT 0)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_title_notices (
        user_id BIGINT NOT NULL, title_key TEXT NOT NULL, name TEXT NOT NULL,
        claimed_until BIGINT NOT NULL DEFAULT 0, claim_token TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(user_id,title_key))''')
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
    name = name or COMMON[key]
    inserted = connection.execute('''INSERT INTO george_titles(user_id,title_key,name) VALUES (%s,%s,%s)
        ON CONFLICT(user_id,title_key) DO NOTHING RETURNING title_key''', (user_id, key, name)).fetchone()
    if inserted:
        connection.execute('''INSERT INTO george_title_notices(user_id,title_key,name) VALUES (%s,%s,%s)
            ON CONFLICT(user_id,title_key) DO NOTHING''', (user_id, key, name))
    if key in SPECIAL_AGENT_REQUIREMENTS:
        refresh_special_agent(connection, user_id)


def refresh_special_agent(connection, user_id):
    earned = {row[0] for row in connection.execute('SELECT title_key FROM george_titles WHERE user_id=%s', (user_id,)).fetchall()}
    if SPECIAL_AGENT_REQUIREMENTS <= earned and 'special_agent' not in earned:
        grant(connection, user_id, 'special_agent')


def event_result(state, kind, facts):
    state = dict(state)
    unlocked = []

    def count(metric, thresholds):
        state[metric] = state.get(metric, 0) + 1
        unlocked.extend((key, COMMON[key]) for limit, key in thresholds if state[metric] >= limit)

    if kind == 'quiz_streak':
        state['quiz_streak'] = state.get('quiz_streak', 0) + 1 if facts['correct_first'] else 0
        if state['quiz_streak'] >= 10:
            unlocked.append(('quiz_streak10', COMMON['quiz_streak10']))
    elif kind == 'quiz' and facts['attempts'] == 1:
        count('quiz_first', ((10, 'quiz10'), (100, 'quiz100')))
    elif kind == 'fortune':
        count('fortunes', ((10, 'fortune10'),))
        seen = set(state.get('fortunes_seen', [])) & FORTUNE_TYPES
        if facts['fortune'] in FORTUNE_TYPES:
            seen.add(facts['fortune'])
        state['fortunes_seen'] = sorted(seen)
        if seen >= FORTUNE_TYPES:
            unlocked.append(('fortune_all', COMMON['fortune_all']))
        if facts['fortune'] == '大吉':
            count('great', ((10, 'great10'),))
        if facts.get('bonus'):
            count('support_matches', ())
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
    elif kind == 'world':
        worlds = set(state.get('worlds', []))
        if facts['world'] in tuple('青黒赤白緑'):
            worlds.add(facts['world'])
        state['worlds'] = sorted(worlds)
        if worlds >= set('青黒赤白緑'):
            unlocked.append(('worlds', COMMON['worlds']))
    elif kind == 'reunion':
        unlocked.append(('reunion', COMMON['reunion']))
    elif kind == 'triple_rare' and facts['count'] >= 3:
        unlocked.append(('triple_rare', COMMON['triple_rare']))
    elif kind == 'favorite_world':
        worlds = set(state.get('favorite_worlds', []))
        if facts['world'] in '青黒赤白緑' and len(facts['world']) == 1:
            worlds.add(facts['world'])
        state['favorite_worlds'] = sorted(worlds)
        if worlds >= set('青黒赤白緑'):
            unlocked.append(('ambassador', COMMON['ambassador']))
    elif kind == 'profile_search':
        people = set(state.get('profile_names', []))
        people.add(character_key(facts['character']))
        state['profile_names'] = sorted(people)
        if len(people) >= 10:
            unlocked.append(('profile30', COMMON['profile30']))
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
    for count, key in ((5, 'bond10'), (100, 'bond100')):
        if len(characters) >= count and key not in existing:
            grant(connection, user_id, key)
