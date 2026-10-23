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


def george_name(character):
    """Dialogue name only; never use this as a database or card identity."""
    record = profile_for(character)
    if not record:
        return character
    return record.get('progressGeorgeName', '').strip() or record['progressName']


def george_naming_context(text):
    import json
    names = {record['progressName']: george_name(record['progressName']) for record in progressData
             if record['progressName'] in text}
    return ('\n【ジョージの呼び名指定】本人を呼ぶときは右側の呼び名をそのまま使い、ちゃん・さん等を重ねません。検索語・カード名・称号名・原作台詞は変更しません。\n'
            + json.dumps(names, ensure_ascii=False)) if names else ''


def apply_george_names(text):
    """Normalize generated dialogue in one pass without adding suffixes twice."""
    import re
    replacements = {}
    for record in progressData:
        source = record['progressName']
        target = george_name(source)
        if target != source:
            replacements[source] = target
    # Protect full configured names before matching a canonical-name prefix.
    for target in list(replacements.values()):
        replacements.setdefault(target, target)
    if not replacements:
        return text
    pattern = '|'.join(re.escape(name) for name in sorted(replacements, key=len, reverse=True))
    pattern = r'(?P<name>' + pattern + r')(?P<honorific>ちゃん|さん|様|さま|くん|君)?'
    def substitute(part):
        def replace(match):
            name = match.group('name')
            if re.match(r'の(?:右腕|良き理解者)|【', part[match.end():]):
                return match.group()
            return replacements[name]
        return re.sub(pattern, replace, part)

    # Inline command examples remain searchable using formal character names.
    parts = re.split(r'(`[^`]*`)', text)
    return ''.join(part if part.startswith('`') else substitute(part) for part in parts)
