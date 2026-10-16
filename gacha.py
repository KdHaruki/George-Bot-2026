"""Offline gacha simulation. Rates use integer basis points, never Gemini."""
from dataclasses import dataclass
import json
from pathlib import Path
import random


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
        path = Path(catalog_path) if catalog_path else Path(__file__).with_name('gacha_catalog.json')
        self.catalog = json.loads(path.read_text(encoding='utf-8'))
        self.pools = {}
        for game, rules in RULES.items():
            entries = self.catalog['games'][game]
            pool = {rarity: [] for rarity, _ in rules.normal}
            seen = set()
            for item in entries['cards']:
                card = Card(**item)
                if card.id in seen or card.rarity not in pool:
                    raise ValueError('ガチャカードのIDまたはレアリティが不正です。')
                seen.add(card.id)
                pool[card.rarity].append(card)
            if any(not cards for cards in pool.values()):
                raise ValueError('空のレアリティがあるため抽選できません。')
            self.pools[game] = pool

    def draw(self, game, count=1, rng=None):
        rules = RULES[game]
        if count not in (1, rules.batch_size):
            raise ValueError(f'回数は1回または{rules.batch_size}回を指定してくれ！')
        rng = rng or random.SystemRandom()
        results = []
        for index in range(count):
            # One dedicated guaranteed slot, not a reroll after a failed batch.
            weights = rules.guaranteed if count == rules.batch_size and index == count - 1 else rules.normal
            rarity = choose_rarity(weights, rng)
            results.append(rng.choice(self.pools[game][rarity]))
        return results

    def rates_text(self, game):
        rules = RULES[game]
        guarantee = dict(rules.guaranteed)
        lines = []
        for rarity, rate in rules.normal:
            size = len(self.pools[game][rarity])
            lines.append(f'**{rarity}**：通常 {rate / 100:g}% ／ 確定枠 {guarantee[rarity] / 100:g}%（{size}種）')
        lines.append(f'{rules.batch_size}連＝通常抽選{rules.batch_size - 1}枠＋確定枠1枠。')
        lines.append('レアリティを抽選後、そのレアリティの収録カードから均等に抽選するぜ。')
        return '\n'.join(lines)
