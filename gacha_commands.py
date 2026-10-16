"""Discord entry points for the local, free gacha simulator."""
import discord
import asyncio
import math
import logging
import random
from discord import app_commands

from gacha import BATCH_GUARANTEE, Card, Gacha, RULES
from gacha_collection import CollectionStore, collection_summary, unowned_cards
from registered_memory import MemoryUnavailable
from progress import progressData


GAME_CHOICES = [app_commands.Choice(name=rules.name, value=key) for key, rules in RULES.items()]


def favorite_details(card):
    record = next((item for item in progressData if item['progressName'] == card.character), None)
    if record is None:
        # Relink omits surnames or model prefixes; accept only a unique match.
        matches = [item for item in progressData if len(card.character) >= 2 and card.character in item['progressName']]
        if len(matches) == 1:
            record = matches[0]
    detail = record.get('progressDetail1', '') if record else ''
    introduction = f'{card.character}の紹介だぜ！\n{detail}' if detail else f'{card.character}の詳しい紹介は、まだ俺にも分からねえな。'
    comment = random.choice([
        f'お気に入りは{card.character}か！ いいセンスだ！',
        f'{card.character}がお気に入りなんだな！ いいセンスだ！',
        f'おっ、{card.character}じゃねえか！ いいセンスだ！',
    ])
    return introduction, comment


def collection_facts(game, cards, saved=None, favorite=None, viewing=False):
    picked = favorite[1] if favorite and favorite[0] == game else None
    relation = 'none'
    if picked:
        if any(card.id == picked.id for card in cards):
            relation = 'exact_card'
        elif any(card.character == picked.character for card in cards):
            relation = 'same_character_other_card'
    return dict(action='favorite_view' if viewing else 'draw', game=RULES[game].name,
                cards=[dict(name=card.name, character=card.character, rarity=card.rarity) for card in cards],
                saved=saved is not None, new_count=sum(bool(entry['new']) for entry in saved) if saved is not None else None,
                highest=RULES[game].normal[0][0], favorite_relation=relation,
                favorite_character=picked.character if picked else None,
                profiles=[favorite_details(card)[0] for card in {card.character: card for card in cards}.values()][:4])


def gacha_comment(game, cards, saved=None, favorite=None):
    if favorite and favorite[0] == game:
        picked = favorite[1]
        if any(card.id == picked.id for card in cards):
            return random.choice([
                f'お気に入りの{picked.character}が来たぜ！',
                f'{picked.character}、お気に入りにしてた子じゃねえか！ うれしい再会だな！',
                f'おっ、お気に入りの{picked.character}を引けたな！',
            ])
        if any(card.character == picked.character for card in cards):
            return random.choice([
                f'お気に入りの{picked.character}が来たぜ！ 別の一枚も集められてよかったな！',
                f'{picked.character}を引けたな！ お気に入りの子のコレクションが広がるぜ！',
                f'おっ、{picked.character}じゃねえか！ お気に入りの子の別カードもうれしいな！',
            ])
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


def result_embed(engine, game, cards, saved=None, favorite=None, batch_counts=None):
    rules = RULES[game]
    lines = []
    for index, card in enumerate(cards, 1):
        text = discord.utils.escape_markdown(card.label)
        is_new = saved is not None and saved[index - 1]['new']
        ownership = ' **【NEW】**' if is_new else ''
        lines.append(f'`{index:02d}` **{card.rarity}** {text}' + ownership)
    embed = discord.Embed(title=f'{rules.name}：{len(cards)}回ガチャ',
                          description='\n'.join(lines), color=0xB06FE0)
    embed.add_field(name='ジョージの一言', value=discord.utils.escape_markdown(gacha_comment(game, cards, saved, favorite)), inline=False)
    if batch_counts is not None:
        limit = BATCH_GUARANTEE[game]
        progress = batch_counts.get(game, 0) % limit
        message = (f'次回{rules.batch_size}連で{rules.normal[0][0]}'
                   + ('1枚確定！' if game == 'vierge' else '確定！')) if progress == limit - 1 else f'確定まであと{limit - progress}回'
        embed.add_field(name='ガチャカウント', value=f'{progress}/{limit}回：**{message}**', inline=False)
    if saved is None:
        embed.add_field(name='保存なし', value='DATABASE_URL未設定のため、この結果はコレクションに保存されないぞ。', inline=False)
    return embed


def rates_embed(engine, game):
    rules = RULES[game]
    embed = discord.Embed(title=f'{rules.name}：排出率',
                          description=engine.rates_text(game), color=0xB06FE0)
    embed.add_field(name='連続ガチャの累計保証', value=f'{rules.batch_size}連を{BATCH_GUARANTEE[game]}回引くごとに、最後の1枚が{rules.normal[0][0]}確定。途中で最高レアが出ても回数はリセットしないぞ。1回ガチャは対象外。', inline=False)
    return embed


def register_gacha_commands(bot, store=None):
    engine = Gacha()
    store = store if store is not None else CollectionStore()
    comment_slots = asyncio.Semaphore(2)

    async def ai_comment(facts, fallback):
        chat = getattr(bot, 'george_chat', None)
        if chat is None:
            return fallback
        try:
            async def generate():
                async with comment_slots:
                    return await chat.collection_comment(facts)
            return await asyncio.wait_for(generate(), timeout=12)
        except Exception as exc:
            logging.warning('Collection comment fallback: type=%s', type(exc).__name__)
            return fallback

    @bot.tree.command(name='ガチャ', description='2作品のカードガチャを無料で試す')
    @app_commands.describe(作品='引きたい作品', 回数='1回／ヴィエルジュ7連／リリンク10連')
    @app_commands.choices(作品=GAME_CHOICES)
    @app_commands.checks.cooldown(1, 5, key=lambda interaction: interaction.user.id)
    async def draw(interaction: discord.Interaction, 作品: str, 回数: int = 1):
        if not store.url and 作品 in RULES and 回数 == RULES[作品].batch_size:
            await interaction.response.send_message('連続ガチャの保証回数を保存するため、DATABASE_URLの設定が必要だぜ。', ephemeral=True)
            return
        try:
            cards = engine.draw(作品, 回数)
        except (ValueError, KeyError):
            size = RULES[作品].batch_size if 作品 in RULES else None
            message = f'この作品は1回か{size}連で引いてくれ！' if size else '作品を選び直してくれ！'
            await interaction.response.send_message(message, ephemeral=True)
            return
        await interaction.response.defer()
        saved = None
        favorite = None
        batch_counts = None
        if store.url:
            try:
                saved = await asyncio.to_thread(store.save_draw, interaction.user.id, 作品, interaction.id, cards)
                cards = [Card(**entry['card']) for entry in saved]
            except (MemoryUnavailable, ValueError):
                await interaction.followup.send('ガチャ結果の保存を確認できなかったぜ。`/所持カード`で確認してから、時間をおいて試してくれ。', ephemeral=True)
                return
            try:
                favorite = await asyncio.to_thread(store.favorite, interaction.user.id)
            except MemoryUnavailable:
                # Saving succeeded: a failed optional lookup must not hide the result.
                logging.warning('Gacha favorite lookup unavailable')
            try:
                batch_counts = await asyncio.to_thread(store.batch_counts, interaction.user.id)
            except MemoryUnavailable:
                logging.warning('Gacha batch counts lookup unavailable')
        embed = result_embed(engine, 作品, cards, saved, favorite, batch_counts)
        comment = await ai_comment(collection_facts(作品, cards, saved, favorite), gacha_comment(作品, cards, saved, favorite))
        embed.set_field_at(0, name='ジョージの一言', value=discord.utils.escape_markdown(comment), inline=False)
        await interaction.followup.send(embed=embed,
                                        allowed_mentions=discord.AllowedMentions.none())

    @draw.autocomplete('回数')
    async def draw_count(interaction: discord.Interaction, current: int):
        game = getattr(interaction.namespace, '作品', None)
        if game not in RULES:
            return [app_commands.Choice(name='1回（先に作品を選択）', value=1)]
        return [app_commands.Choice(name=f'{count}回', value=count) for count in (1, RULES[game].batch_size)]

    @draw.error
    async def on_draw_error(interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message('ちょっと休憩だぜ！ 少し待ってから引いてくれ。', ephemeral=True)
        else:
            raise error

    @bot.tree.command(name='ガチャ確率', description='2作品の排出率を確認する')
    @app_commands.describe(作品='確認したい作品')
    @app_commands.choices(作品=GAME_CHOICES)
    async def rates(interaction: discord.Interaction, 作品: str):
        if 作品 not in RULES:
            await interaction.response.send_message('作品を選び直してくれ！', ephemeral=True)
            return
        await interaction.response.send_message(embed=rates_embed(engine, 作品), ephemeral=True)

    @bot.tree.command(name='所持カード', description='自分のコレクションを見る（サーバー・DM共通）')
    @app_commands.describe(作品='省略すると両作品', キャラ='名前の一部で絞り込み', レアリティ='省略すると全レアリティ', ページ='1ページ10種類')
    @app_commands.choices(作品=GAME_CHOICES, レアリティ=[app_commands.Choice(name=r, value=r) for r in ('UR', 'SR', 'HR', 'R', '★3', '★2', '★1')])
    async def owned(interaction: discord.Interaction, 作品: str = None, キャラ: app_commands.Range[str, 0, 100] = '',
                    レアリティ: str = None, ページ: app_commands.Range[int, 1, 1000000] = 1):
        await show_cards(interaction, 作品, キャラ, レアリティ, ページ)

    @bot.tree.command(name='未所持カード', description='今のガチャでまだ持っていないカードを探す')
    @app_commands.describe(作品='省略すると両作品', キャラ='名前の一部で絞り込み', レアリティ='省略すると全レアリティ', ページ='1ページ10種類')
    @app_commands.choices(作品=GAME_CHOICES, レアリティ=[app_commands.Choice(name=r, value=r) for r in ('UR', 'SR', 'HR', 'R', '★3', '★2', '★1')])
    async def missing(interaction: discord.Interaction, 作品: str = None, キャラ: app_commands.Range[str, 0, 100] = '',
                      レアリティ: str = None, ページ: app_commands.Range[int, 1, 1000000] = 1):
        await show_cards(interaction, 作品, キャラ, レアリティ, ページ, unowned=True)

    async def show_cards(interaction, 作品, キャラ, レアリティ, ページ, unowned=False):
        await interaction.response.defer(ephemeral=True)
        if 作品 is not None and 作品 not in RULES:
            await interaction.followup.send('作品を選び直してくれ！', ephemeral=True)
            return
        try:
            rows = await asyncio.to_thread(store.owned, interaction.user.id, 作品)
            favorite = None if unowned else await asyncio.to_thread(store.favorite, interaction.user.id)
        except MemoryUnavailable as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        if unowned:
            rows = unowned_cards(engine, rows, 作品)
        query = キャラ.strip().casefold()
        rows = [(game, card, count) for game, card, count in rows
                if (not query or query in (card.character + card.name).casefold())
                and (レアリティ is None or card.rarity == レアリティ)]
        rank = {'UR': 0, 'SR': 1, 'HR': 2, 'R': 3, '★3': 0, '★2': 1, '★1': 2}
        favorite_key = (favorite[0], favorite[1].id) if favorite else None
        rows.sort(key=lambda row: ((row[0], row[1].id) != favorite_key, row[0], rank.get(row[1].rarity, 9), row[1].character, row[1].label, row[1].id))
        pages = max(1, math.ceil(len(rows) / 10))
        if ページ > pages:
            await interaction.followup.send(f'ページは1〜{pages}で指定してくれ！', ephemeral=True)
            return
        lines = [('⭐ ' if (game, card.id) == favorite_key else '') + f"**{card.rarity}** {discord.utils.escape_markdown(card.label)}" + ('' if unowned else f' — **{count}枚**')
                 for game, card, count in rows[(ページ - 1) * 10:ページ * 10]]
        empty = ('この条件の未所持カードはないぜ！' if query or レアリティ else '今のガチャ対象は全部そろってるぜ！') if unowned else '該当するカードはまだないぜ！ `/ガチャ`で集めてみてくれ。'
        embed = discord.Embed(title='未所持カード' if unowned else '所持カード', description='\n'.join(lines) or empty, color=0xB06FE0)
        await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def favorite_autocomplete(interaction: discord.Interaction, current: str):
        try:
            rows = await asyncio.wait_for(asyncio.to_thread(store.owned, interaction.user.id), timeout=2)
        except (MemoryUnavailable, asyncio.TimeoutError):
            return []
        query = current.strip().casefold()
        namespace = getattr(interaction, 'namespace', None)
        character = (getattr(namespace, 'プログレス', None) or '').strip().casefold()
        game_filter = getattr(namespace, '作品', None)
        rank = {'UR': 0, 'SR': 1, 'HR': 2, 'R': 3, '★3': 0, '★2': 1, '★1': 2}
        rows = sorted(rows, key=lambda row: (0 if row[0] == 'vierge' else 1,
                      rank.get(row[1].rarity, 9), row[1].character, row[1].label, row[1].id))
        return [app_commands.Choice(name=f"{card.rarity} {card.label}（{'ヴィエルジュ' if game == 'vierge' else 'リリンク'}）"[:100],
                                    value=f'{game}:{card.id}') for game, card, _ in rows
                if (not game_filter or game == game_filter)
                and (not character or character in card.character.casefold())
                and (not query or query in (card.character + card.label).casefold())][:25]

    @bot.tree.command(name='お気に入り', description='推しの1枚を登録・確認・解除（自分の所持カードから選択）')
    @app_commands.describe(カード='名前を入力して所持カードの候補から選ぶ。省略で確認', 解除='Trueで登録解除。カード自体は消えないぞ',
                           プログレス='先に名前を入力するとカード候補を絞り込む（部分一致）', 作品='カード候補を作品で絞り込む')
    @app_commands.choices(作品=GAME_CHOICES)
    @app_commands.autocomplete(カード=favorite_autocomplete)
    async def favorite_command(interaction: discord.Interaction, カード: app_commands.Range[str, 1, 100] = None, 解除: bool = False,
                               プログレス: app_commands.Range[str, 1, 100] = None, 作品: str = None):
        await interaction.response.defer(ephemeral=True)
        if カード is not None and 解除:
            await interaction.followup.send('登録するカードと解除は、どちらか一つを指定してくれ！', ephemeral=True)
            return
        try:
            if 解除:
                removed = await asyncio.to_thread(store.clear_favorite, interaction.user.id)
                await interaction.followup.send('お気に入りを解除したぜ。所持カードはそのままだぞ！' if removed else 'お気に入りはまだ登録されていないぜ。', ephemeral=True)
                return
            if カード is not None:
                game, separator, card_id = カード.partition(':')
                if not separator or game not in RULES or not card_id:
                    raise ValueError('カード名を入力して、表示される所持カードの候補から選んでくれ！')
                selected = await asyncio.to_thread(store.set_favorite, interaction.user.id, game, card_id)
            else:
                selected = await asyncio.to_thread(store.favorite, interaction.user.id)
            if selected is None:
                await interaction.followup.send('お気に入りはまだないぜ。`/お気に入り`の「カード」に名前を入れて、候補から選んでくれ！', ephemeral=True)
                return
            game, card, count = selected
            embed = discord.Embed(title='⭐ お気に入り' + ('を登録したぜ！' if カード else ''),
                                  description=f'**{card.rarity}** {discord.utils.escape_markdown(card.label)}\n{RULES[game].name}｜所持{count}枚', color=0xB06FE0)
            introduction, comment = favorite_details(card)
            comment = await ai_comment(collection_facts(game, [card], favorite=selected, viewing=True), comment)
            embed.add_field(name='ジョージのプログレス紹介', value=discord.utils.escape_markdown(introduction)[:1024], inline=False)
            embed.add_field(name='ジョージの一言', value=discord.utils.escape_markdown(comment)[:1024], inline=False)
            embed.set_footer(text='ユーザーごとに両作品で1枚・サーバーとDMで共通・所持一覧の先頭に表示')
            await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except (ValueError, MemoryUnavailable) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    @bot.tree.command(name='収集率', description='現在のガチャ収録カードを何種類集めたか確認する')
    @app_commands.describe(作品='省略すると両作品')
    @app_commands.choices(作品=GAME_CHOICES)
    async def completion(interaction: discord.Interaction, 作品: str = None):
        await interaction.response.defer(ephemeral=True)
        if 作品 is not None and 作品 not in RULES:
            await interaction.followup.send('作品を選び直してくれ！', ephemeral=True)
            return
        try:
            rows = await asyncio.to_thread(store.owned, interaction.user.id, 作品)
        except MemoryUnavailable as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        embed = discord.Embed(title='カード収集率', color=0xB06FE0)
        for game in ([作品] if 作品 else RULES):
            unique, total, copies, archived = collection_summary(engine, rows, game)
            text = f'{unique}/{total}種類（{unique / total * 100:.1f}%）\n重複込みの所持数：{copies}枚'
            if archived:
                text += f'\n現在のガチャ対象外：{archived}種類（所持は維持）'
            embed.add_field(name=RULES[game].name, value=text, inline=False)
        embed.set_footer(text='現在このBotのガチャに収録しているカードが分母。過去の結果は遡って登録されません。')
        await interaction.followup.send(embed=embed, ephemeral=True)
