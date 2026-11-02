"""確定済みのガチャ結果から、結果画面・排出率・一言生成用の情報を組み立てる。"""

import random
import re

import discord

from collection_display import favorite_details
from discord_layout import space_headings
from gacha import BATCH_GUARANTEE, RULES
from progress_profiles import character_key, george_name


def draw_highlights(cards):
    from collections import Counter
    counts = Counter(character_key(card.character) for card in cards)
    highlights = []
    if not cards:
        return highlights
    name, count = counts.most_common(1)[0]
    if count >= 3:
        highlights.append(f'{george_name(name)}が{count}枚も来たぜ！ 今日は縁があるな！')
    if len(cards) >= 7 and len(counts) == len(cards):
        highlights.append('全員違う顔ぶれだぜ！ にぎやかな出会いになったな！')
    top = sum(card.rarity in ('UR', '★3') for card in cards)
    if top >= 2:
        highlights.append(f'最高レアが{top}枚！ こいつは見事な引きだぜ！')
    return highlights


def collection_facts(game, cards, saved=None, favorite=None, rapid_count=0):
    picked = favorite[1] if favorite else None
    relation = 'none'
    if picked:
        if favorite[0] == game and any(card.id == picked.id for card in cards):
            relation = 'exact_card'
        elif any(character_key(card.character) == character_key(picked.character) for card in cards):
            relation = 'same_character_other_card'
    return dict(action='draw', game=RULES[game].name, rapid_count=rapid_count,
                batch_card_count=len(cards),
                rapid_draws=rapid_count >= 3, free_simulator=True,
                highest_count=sum(card.rarity == RULES[game].normal[0][0] for card in cards),
                cards=[dict(name=card.name, character=card.character, rarity=card.rarity) for card in cards],
                highlights=draw_highlights(cards), saved=saved is not None, new_count=sum(bool(entry['new']) for entry in saved) if saved is not None else None,
                highest=RULES[game].normal[0][0], favorite_relation=relation,
                favorite_character=picked.character if picked else None,
                profiles=[favorite_details(card) for card in {card.character: card for card in cards}.values()][:4])


def gacha_comment(game, cards, saved=None, favorite=None, rapid_count=0):
    facts = collection_facts(game, cards, saved, favorite, rapid_count)
    special = []
    if facts['favorite_relation'] != 'none':
        name = george_name(facts['favorite_character'])
        special.append(f'お気に入りの{name}が来たぜ！')
    if facts['highest_count'] >= 2:
        special.append(random.choice([
            f"{facts['highest']}が{facts['highest_count']}枚！ 見事な引きだぜ！",
            f"おっ、{facts['highest']}が{facts['highest_count']}枚も来たな！",
        ]))
    if facts['rapid_draws']:
        special.append(random.choice([
            f"立て続けに{rapid_count}回も！ お目当ての子に早く会いたいんだな？ 球筋に出てるぜ！",
            f"もう{rapid_count}回目だな！ 今日は良いことでもあったのか？ 球筋に出てるぜ！",
        ]))
    if special:
        return ' '.join(special)[:140]
    highlights = draw_highlights(cards)
    if highlights:
        return ' '.join(highlights)[:140]
    new_count = sum(entry['new'] for entry in saved) if saved is not None else 0
    highest = RULES[game].normal[0][0]
    rare_count = sum(card.rarity == highest for card in cards)
    if rare_count and new_count:
        return f'{highest}が{rare_count}枚、それに初入手も{new_count}種類だぜ！'
    if rare_count:
        return random.choice([f'{highest}が{rare_count}枚来たぜ！ どの子が気に入った？', f'おっ、{highest}を引けたな！'])
    if new_count:
        return random.choice([f'初入手が{new_count}種類だぜ！ コレクションが広がったな！', f'新しいカードが{new_count}種類も来たぜ！'])
    if saved is not None:
        return random.choice(['今回は持っている顔ぶれだったな。集めた枚数はしっかり増えたぜ！', 'おなじみの顔ぶれが来たぜ！'])
    return random.choice(['今回はこんな顔ぶれだぜ！ 気になる子はいたか？', '結果が出たぜ！ どのかわいこちゃんもじっくり見てみな！'])


def rapid_comment_counts_match(facts, answer):
    """Reject a rapid-run count mistaken for the number of cards drawn."""
    if not facts.get('rapid_draws'):
        return True
    if not re.search(rf"(?<!\d){facts['rapid_count']}回", answer):
        return False
    # Card quantities may refer to the batch, a rarity, a character or new cards.
    cards = facts['cards']
    valid = {facts['batch_card_count'], facts['highest_count'], facts.get('new_count')}
    for field in ('rarity', 'character'):
        valid.update(sum(card[field] == value for card in cards) for value in {card[field] for card in cards})
    return all(int(number) in valid for number in re.findall(r'(\d+)枚', answer))


def result_embed(engine, game, cards, saved=None, favorite=None, batch_counts=None, on_day=None):
    rules = RULES[game]
    lines = []
    rank = {rarity: index for index, (rarity, _) in enumerate(rules.normal)}
    for index, card in sorted(enumerate(cards), key=lambda item: rank.get(item[1].rarity, 99)):
        text = discord.utils.escape_markdown(card.label)
        is_new = saved is not None and saved[index]['new']
        ownership = ' **✨ NEW**' if is_new else ''
        rarity = f'`【{card.rarity}】` ' if game == 'relink' else f'【{card.rarity}】'
        lines.append(f'{rarity}{text}' + ownership)
    embed = discord.Embed(title=f'{rules.name}：{len(cards)}回ガチャ',
                          description='\n'.join(lines), color=0xE2AD48)
    embed.add_field(name='【ジョージの一言】', value=discord.utils.escape_markdown(gacha_comment(game, cards, saved, favorite)), inline=False)
    if batch_counts is not None:
        limit = 100 if game == 'relink' else BATCH_GUARANTEE[game]
        progress = batch_counts.get(game, 0) % limit
        message = (f'次回{rules.batch_size}連で{rules.normal[0][0]}'
                   + ('1枚確定！' if game == 'vierge' else '確定！')) if progress == limit - 1 else f'確定まであと{limit - progress}回'
        if game == 'relink':
            remaining = 100 - progress
            message = '次回10連で★3確定！' if remaining <= 10 else f'★3確定まであと{remaining}'
        unit = '' if game == 'relink' else '回'
        embed.add_field(name='【ガチャカウント】', value=f'{progress}/{limit}{unit}：**{message}**', inline=False)
    if saved is None:
        embed.add_field(name='保存なし', value='DATABASE_URL未設定のため、この結果はコレクションに保存されないぞ。', inline=False)
    names = engine.birthday_targets(on_day, game)
    if names:
        month, day = map(int, engine.birthday_map(game)[names[0]].split('-'))
        highest = rules.normal[0][0]
        embed.add_field(name='【🎂 今日の誕生日ピックアップ】', value=f'{month}月{day}日｜' + '・'.join(names) + f'\n{highest}抽選内で対象キャラが合計50％！', inline=False)
    return space_headings(embed)


def rates_embed(engine, game, on_day=None):
    rules = RULES[game]
    embed = discord.Embed(title=f'【{rules.name}：排出率】',
                          description=engine.rates_text(game), color=0xE2AD48)
    embed.add_field(name='【連続ガチャの累計保証】', value=f'{rules.batch_size}連を{BATCH_GUARANTEE[game]}回引くごとに、最後の1枚が{rules.normal[0][0]}確定。途中で最高レアが出ても回数はリセットしないぞ。', inline=False)
    if game == 'relink':
        embed.set_field_at(0, name='【累計カウント保証】', value='10連1回で10カウント。100カウント到達ごとの1枚が★3確定。途中の★3ではリセットせず、端数も繰り越すぞ。', inline=False)
        embed.add_field(name='【誕生日ピックアップ】', value='日本時間の誕生日当日は、★3抽選内で対象の子が合計50％。同日が複数なら均等に分け、残り50％は対象外の★3から抽選。100カウント保証にも適用。★3全体の排出率は変わらないぞ。', inline=False)
    if game == 'vierge':
        embed.set_field_at(0, name='【7連ガチャの保証】', value='4回を1周期として、最後の1枚に保証が付くぜ！\n1回目（1/4）：SR以上確定。\n4回目（4/4）：UR確定。\n以降も同じ周期で繰り返すぞ。途中でURが出ても回数はリセットしないぜ。', inline=False)
    if game == 'vierge':
        embed.add_field(name='【誕生日ピックアップ】', value='日本時間の誕生日当日は、UR抽選内で対象キャラが合計50％。同日対象は均等、残り50％は対象外から抽選。UR保証にも適用し、UR自体の排出率は変わらないぞ。確認済みの誕生日があるキャラのみ対象。', inline=False)
    upcoming = engine.next_birthday(on_day, game)
    if upcoming:
        day, names = upcoming
        embed.add_field(name='【🎂 次の誕生日】', value=f'{day.month}月{day.day}日｜' + '・'.join(names), inline=False)
    return space_headings(embed)


