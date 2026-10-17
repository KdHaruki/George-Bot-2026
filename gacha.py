"""Offline gacha simulation. Rates use integer basis points, never Gemini."""
from dataclasses import dataclass, replace
import json
from pathlib import Path
import random
from datetime import date, datetime, timedelta, timezone
import hashlib
import re
from progress import progressData


@dataclass(frozen=True)
class Rules:
    name: str
    batch_size: int
    normal: tuple
    guaranteed: tuple


RULES = {
    'vierge': Rules('アンジュ・ヴィエルジュ', 7,
                    (('UR', 100), ('SR', 300), ('HR', 1400), ('R', 8200)),
                    (('UR', 250), ('SR', 750), ('HR', 9000), ('R', 0))),
    'relink': Rules('アンジュ・リリンク', 10,
                    (('★3', 400), ('★2', 2600), ('★1', 7000)),
                    (('★3', 400), ('★2', 9600), ('★1', 0))),
}

BATCH_GUARANTEE = {'vierge': 4, 'relink': 10}
RELINK_OUTFITS = json.loads(Path(__file__).with_name('relink_outfits.json').read_text(encoding='utf-8'))
VIERGE_EXCLUDED = frozenset(('久遠空', 'シンシア', 'ヒメガミノミコト', 'ナクル・クルルシファー'))
VIERGE_CHARACTERS = tuple(record for record in progressData
                          if re.sub(r'\s+', '', record['progressName']) not in VIERGE_EXCLUDED)


@dataclass(frozen=True)
class Card:
    id: str
    character: str
    name: str
    rarity: str
    cost: int | None = None
    skill: str = ''
    source: str = ''

    @property
    def label(self):
        details = []
        if self.cost is not None:
            details.append(f'コスト{self.cost}')
        if self.skill:
            details.append(self.skill)
        return self.name + (' ／ ' + '・'.join(details) if details else '')


def vierge_character_card(character, rarity):
    identity = hashlib.sha256(character.encode('utf-8')).hexdigest()[:20]
    return Card(f'vierge-character-{rarity}-{identity}', character, character, rarity)


def outfit_display_name(character, outfit):
    text = outfit.replace('(', '（').replace(')', '）').strip()
    text = re.sub(r'\s*([（）])\s*', r'\1', text)
    return f'{character}【{text}】'


def current_card(game, card):
    outfit = RELINK_OUTFITS.get(card.id) if game == 'relink' else None
    return replace(card, name=outfit_display_name(card.character, outfit['outfit'])) if outfit else card


def choose_rarity(weights, rng):
    if any(weight < 0 for _, weight in weights) or sum(weight for _, weight in weights) != 10000:
        raise ValueError('排出率の合計は100%である必要があります。')
    ticket = rng.randrange(10000)
    cumulative = 0
    for rarity, weight in weights:
        cumulative += weight
        if ticket < cumulative:
            return rarity
    raise AssertionError('Invalid probability table')


class Gacha:
    def __init__(self, catalog_path=None):
        self.vierge_birthdays = json.loads(Path(__file__).with_name('vierge_birthdays.json').read_text(encoding='utf-8'))['birthdays']
        self.birthdays = json.loads(Path(__file__).with_name('relink_birthdays.json').read_text(encoding='utf-8'))['birthdays']
        path = Path(catalog_path) if catalog_path else Path(__file__).with_name('gacha_catalog.json')
        self.catalog = json.loads(path.read_text(encoding='utf-8'))
        # Vierge is a character simulator, independent of historical card variants.
        self.catalog['games']['vierge'] = {
            'sources': [], 'missing_characters': [],
            'note': f'全{len(VIERGE_CHARACTERS)}人×UR・SR・HR・R。キャラクターとレアリティだけのBot独自ガチャ。各レアリティ内はキャラごとに均等。',
            'cards': [dict(id=card.id, character=card.character, name=card.name, rarity=card.rarity)
                      for rarity, _ in RULES['vierge'].normal
                      for record in VIERGE_CHARACTERS
                      for card in [vierge_character_card(record['progressName'], rarity)]]}
        self.pools = {}
        for game, rules in RULES.items():
            entries = self.catalog['games'][game]
            pool = {rarity: [] for rarity, _ in rules.normal}
            seen = set()
            for item in entries['cards']:
                card = current_card(game, Card(**item))
                if card.id in seen or card.rarity not in pool:
                    raise ValueError('ガチャカードのIDまたはレアリティが不正です。')
                seen.add(card.id)
                pool[card.rarity].append(card)
            if any(not cards for cards in pool.values()):
                raise ValueError('空のレアリティがあるため抽選できません。')
            self.pools[game] = pool

    def birthday_map(self, game):
        return self.vierge_birthdays if game == 'vierge' else self.birthdays

    def birthday_targets(self, on_day=None, game='relink'):
        day = on_day or datetime.now(timezone(timedelta(hours=9))).date()
        eligible = {card.character for card in self.pools[game][RULES[game].normal[0][0]]}
        return sorted(name for name in eligible if self.birthday_map(game).get(name) == day.strftime('%m-%d'))

    def next_birthday(self, on_day=None, game='relink'):
        day = on_day or datetime.now(timezone(timedelta(hours=9))).date()
        upcoming = {}
        for name in {card.character for card in self.pools[game][RULES[game].normal[0][0]]}:
            birthday = self.birthday_map(game).get(name)
            if not birthday:
                continue
            month, number = map(int, birthday.split('-'))
            for year in range(day.year, day.year + 5):
                try:
                    candidate = date(year, month, number)
                except ValueError:
                    continue
                if candidate > day:
                    upcoming.setdefault(candidate, []).append(name)
                    break
        if not upcoming:
            return None
        nearest = min(upcoming)
        return nearest, sorted(upcoming[nearest])

    def choose_card(self, game, rarity, rng=None, on_day=None):
        rng = rng or random.SystemRandom()
        pool = self.pools[game][rarity]
        if rarity == RULES[game].normal[0][0]:
            day = on_day or datetime.now(timezone(timedelta(hours=9))).date()
            names = set(self.birthday_targets(day, game))
            featured = [card for card in pool if card.character in names]
            others = [card for card in pool if card.character not in names]
            if featured and others:
                if rng.randrange(10000) < 5000:
                    # Split the featured half equally by character, then by outfit.
                    representatives = list({card.character: card for card in featured}.values())
                    character = rng.choice(representatives).character
                    pool = [card for card in featured if card.character == character]
                else:
                    pool = others
        return rng.choice(pool)

    def draw(self, game, count=1, rng=None, on_day=None):
        rules = RULES[game]
        if count not in (1, rules.batch_size):
            raise ValueError(f'回数は1回または{rules.batch_size}回を指定してくれ！')
        rng = rng or random.SystemRandom()
        results = []
        for index in range(count):
            # One dedicated guaranteed slot, not a reroll after a failed batch.
            weights = rules.guaranteed if count == rules.batch_size and index == count - 1 else rules.normal
            rarity = choose_rarity(weights, rng)
            results.append(self.choose_card(game, rarity, rng, on_day))
        return results

    def rates_text(self, game):
        rules = RULES[game]
        guarantee = dict(rules.guaranteed)
        lines = []
        for rarity, rate in rules.normal:
            size = len(self.pools[game][rarity])
            lines.append(f'【{rarity}】：通常 {rate / 100:g}% ／ 確定枠 {guarantee[rarity] / 100:g}%（{size}種）')
        return '\n'.join(lines)
