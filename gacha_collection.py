"""User-owned collections, saved atomically with idempotent draw receipts."""
from contextlib import contextmanager
from dataclasses import asdict
import json
import time

from gacha import BATCH_GUARANTEE, RULES, Card, Gacha, vierge_character_card, current_card
import random
from registered_memory import MemoryStore, MemoryUnavailable
from favorite_album import ensure_album, record_registration, record_completions
from title_core import ensure_titles, seed_existing_streaks, record_event, change_streak, settle_streak, refresh_special_agent
from progress_profiles import character_key, profile_for
from daily_affection import ensure_daily, seed_daily, settle_daily, start_daily


class CollectionStore(MemoryStore):
    def claim_title_notifications(self, user_id, token):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            settle_streak(connection, user_id)
            refresh_special_agent(connection, user_id)
            now = int(time.time())
            rows = connection.execute('''SELECT title_key,name FROM george_title_notices
                WHERE user_id=%s AND claimed_until<=%s AND title_key<>'exchange10' AND title_key NOT LIKE %s
                ORDER BY title_key LIMIT 10''', (user_id, now, 'collection:%')).fetchall()
            for key, _ in rows:
                connection.execute('''UPDATE george_title_notices SET claimed_until=%s,claim_token=%s
                    WHERE user_id=%s AND title_key=%s''', (now + 120, token, user_id, key))
            return rows

    def finish_title_notifications(self, user_id, token, delivered):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            if delivered:
                connection.execute('DELETE FROM george_title_notices WHERE user_id=%s AND claim_token=%s', (user_id, token))
            else:
                connection.execute('''UPDATE george_title_notices SET claimed_until=0,claim_token=''
                    WHERE user_id=%s AND claim_token=%s''', (user_id, token))

    @contextmanager
    def connect(self):
        try:
            with super().connect() as connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS george_gacha_cards (
                    user_id BIGINT NOT NULL, game TEXT NOT NULL, card_id TEXT NOT NULL,
                    card JSONB NOT NULL, quantity BIGINT NOT NULL CHECK(quantity>0),
                    PRIMARY KEY(user_id,game,card_id))""")
                connection.execute("""CREATE TABLE IF NOT EXISTS george_gacha_draws (
                    interaction_id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL,
                    game TEXT NOT NULL, result JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
                connection.execute("CREATE INDEX IF NOT EXISTS george_gacha_draws_owner_idx ON george_gacha_draws(user_id,created_at)")
                connection.execute("""CREATE TABLE IF NOT EXISTS george_gacha_batches (
                    user_id BIGINT NOT NULL, game TEXT NOT NULL, batches BIGINT NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id,game))""")
                connection.execute("""CREATE TABLE IF NOT EXISTS george_relink_counts (
                    user_id BIGINT PRIMARY KEY, draws BIGINT NOT NULL DEFAULT 0)""")
                connection.execute("""CREATE TABLE IF NOT EXISTS george_gacha_favorites (
                    user_id BIGINT PRIMARY KEY, game TEXT NOT NULL, card_id TEXT NOT NULL,
                    FOREIGN KEY(user_id,game,card_id) REFERENCES george_gacha_cards(user_id,game,card_id))""")
                self.migrate_vierge(connection)
                ensure_album(connection)
                ensure_daily(connection)
                ensure_titles(connection)
                seed_existing_streaks(connection)
                seed_daily(connection)
                yield connection
        except MemoryUnavailable:
            raise MemoryUnavailable('コレクションの保存先を利用できなかったぜ。管理者にDATABASE_URLを確認してもらってくれ。') from None

    @staticmethod
    def migrate_vierge(connection):
        connection.execute('CREATE TABLE IF NOT EXISTS george_gacha_migrations (name TEXT PRIMARY KEY)')
        key = ('vierge-characters-v1',)
        query = 'SELECT 1 FROM george_gacha_migrations WHERE name=%s'
        if connection.execute(query, key).fetchone():
            return
        connection.execute("SELECT pg_advisory_xact_lock(hashtext('george-vierge-characters-v1'))")
        if connection.execute(query, key).fetchone():
            return
        rows = connection.execute("SELECT user_id,card_id,card,quantity FROM george_gacha_cards WHERE game='vierge' FOR UPDATE").fetchall()
        for user_id, old_id, payload, quantity in rows:
            card = vierge_character_card(payload['character'], payload['rarity'])
            if old_id == card.id:
                continue
            connection.execute('''INSERT INTO george_gacha_cards(user_id,game,card_id,card,quantity)
                VALUES (%s,'vierge',%s,%s::jsonb,%s) ON CONFLICT(user_id,game,card_id)
                DO UPDATE SET quantity=george_gacha_cards.quantity+EXCLUDED.quantity,card=EXCLUDED.card''',
                (user_id, card.id, json.dumps(asdict(card), ensure_ascii=False), quantity))
            connection.execute("UPDATE george_gacha_favorites SET card_id=%s WHERE user_id=%s AND game='vierge' AND card_id=%s", (card.id, user_id, old_id))
            connection.execute("DELETE FROM george_gacha_cards WHERE user_id=%s AND game='vierge' AND card_id=%s", (user_id, old_id))
        connection.execute('INSERT INTO george_gacha_migrations(name) VALUES (%s)', key)

    def save_draw(self, user_id, game, interaction_id, cards):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            previous = connection.execute('SELECT user_id,game,result FROM george_gacha_draws WHERE interaction_id=%s', (interaction_id,)).fetchone()
            if previous:
                if previous[:2] != (user_id, game):
                    raise ValueError('Draw owner mismatch')
                if game == 'vierge':
                    return [dict(entry, card=asdict(vierge_character_card(entry['card']['character'], entry['card']['rarity']))) for entry in previous[2]]
                return [dict(entry, card=asdict(current_card(game, Card(**entry['card'])))) for entry in previous[2]]
            cards = [current_card(game, card) for card in cards]
            if game == 'relink':
                total = connection.execute("""INSERT INTO george_relink_counts(user_id,draws)
                    VALUES (%s,COALESCE((SELECT batches*10 FROM george_gacha_batches
                        WHERE user_id=%s AND game='relink'),0)+%s)
                    ON CONFLICT(user_id) DO UPDATE SET draws=george_relink_counts.draws+%s
                    RETURNING draws""", (user_id, user_id, len(cards), len(cards))).fetchone()[0]
                for index in range(len(cards)):
                    if (total - len(cards) + index + 1) % 100 == 0:
                        cards[index] = Gacha().choose_card(game, '★3')
            elif len(cards) == RULES[game].batch_size:
                batches = connection.execute("""INSERT INTO george_gacha_batches(user_id,game,batches)
                    VALUES (%s,%s,1) ON CONFLICT(user_id,game) DO UPDATE SET
                    batches=george_gacha_batches.batches+1 RETURNING batches""", (user_id, game)).fetchone()[0]
                if batches % BATCH_GUARANTEE[game] == 0:
                    highest = RULES[game].normal[0][0]
                    cards[-1] = Gacha().choose_card(game, highest)
                elif game == 'vierge' and batches % BATCH_GUARANTEE[game] == 1:
                    # Raise the existing guaranteed slot to SR; never downgrade UR.
                    if cards[-1].rarity not in ('UR', 'SR'):
                        cards[-1] = random.SystemRandom().choice(Gacha().pools[game]['SR'])
            result = []
            for card in cards:
                payload = asdict(card)
                quantity = connection.execute("""INSERT INTO george_gacha_cards(user_id,game,card_id,card,quantity)
                    VALUES (%s,%s,%s,%s::jsonb,1)
                    ON CONFLICT(user_id,game,card_id) DO UPDATE SET
                    quantity=george_gacha_cards.quantity+1,card=EXCLUDED.card RETURNING quantity""",
                    (user_id, game, card.id, json.dumps(payload, ensure_ascii=False))).fetchone()[0]
                result.append(dict(card=payload, quantity=quantity, new=quantity == 1))
            connection.execute('INSERT INTO george_gacha_draws(interaction_id,user_id,game,result) VALUES (%s,%s,%s,%s::jsonb)',
                               (interaction_id, user_id, game, json.dumps(result, ensure_ascii=False)))
            favorite = connection.execute('''SELECT c.card FROM george_gacha_favorites f
                JOIN george_gacha_cards c ON (c.user_id,c.game,c.card_id)=(f.user_id,f.game,f.card_id)
                WHERE f.user_id=%s''', (user_id,)).fetchone()
            if favorite and any(card.rarity == RULES[game].normal[0][0] and
                                character_key(card.character) == character_key(favorite[0]['character']) for card in cards):
                record_event(connection, user_id, f'reunion:{interaction_id}', 'reunion')
            highest_count = sum(card.rarity == RULES[game].normal[0][0] for card in cards)
            if len(cards) == RULES[game].batch_size and highest_count >= 3:
                record_event(connection, user_id, f'triple-rare:{interaction_id}', 'triple_rare', count=highest_count)
            if game == 'vierge' and len(cards) == 7 and {'UR', 'SR', 'HR', 'R'} <= {card.rarity for card in cards}:
                record_event(connection, user_id, f'royal-flush:{interaction_id}', 'royal_flush',
                             game=game, count=len(cards), rarities=sorted({card.rarity for card in cards}))
            record_completions(connection, user_id, (card.character for card in cards))
            # Receipts only prevent short-term redelivery; owned cards never expire.
            connection.execute("DELETE FROM george_gacha_draws WHERE user_id=%s AND created_at<NOW()-INTERVAL '7 days'", (user_id,))
        return result

    def batch_counts(self, user_id):
        with self.connect() as connection:
            rows = connection.execute('SELECT game,batches FROM george_gacha_batches WHERE user_id=%s', (user_id,)).fetchall()
            relink = connection.execute('SELECT draws FROM george_relink_counts WHERE user_id=%s', (user_id,)).fetchone()
        counts = {game: count for game, count in rows}
        counts['relink'] = relink[0] if relink else counts.get('relink', 0) * 10
        return counts

    def owned(self, user_id, game=None):
        with self.connect() as connection:
            rows = connection.execute("""SELECT game,card,quantity FROM george_gacha_cards
                WHERE user_id=%s AND (%s::text IS NULL OR game=%s) ORDER BY game,card_id""", (user_id, game, game)).fetchall()
        return [(game, current_card(game, Card(**card)), quantity) for game, card, quantity in rows]

    def favorite(self, user_id):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            settle_daily(connection, user_id)
            row = connection.execute("""SELECT c.game,c.card,c.quantity FROM george_gacha_favorites f
                JOIN george_gacha_cards c ON (c.user_id,c.game,c.card_id)=(f.user_id,f.game,f.card_id)
                WHERE f.user_id=%s""", (user_id,)).fetchone()
        return (row[0], current_card(row[0], Card(**row[1])), row[2]) if row else None

    def set_favorite(self, user_id, game, card_id, toggle=False):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            row = connection.execute("SELECT card,quantity FROM george_gacha_cards WHERE user_id=%s AND game=%s AND card_id=%s", (user_id, game, card_id)).fetchone()
            if row is None:
                raise ValueError('お気に入りにできるのは、自分が持っているカードだけだぜ。候補から選んでくれ！')
            settle_daily(connection, user_id)
            if toggle:
                current = connection.execute('SELECT game,card_id FROM george_gacha_favorites WHERE user_id=%s', (user_id,)).fetchone()
                if current == (game, card_id):
                    change_streak(connection, user_id, None)
                    start_daily(connection, user_id, None)
                    connection.execute('DELETE FROM george_gacha_favorites WHERE user_id=%s', (user_id,))
                    return None
            connection.execute("""INSERT INTO george_gacha_favorites(user_id,game,card_id) VALUES (%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET game=EXCLUDED.game,card_id=EXCLUDED.card_id""", (user_id, game, card_id))
            record_registration(connection, user_id, current_card(game, Card(**row[0])).character)
            change_streak(connection, user_id, current_card(game, Card(**row[0])).character)
            start_daily(connection, user_id, current_card(game, Card(**row[0])).character)
            profile = profile_for(row[0]['character'])
            if profile:
                record_event(connection, user_id, f'favorite-world:{game}:{card_id}', 'favorite_world', world=profile['progressWorld'])
        return game, current_card(game, Card(**row[0])), row[1]

    def clear_favorite(self, user_id):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            settle_daily(connection, user_id)
            change_streak(connection, user_id, None)
            start_daily(connection, user_id, None)
            return connection.execute('DELETE FROM george_gacha_favorites WHERE user_id=%s', (user_id,)).rowcount > 0


def collection_summary(engine, rows, game):
    current = {card.id for pool in engine.pools[game].values() for card in pool}
    owned = {card.id for row_game, card, _ in rows if row_game == game}
    total_copies = sum(count for row_game, _, count in rows if row_game == game)
    return len(current & owned), len(current), total_copies, len(owned - current)


def unowned_cards(engine, rows, game=None):
    """Compare by game and stable card ID, never by character name alone."""
    owned = {(row_game, card.id) for row_game, card, count in rows if count > 0}
    return [(key, card, 0) for key in ([game] if game else engine.pools)
            for pool in engine.pools[key].values() for card in pool if (key, card.id) not in owned]
