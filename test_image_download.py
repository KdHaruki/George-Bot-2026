import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from scripts.download_relink_images import download


class DownloadTests(unittest.TestCase):
    def test_sequential_delay_and_cached_files_require_no_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / 'images.json'
            target = root / 'assets'
            metadata.write_text(json.dumps({'card': {'image': 'https://cdn.gamerch.com/a'}}))
            robots = io.BytesIO(b'User-agent: *\nAllow: /\nCrawl-delay: 6\n')
            response = io.BytesIO(b'\x89PNG test data')
            response.url = 'https://cdn.gamerch.com/a'
            with patch('scripts.download_relink_images.urllib.request.urlopen', side_effect=[robots, response]) as request, patch('scripts.download_relink_images.time.sleep') as sleep:
                download(metadata, target)
                self.assertEqual(request.call_count, 2)
                sleep.assert_called_once_with(6)
            self.assertTrue((target / 'card.png').is_file())
            with patch('scripts.download_relink_images.urllib.request.urlopen') as request:
                download(metadata, target)
                request.assert_not_called()

    def test_rate_limit_stops_without_retry_or_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / 'images.json'
            target = root / 'assets'
            metadata.write_text(json.dumps({'card': {'image': 'https://cdn.gamerch.com/a'}, 'other': {'image': 'https://cdn.gamerch.com/b'}}))
            error = urllib.error.HTTPError('https://cdn.gamerch.com/a', 429, 'limit', {}, None)
            with patch('scripts.download_relink_images.urllib.request.urlopen', side_effect=[io.BytesIO(b'User-agent: *\nAllow: /'), error]) as request, patch('scripts.download_relink_images.time.sleep'):
                with self.assertRaises(urllib.error.HTTPError):
                    download(metadata, target)
                self.assertEqual(request.call_count, 2)
            self.assertEqual(list(target.iterdir()), [])
