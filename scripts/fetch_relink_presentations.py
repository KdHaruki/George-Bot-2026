"""Manual Wiki import: one short opening quote and matching banner per ★3.

Never invoked by the bot. Does not download image files.
"""
import concurrent.futures
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href', '').startswith('https://gamerch.com/ange-relink/'):
            self.links[attrs.get('title', '')] = attrs['href']


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)


def extract(raw):
    # Only the opening catchphrase immediately before Basic Information.
    head = raw.split('<h2 id="outline__%E5%9F%BA%E6%9C%AC%E6%83%85%E5%A0%B1"', 1)[0]
    boxes = list(re.finditer(r'<div class="mu__box"[^>]*>(.*?)</div>', head, re.S))
    if not boxes:
        raise ValueError('Opening quote box not found')
    box = boxes[-1]
    parser = Text()
    parser.feed(box.group(1))
    quote = '\n'.join(line.strip() for line in ''.join(parser.parts).strip().splitlines() if line.strip())
    if not 1 <= len(quote) <= 120:
        raise ValueError('Opening quote length requires review')
    images = re.findall(r'<img\b[^>]*\bdata-src="([^"]+)"', head[:box.start()])
    image = unescape(images[-1]) if images else ''
    if not image.startswith('https://cdn.gamerch.com/'):
        raise ValueError('Character banner not found')
    return quote, image


def build():
    outfits = json.loads(Path('relink_outfits.json').read_text(encoding='utf-8'))
    catalog = json.loads(Path('gacha_catalog.json').read_text(encoding='utf-8'))
    cards = [card for card in catalog['games']['relink']['cards'] if card['rarity'] == '★3']
    links = Links()
    links.feed(Path('.venv/gacha_sources/relink.html').read_text(encoding='utf-8'))
    destination = Path('.venv/gacha_sources/presentations')
    destination.mkdir(parents=True, exist_ok=True)

    def fetch(card):
        source = outfits[card['id']]['source']
        path = destination / (card['id'] + '.html')
        if not path.exists():
            path.write_bytes(urllib.request.urlopen(source, timeout=25).read())
        quote, image = extract(path.read_text(encoding='utf-8'))
        return card['id'], dict(name=card['name'], quote=quote, image=image, source=source)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        records = dict(pool.map(fetch, cards))
    Path('relink_presentations.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Imported {len(records)} short quotes and banner URLs; no image files downloaded.')


if __name__ == '__main__':
    build()
