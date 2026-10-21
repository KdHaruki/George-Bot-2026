import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from dataclasses import asdict
import discord
from discord import app_commands
from gacha import Gacha
from gacha_commands import register_gacha_commands
from relink_presentations import PRESENTATIONS, star3_embeds
from scripts.fetch_relink_presentations import extract
from pathlib import Path
import tempfile
from relink_presentations import presentation_files, local_image


class PresentationTests(unittest.TestCase):
    def test_local_attachment_and_missing_file_never_use_remote_url(self):
        card = Gacha().pools['relink']['★3'][0]
        with tempfile.TemporaryDirectory() as directory:
            with patch('relink_presentations.IMAGE_DIRECTORY', Path(directory)):
                self.assertFalse(star3_embeds([card])[0].thumbnail.url)
                self.assertEqual(presentation_files([card]), [])
                path = Path(directory) / (card.id + '.png')
                path.write_bytes(b'\x89PNG test')
                embed = star3_embeds([card, card])[0]
                self.assertEqual(embed.image.url, 'attachment://' + path.name)
                self.assertFalse(embed.thumbnail.url)
                self.assertFalse(embed.footer.text)
                files = presentation_files([card, card])
                try:
                    self.assertEqual(len(files), 1)
                    self.assertEqual(files[0].filename, path.name)
                finally:
                    for file in files:
                        file.close()

    def test_all_star3_outfits_have_distinct_registered_images_and_short_quotes(self):
        engine = Gacha()
        cards = engine.pools['relink']['★3']
        self.assertEqual({card.id for card in cards}, PRESENTATIONS.keys())
        self.assertEqual(len({entry['image'] for entry in PRESENTATIONS.values()}), 46)
        for card in cards:
            entry = PRESENTATIONS[card.id]
            self.assertEqual(entry['name'], card.name)
            self.assertTrue(1 <= len(entry['quote']) <= 120)
            self.assertTrue(entry['image'].startswith('https://cdn.gamerch.com/'))
            path = local_image(card.id)
            self.assertIsNotNone(path)
            self.assertTrue(0 < path.stat().st_size <= 2 * 1024 * 1024)
        rosalie = next(card for card in cards if card.character == 'ロザリー')
        self.assertEqual(rosalie.name, 'ロザリー【幻影のドレス】')
        self.assertEqual(PRESENTATIONS[rosalie.id]['quote'], 'キミのこと、\nずーーっと待ってたよ！')
        embeds = star3_embeds([rosalie, rosalie] + engine.pools['relink']['★1'][:1])
        self.assertEqual(len(embeds), 2)
        self.assertIn('×2', embeds[0].title)
        self.assertFalse(embeds[0].description)
        self.assertEqual(embeds[1].description, PRESENTATIONS[rosalie.id]['quote'])

    def test_import_preserves_exact_punctuation_and_newlines(self):
        raw = '<img data-src="https://cdn.gamerch.com/banner"><div class="mu__box"><p>キミのこと、<br />ずーーっと待ってたよ！</p></div><h2 id="outline__%E5%9F%BA%E6%9C%AC%E6%83%85%E5%A0%B1"'
        quote, image = extract(raw)
        self.assertEqual(quote, 'キミのこと、\nずーーっと待ってたよ！')
        self.assertEqual(image, 'https://cdn.gamerch.com/banner')


class PresentationCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_star3_result_sent_before_art_and_art_failure_is_optional(self):
        card = Gacha().pools['relink']['★3'][0]
        store = SimpleNamespace(url='test', owned=Mock(return_value=[]), save_draw=Mock(return_value=[dict(card=asdict(card), quantity=1, new=True)]),
                                favorite=Mock(return_value=None), batch_counts=Mock(return_value={'relink': 100}))
        client = discord.Client(intents=discord.Intents.default())
        bot = SimpleNamespace(tree=app_commands.CommandTree(client))
        register_gacha_commands(bot, store)
        interaction = SimpleNamespace(id=10, user=SimpleNamespace(id=1), response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock(side_effect=[None, RuntimeError('art failure')])))
        await bot.tree.get_command('ガチャ').callback(interaction, 'relink')
        calls = interaction.followup.send.call_args_list
        self.assertIn(card.name, calls[0].kwargs['embed'].description)
        self.assertEqual(calls[1].kwargs['embeds'][1].description, PRESENTATIONS[card.id]['quote'])
        self.assertFalse(calls[1].kwargs['allowed_mentions'].everyone)
        store.save_draw.assert_called_once()
        await client.close()
