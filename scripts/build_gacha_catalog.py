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
from gacha import vierge_character_card, RULES, VIERGE_CHARACTERS
from dataclasses import asdict
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
    outfits = json.loads(Path('relink_outfits.json').read_text(encoding='utf-8'))
    cards = [asdict(vierge_character_card(record['progressName'], rarity))
             for rarity, _ in RULES['vierge'].normal for record in VIERGE_CHARACTERS]
    relink = []
    for row in rows('relink'):
        if len(row) != 8 or row[2] not in ('★1', '★2', '★3'):
            continue
        if row[-1] != '恒常' and not (row[-1] == '限定' and row[2] == '★3'):
            continue
        identity = hashlib.sha256((row[1] + row[2]).encode()).hexdigest()[:16]
        character = row[1].split('（', 1)[0]
        if character == 'テオ':
            character = 'テオドーチェ'
        card_id = 'relink-' + identity
        relink.append(dict(id=card_id, character=character, name=outfits[card_id]['name'], rarity=row[2]))
    birthdays = {}
    for row in rows('relink'):
        if len(row) == 10:
            matched = re.fullmatch(r'(\d{1,2})月(\d{1,2})日', row[6])
            if matched:
                birthdays[row[1]] = f'{int(matched[1]):02d}-{int(matched[2]):02d}'
    if not {card['character'] for card in relink} <= birthdays.keys():
        raise ValueError('Missing Relink character birthday')
    Path('relink_birthdays.json').write_text(json.dumps({'source': SOURCES['relink'], 'checked': '2026-10-16',
                                                      'birthdays': birthdays}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    catalog = {'schema': 1, 'games': {
        'vierge': {'sources': [], 'note': f'全{len(VIERGE_CHARACTERS)}人×4レアリティのBot独自ガチャ。各レアリティ内はキャラごとに均等。',
                   'missing_characters': [], 'cards': cards},
        'relink': {'sources': [SOURCES['relink'], 'https://gamerch.com/ange-relink/895716'],
                   'note': '公開攻略表の恒常カードと限定衣装の★3を収録。通常は同レアリティ内のカードごとに均等、誕生日当日の★3は対象キャラ合計50％。原作の開催期間・個別ピックアップは再現しません。',
                   'missing_characters': [], 'cards': relink},
    }}
    Path('gacha_catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for game, value in catalog['games'].items():
        print(game, len(value['cards']), 'cards;', len(value['missing_characters']), 'unverified characters')


if __name__ == '__main__':
    build()
