"""Resolve short character names to one shared profile identity."""
import unicodedata
from functools import lru_cache
from progress import progressData


NAME_ALIASES = {'空': '久遠空', '葵': '御影葵', '遥': '東条遥'}


def normalize(name):
    return ''.join(unicodedata.normalize('NFKC', name).split()).casefold()


@lru_cache(maxsize=1024)
def profile_for(character):
    character = NAME_ALIASES.get(character, character)
    exact = [r for r in progressData if normalize(r['progressName']) == normalize(character)]
    if not exact:
        exact = [r for r in progressData if any(normalize(r.get(f'progressNickname{i}', '')) == normalize(character)
                                               for i in range(1, 4))]
    matches = exact or [r for r in progressData if len(normalize(character)) >= 2
                        and normalize(character) in normalize(r['progressName'])]
    return matches[0] if len(matches) == 1 else None


def character_key(character):
    record = profile_for(character)
    return record['progressName'] if record else character
