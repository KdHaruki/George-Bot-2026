"""Build checked-in factual card data from locally downloaded tables.

Run fetch_gacha_sources.py first. No rarity is guessed for missing characters.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from progress import progressData
from scripts.fetch_gacha_sources import SOURCES


def normalize(value):
    return re.sub(r'[\s・＝=―ーｰ]', '', unicodedata.normalize('NFKC', value))


ALIASES = {
    '安堂環': '安藤環', '城ヶ崎愛奈': '城ケ崎愛奈',
    'クラリス・エーデルライト': 'クラリス・エーテルライト',
    'クラリス': 'クラリス・エーテルライト', 'アインス': 'アインス・エクスアウラ',
    'カトリーヌ': 'カトリーヌ・オベール', 'セナ': 'セナ・ユニヴェール',
    'ルルーナ': 'ルルーナ・ゼンディア', 'ユーフィリア': 'コードΩ00ユーフィリア',
    'エルセア': 'エルセア=エコルダ', 'ゼシカ': 'システム＝NPゼシカ',
}


def rows(name):
    return json.loads(Path(f'.venv/gacha_sources/{name}.json').read_text(encoding='utf-8'))


def build():
    names = {normalize(p['progressName']): p['progressName'] for p in progressData}
    cards = []
    seen = set()
    for rarity in ('UR', 'SR', 'HR', 'R'):
        for row in rows(rarity):
            if len(row) < 5 or row[0] or row[1] or not row[3].isdigit():
                continue
            name = row[2]
            base = re.split(r'[【(（]', name)[0].strip()
            character = names.get(normalize(ALIASES.get(base, base)))
            if not character:
                continue  # Excludes collaboration characters outside progress.py.
            skill = re.split(r'cost\s*[：:]|\(真・|（真・', row[-1], flags=re.I)[0].strip('● ')
            signature = (rarity, name, int(row[3]), skill)
            if signature in seen:
                continue
            seen.add(signature)
            identity = hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest()[:16]
            cards.append(dict(id='vierge-' + identity, character=character, name=name,
                              rarity=rarity, cost=int(row[3]), skill=skill))
    covered = {card['character'] for card in cards}
    for additions_path in (Path('gacha_additions.json'), Path('gacha_manual_cards.json')):
        if not additions_path.exists():
            continue
        for item in json.loads(additions_path.read_text(encoding='utf-8')):
            if item['character'] not in {p['progressName'] for p in progressData}:
                raise ValueError('Additional card is outside progress.py')
            signature = (item['rarity'], item['name'], item.get('cost'), item.get('skill', ''))
            if signature in seen:
                continue
            seen.add(signature)
            identity = hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest()[:16]
            cards.append(dict(id='vierge-' + identity, **item))
        covered = {card['character'] for card in cards}
    relink = []
    for row in rows('relink'):
        if len(row) != 8 or row[2] not in ('★1', '★2', '★3') or row[-1] != '恒常':
            continue
        identity = hashlib.sha256((row[1] + row[2]).encode()).hexdigest()[:16]
        relink.append(dict(id='relink-' + identity, character=row[1], name=row[1], rarity=row[2]))
    catalog = {'schema': 1, 'games': {
        'vierge': {'sources': [SOURCES[r] for r in ('UR', 'SR', 'HR', 'R')] + [
                    'https://ange.webcraft.work/ext/', 'https://ange.webcraft.work/q_a_begginer/',
                    'https://www.gamer.ne.jp/news/201903010060/',
                    'https://www.4gamer.net/games/234/G023460/20200217084/',
                    'https://buhitter.com/search?offset=20&q=ange_gb'],
                   'note': '公開攻略表で確認できたカードを集めたBot用プール。イベントカードを含むため、当時のゴールドガチャの収録内容そのものではありません。カード別の割合は同レアリティ内で均等です。',
                   'missing_characters': [p['progressName'] for p in progressData if p['progressName'] not in covered],
                   'cards': cards},
        'relink': {'sources': [SOURCES['relink'], 'https://gamerch.com/ange-relink/895716'],
                   'note': '2024-09-10更新の公開攻略表に載る恒常カード37種。限定衣装・ピックアップ・★3確定ゲージは含みません。同レアリティ内は均等です。',
                   'missing_characters': [], 'cards': relink},
    }}
    Path('gacha_catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for game, value in catalog['games'].items():
        print(game, len(value['cards']), 'cards;', len(value['missing_characters']), 'unverified characters')


if __name__ == '__main__':
    build()
