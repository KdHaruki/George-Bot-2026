"""Download public rarity tables for offline review (never run by the bot)."""
import concurrent.futures
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.parse
import urllib.request


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []
        elif tag == 'br' and self.cell is not None:
            self.cell.append(' ')

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
            self.cell = None


SOURCES = {rarity: 'https://ange.gamerch.com/' + urllib.parse.quote('★' * stars + rarity)
           for rarity, stars in [('UR', 6), ('SR', 5), ('HR', 4), ('R', 3)]}
SOURCES['relink'] = 'https://gamerch.com/ange-relink/791926'


def fetch(item):
    name, url = item
    destination = Path('.venv/gacha_sources')
    destination.mkdir(parents=True, exist_ok=True)
    raw = urllib.request.urlopen(url, timeout=30).read().decode('utf-8')
    (destination / (name + '.html')).write_text(raw, encoding='utf-8')
    parser = Tables()
    parser.feed(raw)
    (destination / (name + '.json')).write_text(json.dumps(parser.rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return name, len(parser.rows)


if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(fetch, SOURCES.items()):
            print(result)
