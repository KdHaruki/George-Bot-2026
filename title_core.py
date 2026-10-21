"""Permanent achievements, updated in the same transactions as their triggers."""
import json

from progress_profiles import character_key
from present_catalog import NORMAL_ITEMS


RETIRED_TITLES = frozenset(('exchange10', 'quiz100', 'great10', 'special_agent', 'fortune_all',
                              'gift10', 'ambassador', 'profile30', 'royal_flush', 'bond100', 'triple_rare', 'reaction', 'bad10', 'mischief_pair'))


def is_retired_title(key):
    return key in RETIRED_TITLES or key.startswith(('collection:', 'affection:', 'anniversary:'))


COMMON = {
    'quiz10': '青蘭学園の知恵袋', 'quiz_streak10': '青蘭学園の名探偵',
    'fortune10': '神頼み', 'fortune_set': '占い師', 'support': 'エール・フレンドを受けし者',
    'special_gift': '青蘭学園のロマンチスト', 'variety': 'ソムリエの証', 'worlds': '青蘭学園の歩く図書館', 'named10': '青蘭学園の勉強家',
    'bond10': 'エール・フレンドを繋ぎし者',
    'idol_producer': '青蘭学園のアイドルプロデューサー', 'favorite_registered': '青蘭学園の新米アルドラ', 'reunion': '青蘭学園の熟練アルドラ', 'favorite_complete': '青蘭学園の一流アルドラ',
    'all_green': '青蘭学園の叛逆者', 'kaguya': '青蘭学園のかぐや姫',
    'complete_vierge': '青蘭学園のレジェンド', 'complete_relink': '青蘭学園の英雄',
}
def current_title_name(key, fallback):
    if key.startswith('favorite_gift:'):
        return f'{key.partition(":")[2]}の右腕'
    if key.startswith('preferred_gifts10:'):
        return f'{key.partition(":")[2]}の良き理解者'
    return COMMON.get(key, fallback)


NORMAL_GIFTS = frozenset(NORMAL_ITEMS)
FORTUNE_TYPES = frozenset(('大吉', '吉', '中吉', '小吉', '末吉', '凶'))


def title_condition(key):
    conditions = {
        'worlds': '5つの世界を検索する。',
        'named10': 'プログレスを累計10人検索する。（世界別の検索は除く）',
        'favorite_registered': 'お気に入りを登録する。',
        'complete_vierge': 'ヴィエルジュの収集率100％を達成する。',
        'complete_relink': 'リリンクの収集率100％を達成する。',
        'quiz10': 'クイズをヒント1回目で累計10回正解する。',
        'quiz_streak10': 'クイズをヒント1回目で10回連続正解する。',
        'fortune10': 'おみくじに累計10回挑戦する。',
        'fortune_set': 'おみくじで全種類を取得する。',
        'support': 'おみくじの応援ボーナスを初めて獲得する。',
        'special_gift': '特別な贈り物をプレゼントする。',
        'variety': f'贈り物{len(NORMAL_GIFTS)}種類をプレゼントする。（特別な贈り物は除く）',
        'idol_producer': 'ガチャでURの小鳥遊希美を獲得する。',
        'reunion': 'ガチャでお気に入り本人のUR・★3を獲得する。',
        'favorite_complete': 'お気に入り本人のレアリティ・衣装を全て獲得する。',
        'all_green': '1回のガチャで緑の世界のプログレスを7枚以上引く。',
        'kaguya': 'おみくじで大吉を3回連続で引く。',
        'bond10': '異なる5人の好感度を100にする。',
    }
    kind, _, character = key.partition(':')
    if character:
        if kind == 'favorite_gift':
            return '好感度100の状態で喜ばれる贈り物をプレゼントする。'
        if kind == 'preferred_gifts10':
            return 'その子に喜ばれる贈り物を累計3個プレゼントする。（特別な贈り物は除く）'
    return conditions.get(key, '取得条件を確認できません。')


def pending_titles(earned, state, affection_count, character=None):
    """Display actual counters; binary milestones are represented as conditions."""
    rows = []

    def add(key, name, condition):
        if key not in earned:
            rows.append((key, name, condition))

    for key, metric, target, label in (
        ('quiz10', 'quiz_first', 10, 'クイズをヒント1回目で正解する'),):
        add(key, COMMON[key], f'{label}：{min(state.get(metric, 0), target)}/{target}回')
    add('quiz_streak10', COMMON['quiz_streak10'], f'クイズをヒント1回目で正解する（10回連続）：{min(state.get("quiz_streak", 0), 10)}/10回')
    for key, metric, target, label in (
        ('fortune10', 'fortunes', 10, 'おみくじに挑戦する'),):
        add(key, COMMON[key], f'{label}：{min(state.get(metric, 0), target)}/{target}回')
    add('fortune_set', COMMON['fortune_set'], title_condition('fortune_set') + f'\n進捗：{len(set(state.get("fortunes_seen", [])) & FORTUNE_TYPES)}/6種類')
    add('support', COMMON['support'], title_condition('support'))
    add('variety', COMMON['variety'], title_condition('variety') + f'\n進捗：{len(set(state.get("gift_kinds", [])) & NORMAL_GIFTS)}/{len(NORMAL_GIFTS)}種類')
    add('special_gift', COMMON['special_gift'], title_condition('special_gift'))
    if character:
        gifts = state.get('preferred_gift_counts', {}).get(character_key(character), 0)
        add(f'preferred_gifts10:{character}', f'{character}の良き理解者', title_condition(f'preferred_gifts10:{character}') + f'\n進捗：{min(gifts, 3)}/3個')
    add('worlds', COMMON['worlds'], f'5つの世界を検索する：{len(set(state.get("worlds", [])) & set("青黒赤白緑"))}/5世界')
    add('named10', COMMON['named10'], title_condition('named10') + f'\n進捗：{min(len({character_key(name) for name in state.get("profile_names", [])}), 10)}/10人')
    add('idol_producer', COMMON['idol_producer'], title_condition('idol_producer'))
    add('favorite_registered', COMMON['favorite_registered'], title_condition('favorite_registered'))
    add('reunion', COMMON['reunion'], title_condition('reunion'))
    add('favorite_complete', COMMON['favorite_complete'], title_condition('favorite_complete'))
    add('all_green', COMMON['all_green'], title_condition('all_green'))
    add('kaguya', COMMON['kaguya'], title_condition('kaguya') + f'\n進捗：{min(state.get("great_streak", 0), 3)}/3回')
    add('complete_vierge', COMMON['complete_vierge'], title_condition('complete_vierge'))
    add('complete_relink', COMMON['complete_relink'], title_condition('complete_relink'))
    for target, key in ((5, 'bond10'),):
        add(key, COMMON[key], f'異なる{target}人の好感度を100にする：{min(affection_count, target)}/{target}人')
    if character:
        add(f'favorite_gift:{character}', f'{character}の右腕', title_condition(f'favorite_gift:{character}'))
    return [(key, name, condition if condition.endswith('。') else condition + '。') for key, name, condition in rows]


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
        state['great_streak'] = state.get('great_streak', 0) + 1 if facts.get('fortune') == '大吉' else 0
        if state['great_streak'] >= 3:
            unlocked.append(('kaguya', COMMON['kaguya']))
        seen = set(state.get('fortunes_seen', [])) & FORTUNE_TYPES
        if facts.get('fortune') in FORTUNE_TYPES:
            seen.add(facts['fortune'])
        state['fortunes_seen'] = sorted(seen)
        if seen >= FORTUNE_TYPES:
            unlocked.append(('fortune_set', COMMON['fortune_set']))
        if facts.get('bonus'):
            count('support_matches', ())
            unlocked.append(('support', COMMON['support']))
    elif kind == 'gift':
        item = facts['item']
        if item == 'rare':
            state['special_gift_given'] = True
            unlocked.append(('special_gift', COMMON['special_gift']))
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
            if counts[character] >= 3:
                unlocked.append((f'preferred_gifts10:{character}', f'{character}の良き理解者'))
        if facts.get('preferred') and item in NORMAL_GIFTS and facts.get('first_perfect_link'):
            character = character_key(facts['character'])
            unlocked.append((f'favorite_gift:{character}', f'{character}の右腕'))
    elif kind == 'profile_search':
        names = {character_key(name) for name in state.get('profile_names', [])}
        names.add(character_key(facts['character']))
        state['profile_names'] = sorted(names)
        if len(names) >= 10:
            unlocked.append(('named10', COMMON['named10']))
    elif kind == 'world':
        worlds = set(state.get('worlds', []))
        if facts.get('world') in tuple('青黒赤白緑'):
            worlds.add(facts['world'])
        state['worlds'] = sorted(worlds)
        if worlds >= set('青黒赤白緑'):
            unlocked.append(('worlds', COMMON['worlds']))
    elif kind == 'idol_producer' and facts.get('game') == 'vierge' and facts.get('count') == 7 and facts.get('rarity') == 'UR' and character_key(facts.get('character', '')) == '小鳥遊希美':
        unlocked.append(('idol_producer', COMMON['idol_producer']))
    elif kind == 'reunion':
        unlocked.append(('reunion', COMMON['reunion']))
    elif kind == 'all_green' and facts.get('game') in ('vierge', 'relink') and facts.get('count') == (7 if facts['game'] == 'vierge' else 10) and 7 <= facts.get('green_count', 0) <= facts['count']:
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


def refresh_collection_titles(connection, user_id):
    from favorite_album import collection_targets
    targets = {'vierge': set(), 'relink': set()}
    for cards in collection_targets().values():
        for game, card_id in cards:
            targets[game].add(card_id)
    owned = {'vierge': set(), 'relink': set()}
    for game, card_id in connection.execute('SELECT game,card_id FROM george_gacha_cards WHERE user_id=%s', (user_id,)).fetchall():
        if game in owned:
            owned[game].add(card_id)
    existing = {row[0] for row in connection.execute('SELECT title_key FROM george_titles WHERE user_id=%s', (user_id,)).fetchall()}
    for game in targets:
        key = f'complete_{game}'
        if key not in existing and targets[game] and targets[game] <= owned[game]:
            grant(connection, user_id, key)
    if 'favorite_complete' not in existing:
        favorite = connection.execute('''SELECT c.card FROM george_gacha_favorites f
            JOIN george_gacha_cards c ON (c.user_id,c.game,c.card_id)=(f.user_id,f.game,f.card_id)
            WHERE f.user_id=%s''', (user_id,)).fetchone()
        if favorite:
            required = collection_targets().get(character_key(favorite[0]['character']), set())
            owned_pairs = {(game, card_id) for game, cards in owned.items() for card_id in cards}
            if required and required <= owned_pairs:
                grant(connection, user_id, 'favorite_complete')


def refresh_registration_title(connection, user_id):
    row = connection.execute('SELECT 1 FROM george_favorite_album WHERE user_id=%s AND first_registered_at IS NOT NULL LIMIT 1', (user_id,)).fetchone()
    if row:
        grant(connection, user_id, 'favorite_registered')


def title_sort_key(row):
    order = ['quiz10', 'quiz_streak10', 'fortune10', 'fortune_set', 'support',
             'variety', 'special_gift', 'preferred_gifts10', 'worlds', 'named10', 'idol_producer', 'favorite_registered',
             'reunion', 'favorite_complete', 'all_green', 'kaguya', 'complete_vierge', 'complete_relink', 'bond10', 'favorite_gift']
    kind = row[0].partition(':')[0]
    return (order.index(kind) if kind in order else len(order), row[1], row[0])


def refresh_preferred_titles(connection, user_id):
    row = connection.execute('SELECT data FROM george_title_stats WHERE user_id=%s', (user_id,)).fetchone()
    counts = json.loads(row[0]).get('preferred_gift_counts', {}) if row else {}
    for character, count in counts.items():
        if count >= 3:
            character = character_key(character)
            grant(connection, user_id, f'preferred_gifts10:{character}', f'{character}の良き理解者')


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
