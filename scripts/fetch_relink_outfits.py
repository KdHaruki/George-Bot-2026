"""Read the exact 衣装 field; reuse cached pages and fetch missing pages slowly."""
import json
from pathlib import Path
import time
import urllib.request
from scripts.fetch_gacha_sources import Tables
from scripts.fetch_relink_presentations import Links
from gacha import outfit_display_name


def build():
    cards = json.loads(Path('gacha_catalog.json').read_text(encoding='utf-8'))['games']['relink']['cards']
    links = Links()
    links.feed(Path('.venv/gacha_sources/relink.html').read_text(encoding='utf-8'))
    output = {}
    saved = json.loads(Path('relink_outfits.json').read_text(encoding='utf-8')) if Path('relink_outfits.json').exists() else {}
    for card in cards:
        wiki_name = saved.get(card['id'], {}).get('wiki_name', card['name'])
        source = links.links[wiki_name]
        path = Path('.venv/gacha_sources/presentations') / (card['id'] + '.html')
        if not path.exists():
            time.sleep(4)
            path.write_bytes(urllib.request.urlopen(urllib.request.Request(source, headers={'User-Agent': 'GeorgeBotDataArchive/1.0'}), timeout=25).read())
        parser = Tables()
        parser.feed(path.read_text(encoding='utf-8'))
        outfits = [row[1] for row in parser.rows if len(row) == 2 and row[0] == '衣装']
        if len(outfits) != 1 or not outfits[0]:
            raise ValueError(f'Outfit requires review: {card["id"]}')
        output[card['id']] = dict(wiki_name=wiki_name, outfit=outfits[0],
                                  name=outfit_display_name(card['character'], outfits[0]), source=source)
        print(f'Checked {len(output)}/{len(cards)}', flush=True)
    Path('relink_outfits.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    build()
