"""Verify a missing character's rarity from its individual status page."""
import concurrent.futures
import html
import json
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from progress import progressData
from scripts.build_gacha_catalog import ALIASES, normalize
from scripts.fetch_gacha_sources import Tables


def fetch(candidate):
    character, name, url, skill = candidate
    parser = Tables()
    parser.feed(urllib.request.urlopen(url, timeout=30).read().decode('utf-8'))
    info = dict(row for row in parser.rows if len(row) == 2)
    rarity = info['レアリティ']
    # LR is the evolved form of UR, not a separate gacha rarity.
    # Rule: https://ange.webcraft.work/q_a_begginer/
    if rarity == 'LR':
        rarity = 'UR'
    if rarity not in ('UR', 'SR', 'HR', 'R'):
        raise ValueError(f'Unsupported rarity: {rarity}')
    cost = int(re.search(r'\d+', info['コスト']).group())
    name = info['名称'].lstrip('☆')
    skill = re.split(r'\s*コスト[：:]', info.get('エクシード', ''))[0]
    return dict(character=character, name=name, rarity=rarity, cost=cost, skill=skill, source=url)


if __name__ == '__main__':
    root = 'https://ange.webcraft.work/ext/'
    raw = urllib.request.urlopen(root, timeout=30).read().decode('utf-8')
    parser = Tables()
    parser.feed(raw)
    names = {normalize(p['progressName']): p['progressName'] for p in progressData}
    # Only retrieve one proven card per as-yet uncovered character; do not crawl the site.
    missing = set(json.loads(Path('gacha_catalog.json').read_text(encoding='utf-8'))['games']['vierge']['missing_characters'])
    links = {html.unescape(label): root + href for href, label in re.findall(r'<a href="(single\.php\?id=\d+)">([^<]+)</a>', raw)}
    path = Path('gacha_additions.json')
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    selected = {item['character']: (item['character'], item['name'], item['source'], '') for item in previous}
    for row in parser.rows:
        if len(row) != 10 or row[2] not in links:
            continue
        name = row[2].lstrip('☆')
        base = re.split(r'[【(（]', name)[0].strip()
        character = names.get(normalize(ALIASES.get(base, base)))
        if character in missing and character not in selected:
            selected[character] = (character, name, links[row[2]], row[8])
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        additions = list(pool.map(fetch, selected.values()))
    path.write_text(json.dumps(additions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Verified individual cards:', len(additions))
