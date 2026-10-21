"""Daily fortune rewards and transactional gifts. No AI or polling."""
from contextlib import contextmanager
import random

from gacha_collection import CollectionStore
from progress_profiles import profile_for, character_key
from favorite_album import record_gift, record_completions
from title_core import record_event, refresh_affection
from daily_affection import MAX_AFFECTION, settle_daily, link_level, affection_limit
from present_catalog import ITEMS, NORMAL_ITEMS, preferred_items
from quiz_rounds import QuizRounds
from fortune_rewards import ensure_fortune_runs, fortune_reward


RARE_RATES = {'大吉': 10, '吉': 5, '中吉': 4, '小吉': 3, '末吉': 2, '凶': 1}
QUIZ_FORTUNES = {1: '大吉', 2: '吉', 3: '中吉', 4: '小吉'}


def affection_display(points, perfect=False):
    limit = affection_limit(perfect)
    points = max(0, min(limit, points))
    filled = points * 10 // limit
    label = f'**{link_label(perfect)}**\n' if perfect else ''
    colors = ('🟢', '🟩') if points * 4 < limit else ('🟡', '🟨') if points * 2 < limit else ('🟠', '🟧') if points * 4 < limit * 3 else ('🔴', '🟥')
    return label + f'**{points}/{limit}**\n' + colors[0] + ' ' + colors[1] * filled + '⬜' * (10 - filled)


def link_label(level):
    numerals = ('Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ')
    suffix = numerals[int(level) - 1] if 1 <= int(level) <= len(numerals) else f'Lv.{level}'
    return f'パーフェクトリンク{suffix}'


def affection_gain(character, item):
    if item not in ITEMS:
        raise ValueError('そのプレゼントは見つからないぜ。')
    return 10 if item == 'rare' else 5 if item in preferred_items(character) else 2


def draw_present(fortune, rng=random):
    if rng.randrange(100) < RARE_RATES[fortune]:
        return 'rare'
    return rng.choice(NORMAL_ITEMS)


def draw_quiz_present(attempts, rng=random):
    if attempts not in QUIZ_FORTUNES:
        raise ValueError('クイズの回答回数が不正だぜ。')
    return draw_present(QUIZ_FORTUNES[attempts], rng)


class PresentStore(QuizRounds, CollectionStore):
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
            ensure_fortune_runs(connection)
            yield connection

    def claim(self, user_id, interaction_id, fortune, lucky_progress=None):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            return fortune_reward(self, connection, user_id, interaction_id, fortune, lucky_progress, draw_present)

    def claim_quiz(self, user_id, interaction_id, attempts=1):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            if attempts == 1:
                record_event(connection, user_id, f'quiz:{interaction_id}', 'quiz', attempts=attempts)
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
            return dict(granted=True, item=item)

    def album(self, user_id, character):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            params = (user_id, character_key(character))
            record_completions(connection, user_id, (character,))
            dates = connection.execute('''SELECT first_registered_at,first_gift_at,max_affection_at
                FROM george_favorite_album WHERE user_id=%s AND character=%s''',
                params).fetchone() or (None, None, None)
            perfect = connection.execute('''SELECT achieved_at FROM george_perfect_links
                WHERE user_id=%s AND character=%s''', params).fetchone()
            completion = connection.execute('''SELECT achieved_at FROM george_character_completions
                WHERE user_id=%s AND character=%s''', params).fetchone()
            support = connection.execute('''SELECT achieved_at FROM george_character_supports
                WHERE user_id=%s AND character=%s''', params).fetchone()
            return (dates[0], None, dates[2], perfect[0] if perfect else None,
                    completion[0] if completion else None, support[0] if support else None)

    @staticmethod
    def current_character(connection, user_id, required=True):
        row = connection.execute('''SELECT c.card FROM george_gacha_favorites f
            JOIN george_gacha_cards c ON (c.user_id,c.game,c.card_id)=(f.user_id,f.game,f.card_id)
            WHERE f.user_id=%s''', (user_id,)).fetchone()
        if not row:
            if not required:
                return None
            raise ValueError('まず /お気に入り プログレス登録 でプログレスを登録してくれ！')
        return character_key(row[0]['character'])

    def snapshot(self, user_id):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            settle_daily(connection, user_id)
            character = self.current_character(connection, user_id)
            items = dict(connection.execute('SELECT item,quantity FROM george_present_items WHERE user_id=%s AND quantity>0', (user_id,)).fetchall())
            row = connection.execute('SELECT points FROM george_affection WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
            level = self._link_level(connection, user_id, character)
            return character, items, min(affection_limit(level), row[0]) if row else 0, level

    @staticmethod
    def _link_level(connection, user_id, character):
        return link_level(connection, user_id, character)

    def points(self, user_id, character):
        return self.affection_status(user_id, character)[0]

    def affection_status(self, user_id, character):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            settle_daily(connection, user_id)
            row = connection.execute('SELECT points FROM george_affection WHERE user_id=%s AND character=%s', (user_id, character_key(character))).fetchone()
            level = self._link_level(connection, user_id, character)
            return min(affection_limit(level), row[0]) if row else 0, level

    def inventory(self, user_id):
        with self.connect() as connection:
            return dict(connection.execute('SELECT item,quantity FROM george_present_items WHERE user_id=%s AND quantity>0', (user_id,)).fetchall())

    def give(self, user_id, interaction_id, expected_character, item):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            settle_daily(connection, user_id)
            receipt = connection.execute('SELECT user_id,character,item,gain,points FROM george_present_receipts WHERE interaction_id=%s', (interaction_id,)).fetchone()
            if receipt:
                if receipt[:3] != (user_id, expected_character, item):
                    raise ValueError('プレゼントの操作が一致しないぜ。開き直してくれ。')
                perfect = self._link_level(connection, user_id, expected_character)
                current = connection.execute('SELECT points FROM george_affection WHERE user_id=%s AND character=%s', (user_id, expected_character)).fetchone()
                return receipt[3], min(affection_limit(perfect), current[0]) if current else receipt[4], perfect
            character = self.current_character(connection, user_id)
            if character != expected_character:
                raise ValueError('お気に入りが変わったぜ。プレゼント画面を開き直してくれ！')
            level = self._link_level(connection, user_id, character)
            limit = affection_limit(level)
            gain = affection_gain(character, item)
            row = connection.execute('SELECT points FROM george_affection WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
            current = min(limit, row[0]) if row else 0
            advanced = current == limit and item in preferred_items(character)
            perfect = level + 1 if advanced else level
            gain = min(gain, limit - current)
            result = connection.execute('''UPDATE george_present_items SET quantity=quantity-1
                WHERE user_id=%s AND item=%s AND quantity>0''', (user_id, item))
            if not result.rowcount:
                raise ValueError('そのプレゼントはもう持っていないぜ。画面を開き直してくれ！')
            points = connection.execute('''INSERT INTO george_affection VALUES (%s,%s,%s)
                ON CONFLICT(user_id,character) DO UPDATE SET points=EXCLUDED.points
                RETURNING points''', (user_id, character, current + gain)).fetchone()[0]
            if advanced:
                connection.execute('''INSERT INTO george_perfect_links(user_id,character) VALUES (%s,%s)
                    ON CONFLICT(user_id,character) DO NOTHING''', (user_id, character))
                connection.execute('''INSERT INTO george_perfect_link_levels(user_id,character,level)
                    VALUES (%s,%s,%s) ON CONFLICT(user_id,character) DO UPDATE SET
                    level=EXCLUDED.level,achieved_at=CURRENT_TIMESTAMP''', (user_id, character, perfect))
            record_gift(connection, user_id, character, current < MAX_AFFECTION <= points)
            record_event(connection, user_id, f'gift:{interaction_id}', 'gift', character=character, item=item,
                         preferred=item in preferred_items(character), first_perfect_link=advanced and level == 0)
            if points >= MAX_AFFECTION:
                refresh_affection(connection, user_id)
            connection.execute('INSERT INTO george_present_receipts(interaction_id,user_id,character,item,gain,points) VALUES (%s,%s,%s,%s,%s,%s)',
                               (interaction_id, user_id, character, item, gain, points))
            connection.execute("DELETE FROM george_present_receipts WHERE user_id=%s AND created_at<NOW()-INTERVAL '7 days'", (user_id,))
            return gain, points, perfect
