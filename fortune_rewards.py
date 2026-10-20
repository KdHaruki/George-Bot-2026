"""Daily base and support gifts; all fortune runs count toward titles."""
import json
import random
import time

from present_catalog import NORMAL_ITEMS
from progress_profiles import character_key
from title_core import record_event


def ensure_fortune_runs(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS george_fortune_bonus_daily (
        user_id BIGINT PRIMARY KEY, reward_day DATE NOT NULL, interaction_id BIGINT NOT NULL, item TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS george_fortune_runs (
        interaction_id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL, result TEXT NOT NULL, created_at BIGINT NOT NULL)''')
    connection.execute('CREATE INDEX IF NOT EXISTS george_fortune_runs_owner_idx ON george_fortune_runs(user_id,created_at)')


def fortune_reward(store, connection, user_id, interaction_id, fortune, lucky_progress, draw_present):
    previous_run = connection.execute('SELECT user_id,result FROM george_fortune_runs WHERE interaction_id=%s', (interaction_id,)).fetchone()
    if previous_run:
        if previous_run[0] != user_id:
            raise ValueError('おみくじの操作が一致しないぜ。やり直してくれ。')
        return json.loads(previous_run[1])
    day = connection.execute("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tokyo')::date").fetchone()[0]
    previous = connection.execute('SELECT reward_day,interaction_id,fortune,item FROM george_present_daily WHERE user_id=%s', (user_id,)).fetchone()
    paid = connection.execute('SELECT reward_day,interaction_id,item FROM george_fortune_bonus_daily WHERE user_id=%s', (user_id,)).fetchone()
    details = None
    # Recognize today's bonuses paid by the prior version without issuing a second one.
    if previous and previous[0] >= day:
        details = connection.execute('SELECT lucky_progress,bonus_item FROM george_fortune_details WHERE user_id=%s AND interaction_id=%s', (user_id, previous[1])).fetchone()
        if details and details[1] and (not paid or paid[0] < previous[0]):
            connection.execute('''INSERT INTO george_fortune_bonus_daily VALUES (%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET reward_day=EXCLUDED.reward_day,
                interaction_id=EXCLUDED.interaction_id,item=EXCLUDED.item''', (user_id, previous[0], previous[1], details[1]))
            paid = (previous[0], previous[1], details[1])
    if previous and previous[1] == interaction_id:
        result = dict(granted=True, item=previous[3], fortune=previous[2],
                      lucky_progress=details[0] if details else None, bonus_item=details[1] if details else None)
    else:
        granted = not previous or previous[0] < day
        favorite = store.current_character(connection, user_id, required=False) if lucky_progress else None
        matched = bool(favorite and character_key(lucky_progress) == favorite)
        bonus = random.choice(NORMAL_ITEMS) if matched and (not paid or paid[0] < day) else None
        item = draw_present(fortune) if granted else previous[3]
        for gift in ([item] if granted else []) + ([bonus] if bonus else []):
            connection.execute('''INSERT INTO george_present_items VALUES (%s,%s,1)
                ON CONFLICT(user_id,item) DO UPDATE SET quantity=george_present_items.quantity+1''', (user_id, gift))
        if granted:
            connection.execute('''INSERT INTO george_present_daily VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET reward_day=EXCLUDED.reward_day,
                interaction_id=EXCLUDED.interaction_id,fortune=EXCLUDED.fortune,item=EXCLUDED.item''', (user_id, day, interaction_id, fortune, item))
            connection.execute('''INSERT INTO george_fortune_details VALUES (%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET interaction_id=EXCLUDED.interaction_id,
                lucky_progress=EXCLUDED.lucky_progress,bonus_item=EXCLUDED.bonus_item''', (user_id, interaction_id, lucky_progress, bonus))
        if bonus:
            connection.execute('''INSERT INTO george_fortune_bonus_daily VALUES (%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET reward_day=EXCLUDED.reward_day,
                interaction_id=EXCLUDED.interaction_id,item=EXCLUDED.item''', (user_id, day, interaction_id, bonus))
        record_event(connection, user_id, f'fortune:{interaction_id}', 'fortune', fortune=fortune, bonus=matched)
        result = dict(granted=granted, item=item, fortune=fortune, lucky_progress=lucky_progress,
                      bonus_item=bonus, support_matched=matched)
    now = int(time.time())
    connection.execute('INSERT INTO george_fortune_runs VALUES (%s,%s,%s,%s)', (interaction_id, user_id, json.dumps(result, ensure_ascii=False), now))
    connection.execute('DELETE FROM george_fortune_runs WHERE user_id=%s AND created_at<%s', (user_id, now - 7 * 86400))
    return result
