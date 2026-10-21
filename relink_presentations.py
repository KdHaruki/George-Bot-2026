"""Saved short original catchphrases and Wiki image URLs, keyed by card ID."""
from collections import Counter
import json
from pathlib import Path
import discord


PRESENTATIONS = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
IMAGE_DIRECTORY = Path(__file__).parent / 'assets' / 'relink'


def local_image(card_id):
    if card_id not in PRESENTATIONS:
        return None
    return next((path for extension in ('.png', '.jpg', '.webp')
                 if (path := IMAGE_DIRECTORY / (card_id + extension)).is_file()), None)


def presentation_files(cards):
    files = []
    try:
        for card_id in dict.fromkeys(card.id for card in cards if card.rarity == '★3'):
            path = local_image(card_id)
            if path:
                files.append(discord.File(path, filename=path.name))
        return files
    except Exception:
        for file in files:
            file.close()
        raise


def star3_embeds(cards):
    counts = Counter(card.id for card in cards if card.rarity == '★3')
    card_names = {card.id: card.name for card in cards}
    result = []
    for card_id, quantity in counts.items():
        entry = PRESENTATIONS.get(card_id)
        if not entry:
            continue
        title = f"【★3】{card_names[card_id]}" + (f' ×{quantity}' if quantity > 1 else '')
        embed = discord.Embed(title=title, color=0xE2AD48)
        path = local_image(card_id)
        if path:
            embed.set_image(url='attachment://' + path.name)
            embed.set_footer(text=entry['quote'])
            result.append(embed)
        else:
            embed.description = discord.utils.escape_markdown(entry['quote'])
            result.append(embed)
    return result
