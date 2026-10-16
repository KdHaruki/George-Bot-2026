"""One-off, sequential image archive. Never run during bot startup or draws."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

USER_AGENT = 'GeorgeBotImageArchive/1.0'
INTERVAL = 4
MAX_BYTES = 2 * 1024 * 1024
EXTENSIONS = {b'\x89PNG': '.png', b'\xff\xd8\xff': '.jpg'}


def download(metadata='relink_presentations.json', destination='assets/relink'):
    records = json.loads(Path(metadata).read_text(encoding='utf-8'))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    pending = {key: value for key, value in records.items() if not any(
        (destination / (key + extension)).is_file() for extension in ('.png', '.jpg', '.webp'))}
    if not pending:
        print(f'Complete: downloaded=0, reused={len(records)}', flush=True)
        return
    robots = urllib.robotparser.RobotFileParser()
    robots_url = 'https://cdn.gamerch.com/robots.txt'
    try:
        with urllib.request.urlopen(urllib.request.Request(robots_url, headers={'User-Agent': USER_AGENT}), timeout=20) as response:
            robots.parse(response.read(256000).decode('utf-8', errors='replace').splitlines())
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        robots.parse([])
    delay = max(INTERVAL, robots.crawl_delay(USER_AGENT) or robots.crawl_delay('*') or 0)
    downloaded, skipped = 0, len(records) - len(pending)
    for card_id, entry in pending.items():
        url = entry['image']
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'cdn.gamerch.com' or not robots.can_fetch(USER_AGENT, url):
            raise ValueError('Image URL is not permitted')
        time.sleep(delay)
        # Stop on any error, including 429/503. No immediate retries or concurrency.
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}), timeout=25) as response:
            if urllib.parse.urlparse(response.url).netloc != 'cdn.gamerch.com':
                raise ValueError('Unexpected image redirect')
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Image exceeds size limit')
        extension = next((ext for signature, ext in EXTENSIONS.items() if data.startswith(signature)), None)
        if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            extension = '.webp'
        if not extension:
            raise ValueError('Unsupported image content')
        target = destination / (card_id + extension)
        partial = target.with_suffix('.part')
        partial.write_bytes(data)
        partial.replace(target)
        downloaded += 1
        print(f'Saved {downloaded + skipped}/{len(records)} ({len(data)} bytes)', flush=True)
    print(f'Complete: downloaded={downloaded}, reused={skipped}', flush=True)


if __name__ == '__main__':
    download()
