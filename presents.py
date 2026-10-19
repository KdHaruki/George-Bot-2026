"""Daily fortune rewards and transactional gifts. No AI or polling."""
from contextlib import contextmanager
import random

from gacha_collection import CollectionStore
from progress_profiles import profile_for, character_key
from favorite_album import record_gift
from title_core import record_event, refresh_affection


RARE_RATES = {'大吉': 10, '吉': 5, '中吉': 4, '小吉': 3, '末吉': 2, '凶': 1}
QUIZ_FORTUNES = {1: '大吉', 2: '吉', 3: '中吉', 4: '小吉'}
MAX_AFFECTION = 100


class PerfectLinkReached(ValueError):
    pass


def affection_display(points, perfect=False):
    if perfect:
        return '**パーフェクトリンク**\n**100/100**\n' + '🟪' * 10
    points = max(0, min(MAX_AFFECTION, points))
    filled = points // 10
    return f'**{points}/{MAX_AFFECTION}**\n' + '🟪' * filled + '⬜' * (10 - filled)


ITEMS = {
    'sweets': ('🍪', 'お菓子'), 'food': ('🍱', 'お弁当'),
    'fashion': ('🎀', 'リボン'), 'book': ('📖', '本'),
    'game': ('🎮', 'ゲーム'), 'magic': ('🪄', '手品グッズ'),
    'rare': ('🌈', '虹色の花束'),
}
NORMAL_ITEMS = tuple(key for key in ITEMS if key != 'rare')
PREFERENCE_WORDS = {
    'sweets': ('甘い', 'お菓子', 'ケーキ', 'クレープ', 'チョコ', 'スイーツ', 'パフェ', 'クッキー', 'アイス'),
    'food': ('ご飯', '料理', '食べ', '食事', 'お肉', 'パン', '牛乳', 'お弁当'),
    'fashion': ('おしゃれ', 'オシャレ', '服', 'アクセサリー', 'ファッション', '買い物', 'ショッピング'),
    'book': ('読書', '本', '勉強', '図書'),
    'game': ('ゲーム', '遊び', 'おもちゃ'),
    'magic': ('手品', '魔法', '不思議', '鏡'),
}


def preferred_items(character):
    record = profile_for(character)
    likes = record.get('progressLike', '') if record else ''
    return tuple(key for key, words in PREFERENCE_WORDS.items() if any(word in likes for word in words))[:2]


def affection_gain(character, item):
    if item not in ITEMS:
        raise ValueError('そのプレゼントは見つからないぜ。')
    return 10 if item == 'rare' else 3 if item in preferred_items(character) else 1


def draw_present(fortune, rng=random):
    if rng.randrange(100) < RARE_RATES[fortune]:
        return 'rare'
    return rng.choice(NORMAL_ITEMS)


def draw_quiz_present(attempts, rng=random):
    if attempts not in QUIZ_FORTUNES:
        raise ValueError('クイズの回答回数が不正だぜ。')
    return draw_present(QUIZ_FORTUNES[attempts], rng)


class PresentStore(CollectionStore):
    @contextmanager
    def connect(self):
        with super().connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS george_present_daily (
                user_id BIGINT PRIMARY KEY, reward_day DATE NOT NULL,
                interaction_id BIGINT NOT NULL, fortune TEXT NOT NULL, item TEXT NOT NULL)''')
            connection.execute('''CREATE TABLE IF NOT EXISTS george_quiz_daily (
                user_id BIGINT PRIMARY KEY, reward_day DATE NOT NULL,
                interaction_id BIGINT NOT NULL, item TEXT NOT NULL)''')
            connection.execute('''CREATE TABLE IF NOT EXISTS george_fortune_details (
                user_id BIGINT PRIMARY KEY, interaction_id BIGINT NOT NULL,
                lucky_progress TEXT, bonus_item TEXT)''')
            connection.execute('''CREATE TABLE IF NOT EXISTS george_present_exchanges (
                interaction_id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL,
                source TEXT NOT NULL, target TEXT NOT NULL, source_quantity BIGINT NOT NULL,
                target_quantity BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
            connection.execute('''CREATE TABLE IF NOT EXISTS george_present_items (
                user_id BIGINT NOT NULL, item TEXT NOT NULL, quantity BIGINT NOT NULL CHECK(quantity>=0),
                PRIMARY KEY(user_id,item))''')
            connection.execute('''CREATE TABLE IF NOT EXISTS george_affection (
                user_id BIGINT NOT NULL, character TEXT NOT NULL, points BIGINT NOT NULL CHECK(points>=0),
                PRIMARY KEY(user_id,character))''')
            connection.execute('''CREATE TABLE IF NOT EXISTS george_perfect_links (
                user_id BIGINT NOT NULL, character TEXT NOT NULL,
                achieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id,character))''')
            connection.execute('''CREATE TABLE IF NOT EXISTS george_present_receipts (
                interaction_id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL, character TEXT NOT NULL,
                item TEXT NOT NULL, gain INTEGER NOT NULL, points BIGINT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
            yield connection

    def claim(self, user_id, interaction_id, fortune, lucky_progress=None):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            day = connection.execute("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date").fetchone()[0]
            previous = connection.execute('SELECT reward_day,interaction_id,fortune,item FROM george_present_daily WHERE user_id=%s', (user_id,)).fetchone()
            if previous and previous[0] >= day:
                details = connection.execute('SELECT lucky_progress,bonus_item FROM george_fortune_details WHERE user_id=%s AND interaction_id=%s', (user_id, previous[1])).fetchone()
                return dict(granted=previous[1] == interaction_id, item=previous[3], fortune=previous[2],
                            lucky_progress=details[0] if details else None, bonus_item=details[1] if details else None)
            item = draw_present(fortune)
            favorite = self.current_character(connection, user_id, required=False) if lucky_progress else None
            bonus = random.choice(NORMAL_ITEMS) if favorite and character_key(lucky_progress) == favorite else None
            connection.execute('''INSERT INTO george_present_items VALUES (%s,%s,1)
                ON CONFLICT(user_id,item) DO UPDATE SET quantity=george_present_items.quantity+1''', (user_id, item))
            if bonus:
                connection.execute('''INSERT INTO george_present_items VALUES (%s,%s,1)
                    ON CONFLICT(user_id,item) DO UPDATE SET quantity=george_present_items.quantity+1''', (user_id, bonus))
            connection.execute('''INSERT INTO george_present_daily VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET reward_day=EXCLUDED.reward_day,
                interaction_id=EXCLUDED.interaction_id,fortune=EXCLUDED.fortune,item=EXCLUDED.item''',
                (user_id, day, interaction_id, fortune, item))
            connection.execute('''INSERT INTO george_fortune_details VALUES (%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET interaction_id=EXCLUDED.interaction_id,
                lucky_progress=EXCLUDED.lucky_progress,bonus_item=EXCLUDED.bonus_item''',
                (user_id, interaction_id, lucky_progress, bonus))
            record_event(connection, user_id, f'fortune:{interaction_id}', 'fortune', fortune=fortune, bonus=bool(bonus))
            return dict(granted=True, item=item, fortune=fortune, lucky_progress=lucky_progress, bonus_item=bonus)

    def claim_quiz(self, user_id, interaction_id, attempts=1):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            day = connection.execute("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date").fetchone()[0]
            previous = connection.execute('SELECT reward_day,interaction_id,item FROM george_quiz_daily WHERE user_id=%s', (user_id,)).fetchone()
            if previous and previous[0] >= day:
                return dict(granted=previous[1] == interaction_id, item=previous[2])
            item = draw_quiz_present(attempts)
            connection.execute('''INSERT INTO george_present_items VALUES (%s,%s,1)
                ON CONFLICT(user_id,item) DO UPDATE SET quantity=george_present_items.quantity+1''', (user_id, item))
            connection.execute('''INSERT INTO george_quiz_daily VALUES (%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET reward_day=EXCLUDED.reward_day,
                interaction_id=EXCLUDED.interaction_id,item=EXCLUDED.item''', (user_id, day, interaction_id, item))
            if attempts == 1:
                record_event(connection, user_id, f'quiz:{interaction_id}', 'quiz', attempts=attempts)
            return dict(granted=True, item=item)

    def album(self, user_id, character):
        with self.connect() as connection:
            return connection.execute('''SELECT first_registered_at,first_gift_at,max_affection_at
                FROM george_favorite_album WHERE user_id=%s AND character=%s''',
                (user_id, character_key(character))).fetchone() or (None, None, None)

    @staticmethod
    def current_character(connection, user_id, required=True):
        row = connection.execute('''SELECT c.card FROM george_gacha_favorites f
            JOIN george_gacha_cards c ON (c.user_id,c.game,c.card_id)=(f.user_id,f.game,f.card_id)
            WHERE f.user_id=%s''', (user_id,)).fetchone()
        if not row:
            if not required:
                return None
            raise ValueError('まず /お気に入り 登録 でプログレスを登録してくれ！')
        return character_key(row[0]['character'])

    def snapshot(self, user_id):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            character = self.current_character(connection, user_id)
            items = dict(connection.execute('SELECT item,quantity FROM george_present_items WHERE user_id=%s AND quantity>0', (user_id,)).fetchall())
            row = connection.execute('SELECT points FROM george_affection WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
            return character, items, min(MAX_AFFECTION, row[0]) if row else 0, self._is_perfect(connection, user_id, character)

    @staticmethod
    def _is_perfect(connection, user_id, character):
        return connection.execute('SELECT 1 FROM george_perfect_links WHERE user_id=%s AND character=%s',
                                  (user_id, character_key(character))).fetchone() is not None

    def points(self, user_id, character):
        return self.affection_status(user_id, character)[0]

    def affection_status(self, user_id, character):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            row = connection.execute('SELECT points FROM george_affection WHERE user_id=%s AND character=%s', (user_id, character_key(character))).fetchone()
            return min(MAX_AFFECTION, row[0]) if row else 0, self._is_perfect(connection, user_id, character)

    def inventory(self, user_id):
        with self.connect() as connection:
            return dict(connection.execute('SELECT item,quantity FROM george_present_items WHERE user_id=%s AND quantity>0', (user_id,)).fetchall())

    def exchange(self, user_id, interaction_id, source, target):
        if source not in NORMAL_ITEMS or target not in NORMAL_ITEMS or source == target:
            raise ValueError('異なる通常アイテム同士で交換してくれ。レアは交換できないぜ！')
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            previous = connection.execute('SELECT user_id,source,target,source_quantity,target_quantity FROM george_present_exchanges WHERE interaction_id=%s', (interaction_id,)).fetchone()
            if previous:
                if previous[:3] != (user_id, source, target):
                    raise ValueError('交換の操作が一致しないぜ。画面を開き直してくれ！')
                return previous[3], previous[4]
            row = connection.execute('''UPDATE george_present_items SET quantity=quantity-3
                WHERE user_id=%s AND item=%s AND quantity>=3 RETURNING quantity''', (user_id, source)).fetchone()
            if row is None:
                raise ValueError('交換には同じ通常アイテムが3個必要だぜ！')
            quantity = connection.execute('''INSERT INTO george_present_items VALUES (%s,%s,1)
                ON CONFLICT(user_id,item) DO UPDATE SET quantity=george_present_items.quantity+1
                RETURNING quantity''', (user_id, target)).fetchone()[0]
            connection.execute('''INSERT INTO george_present_exchanges(interaction_id,user_id,source,target,source_quantity,target_quantity)
                VALUES (%s,%s,%s,%s,%s,%s)''', (interaction_id, user_id, source, target, row[0], quantity))
            record_event(connection, user_id, f'exchange:{interaction_id}', 'exchange')
            connection.execute("DELETE FROM george_present_exchanges WHERE user_id=%s AND created_at<NOW()-INTERVAL '7 days'", (user_id,))
            return row[0], quantity

    def give(self, user_id, interaction_id, expected_character, item):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            receipt = connection.execute('SELECT user_id,character,item,gain,points FROM george_present_receipts WHERE interaction_id=%s', (interaction_id,)).fetchone()
            if receipt:
                if receipt[:3] != (user_id, expected_character, item):
                    raise ValueError('プレゼントの操作が一致しないぜ。開き直してくれ。')
                perfect = self._is_perfect(connection, user_id, expected_character)
                return receipt[3], MAX_AFFECTION if perfect else receipt[4], perfect
            character = self.current_character(connection, user_id)
            if character != expected_character:
                raise ValueError('お気に入りが変わったぜ。プレゼント画面を開き直してくれ！')
            if self._is_perfect(connection, user_id, character):
                raise PerfectLinkReached('パーフェクトリンク達成済みだぜ！ この子へのプレゼントはもう渡せないぞ。アイテムは消費していないぜ。')
            gain = affection_gain(character, item)
            row = connection.execute('SELECT points FROM george_affection WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
            current = min(MAX_AFFECTION, row[0]) if row else 0
            perfect = current == MAX_AFFECTION and item in preferred_items(character)
            gain = min(gain, MAX_AFFECTION - current)
            result = connection.execute('''UPDATE george_present_items SET quantity=quantity-1
                WHERE user_id=%s AND item=%s AND quantity>0''', (user_id, item))
            if not result.rowcount:
                raise ValueError('そのプレゼントはもう持っていないぜ。画面を開き直してくれ！')
            points = connection.execute('''INSERT INTO george_affection VALUES (%s,%s,%s)
                ON CONFLICT(user_id,character) DO UPDATE SET points=EXCLUDED.points
                RETURNING points''', (user_id, character, current + gain)).fetchone()[0]
            if perfect:
                connection.execute('''INSERT INTO george_perfect_links(user_id,character) VALUES (%s,%s)
                    ON CONFLICT(user_id,character) DO NOTHING''', (user_id, character))
            record_gift(connection, user_id, character, current < MAX_AFFECTION <= points)
            record_event(connection, user_id, f'gift:{interaction_id}', 'gift', character=character, item=item,
                         preferred=item in preferred_items(character))
            if points >= MAX_AFFECTION:
                refresh_affection(connection, user_id)
            connection.execute('INSERT INTO george_present_receipts(interaction_id,user_id,character,item,gain,points) VALUES (%s,%s,%s,%s,%s,%s)',
                               (interaction_id, user_id, character, item, gain, points))
            connection.execute("DELETE FROM george_present_receipts WHERE user_id=%s AND created_at<NOW()-INTERVAL '7 days'", (user_id,))
            return gain, points, perfect
