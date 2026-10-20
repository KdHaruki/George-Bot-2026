"""Permanent achievements, updated in the same transactions as their triggers."""
import json

from progress_profiles import character_key
from present_catalog import NORMAL_ITEMS


RETIRED_TITLES = frozenset(('exchange10', 'quiz100', 'great10', 'special_agent', 'fortune_all',
                              'gift10', 'ambassador', 'profile30', 'royal_flush', 'bond100', 'triple_rare'))


def is_retired_title(key):
    return key in RETIRED_TITLES or key.startswith(('collection:', 'affection:', 'anniversary:'))


COMMON = {
    'quiz10': '青蘭学園の知恵袋', 'quiz_streak10': '青蘭学園の名探偵',
    'fortune10': '今日も神頼み', 'support': 'エール・フレンドを受けし者',
    'variety': '青蘭学園のソムリエ',
    'bond10': 'エール・フレンドを繋ぎし者',
    'worlds': '世界の秘密を知る者', 'idol_producer': '青蘭学園のアイドルプロデューサー', 'reunion': '青蘭学園の時間超越者',
    'all_green': '青蘭学園の叛逆者',
}
def current_title_name(key, fallback):
    if key.startswith('favorite_gift:'):
        return f'{key.partition(":")[2]}の右腕'
    if key.startswith('preferred_gifts10:'):
        return f'{key.partition(":")[2]}の良き理解者'
    return COMMON.get(key, fallback)


NORMAL_GIFTS = frozenset(NORMAL_ITEMS)


def title_condition(key):
    conditions = {
        'quiz10': 'クイズをヒント1回目で正解した回数を累計10回',
        'quiz_streak10': 'クイズをヒント1回目で正解（10回連続）',
        'fortune10': 'おみくじを累計10回',
        'support': 'おみくじの応援ボーナスを初めて獲得',
        'variety': f'通常プレゼント全{len(NORMAL_GIFTS)}種類を贈る（相手を問わず）',
        'worlds': '5つの世界を検索する',
        'idol_producer': 'ヴィエルジュ7連でURの小鳥遊希美を引く',
        'reunion': 'ガチャでお気に入り本人のUR・★3を引く',
        'all_green': '1回のガチャで引いたプログレスがすべて緑の世界',
        'bond10': '異なる5人の好感度を100にする',
    }
    kind, _, character = key.partition(':')
    if character:
        if kind == 'favorite_gift':
            return '好感度100で喜ばれる贈り物を贈る'
        if kind == 'preferred_gifts10':
            return f'{character}に喜ばれる贈り物を累計10個贈る（通常品）'
    return conditions.get(key, '取得条件を確認できません。')


def pending_titles(earned, state, affection_count, character=None):
    """Display actual counters; binary milestones are represented as conditions."""
    rows = []

    def add(key, name, condition):
        if key not in earned:
            rows.append((key, name, condition))

    for key, metric, target, label in (
        ('quiz10', 'quiz_first', 10, 'クイズをヒント1回目で正解'),):
        add(key, COMMON[key], f'{label}：{min(state.get(metric, 0), target)}/{target}回')
    add('quiz_streak10', COMMON['quiz_streak10'], f'クイズをヒント1回目で正解（10回連続）：{min(state.get("quiz_streak", 0), 10)}/10回')
    for key, metric, target, label in (
        ('fortune10', 'fortunes', 10, 'おみくじ'),):
        add(key, COMMON[key], f'{label}：{min(state.get(metric, 0), target)}/{target}回')
    add('support', COMMON['support'], 'おみくじの応援ボーナスを初めて獲得')
    add('variety', COMMON['variety'], f'通常プレゼント全{len(NORMAL_GIFTS)}種類を贈る：{len(set(state.get("gift_kinds", [])) & NORMAL_GIFTS)}/{len(NORMAL_GIFTS)}種類')
    if character:
        gifts = state.get('preferred_gift_counts', {}).get(character_key(character), 0)
        add(f'preferred_gifts10:{character}', f'{character}の良き理解者', f'喜ばれる贈り物を贈る：{min(gifts, 10)}/10個')
    add('worlds', COMMON['worlds'], f'5つの世界を検索：{len(set(state.get("worlds", [])) & set("青黒赤白緑"))}/5世界')
    add('idol_producer', COMMON['idol_producer'], title_condition('idol_producer'))
    add('reunion', COMMON['reunion'], 'ガチャで現在のお気に入り本人のUR・★3を引く')
    add('all_green', COMMON['all_green'], title_condition('all_green'))
    for target, key in ((5, 'bond10'),):
        add(key, COMMON[key], f'異なる{target}人の好感度を100にする：{min(affection_count, target)}/{target}人')
    if character:
        add(f'favorite_gift:{character}', f'{character}の右腕', '好感度100で喜ばれる贈り物を贈る')
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


def grant(connection, user_id, key, name=None):
    if is_retired_title(key):
        return
    name = current_title_name(key, name or COMMON.get(key, key))
    inserted = connection.execute('''INSERT INTO george_titles(user_id,title_key,name) VALUES (%s,%s,%s)
        ON CONFLICT(user_id,title_key) DO NOTHING RETURNING title_key''', (user_id, key, name)).fetchone()
    if inserted:
        connection.execute('''INSERT INTO george_title_notices(user_id,title_key,name) VALUES (%s,%s,%s)
            ON CONFLICT(user_id,title_key) DO NOTHING''', (user_id, key, name))


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
        count('quiz_first', ((10, 'quiz10'),))
    elif kind == 'fortune':
        count('fortunes', ((10, 'fortune10'),))
        if facts.get('bonus'):
            count('support_matches', ())
            unlocked.append(('support', COMMON['support']))
    elif kind == 'gift':
        item = facts['item']
        kinds = set(state.get('gift_kinds', []))
        if item in NORMAL_GIFTS:
            kinds.add(item)
        state['gift_kinds'] = sorted(kinds)
        if kinds >= NORMAL_GIFTS:
            unlocked.append(('variety', COMMON['variety']))
        if facts.get('preferred') and item in NORMAL_GIFTS:
            character = character_key(facts['character'])
            counts = dict(state.get('preferred_gift_counts', {}))
            counts[character] = counts.get(character, 0) + 1
            state['preferred_gift_counts'] = counts
            if counts[character] >= 10:
                unlocked.append((f'preferred_gifts10:{character}', f'{character}の良き理解者'))
        if facts.get('preferred') and item in NORMAL_GIFTS and facts.get('first_perfect_link'):
            character = character_key(facts['character'])
            unlocked.append((f'favorite_gift:{character}', f'{character}の右腕'))
    elif kind == 'world':
        worlds = set(state.get('worlds', []))
        if facts['world'] in tuple('青黒赤白緑'):
            worlds.add(facts['world'])
        state['worlds'] = sorted(worlds)
        if worlds >= set('青黒赤白緑'):
            unlocked.append(('worlds', COMMON['worlds']))
    elif kind == 'idol_producer' and facts.get('game') == 'vierge' and facts.get('count') == 7 and facts.get('rarity') == 'UR' and character_key(facts.get('character', '')) == '小鳥遊希美':
        unlocked.append(('idol_producer', COMMON['idol_producer']))
    elif kind == 'reunion':
        unlocked.append(('reunion', COMMON['reunion']))
    elif kind == 'all_green' and facts.get('game') in ('vierge', 'relink') and facts.get('count') == (7 if facts['game'] == 'vierge' else 10) and facts.get('worlds') == ['緑']:
        unlocked.append(('all_green', COMMON['all_green']))
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


def refresh_perfect_titles(connection, user_id):
    people = connection.execute('SELECT character FROM george_perfect_links WHERE user_id=%s', (user_id,)).fetchall()
    existing = {row[0] for row in connection.execute('SELECT title_key FROM george_titles WHERE user_id=%s', (user_id,)).fetchall()}
    for (character,) in people:
        character = character_key(character)
        if f'favorite_gift:{character}' not in existing:
            grant(connection, user_id, f'favorite_gift:{character}', f'{character}の右腕')


def refresh_affection(connection, user_id):
    refresh_perfect_titles(connection, user_id)
    rows = connection.execute('SELECT character FROM george_affection WHERE user_id=%s AND points>=100', (user_id,)).fetchall()
    characters = {character_key(row[0]) for row in rows}
    existing = {row[0] for row in connection.execute('SELECT title_key FROM george_titles WHERE user_id=%s', (user_id,)).fetchall()}
    for count, key in ((5, 'bond10'),):
        if len(characters) >= count and key not in existing:
            grant(connection, user_id, key)
