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
from relink_presentations import star3_embeds, presentation_files


GAME_CHOICES = [app_commands.Choice(name=rules.name, value=key) for key, rules in RULES.items()]


class CardListView(discord.ui.View):
    def __init__(self, owner_id, lines, title):
        super().__init__(timeout=180)
        self.owner_id, self.lines, self.title = owner_id, lines, title
        self.page = 0
        self.pages = math.ceil(len(lines) / 10)
        self.previous = discord.ui.Button(label='前へ', disabled=True)
        self.next = discord.ui.Button(label='次へ', disabled=self.pages <= 1)
        self.previous.callback = self.go_previous
        self.next.callback = self.go_next
        self.add_item(self.previous)
        self.add_item(self.next)

    def embed(self):
        return discord.Embed(title=self.title, description='\n'.join(self.lines[self.page * 10:(self.page + 1) * 10]), color=0xB06FE0)

    async def move(self, interaction, step):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('一覧を開いた本人だけが操作できるぜ。', ephemeral=True)
            return
        self.page = min(self.pages - 1, max(0, self.page + step))
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page == self.pages - 1
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def go_previous(self, interaction):
        await self.move(interaction, -1)

    async def go_next(self, interaction):
        await self.move(interaction, 1)


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
    if viewing:
        return dict(action='favorite_view', character=cards[0].character,
                    profiles=[favorite_details(cards[0])[0]])
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
        ownership = ' **✨ NEW**' if is_new else ''
        rarity = f'`【{card.rarity}】` ' if game == 'relink' else f'【{card.rarity}】'
        lines.append(f'{rarity}{text}' + ownership)
    embed = discord.Embed(title=f'{rules.name}：{len(cards)}回ガチャ',
                          description='\n'.join(lines), color=0xB06FE0)
    embed.add_field(name='ジョージの一言', value=discord.utils.escape_markdown(gacha_comment(game, cards, saved, favorite)), inline=False)
    if batch_counts is not None:
        limit = 100 if game == 'relink' else BATCH_GUARANTEE[game]
        progress = batch_counts.get(game, 0) % limit
        message = (f'次回{rules.batch_size}連で{rules.normal[0][0]}'
                   + ('1枚確定！' if game == 'vierge' else '確定！')) if progress == limit - 1 else f'確定まであと{limit - progress}回'
        if game == 'relink':
            remaining = 100 - progress
            message = '次回10連で★3確定！' if remaining <= 10 else f'★3確定まであと{remaining}'
        unit = '' if game == 'relink' else '回'
        embed.add_field(name='ガチャカウント', value=f'{progress}/{limit}{unit}：**{message}**', inline=False)
    if saved is None:
        embed.add_field(name='保存なし', value='DATABASE_URL未設定のため、この結果はコレクションに保存されないぞ。', inline=False)
    return embed


def rates_embed(engine, game):
    rules = RULES[game]
    embed = discord.Embed(title=f'{rules.name}：排出率',
                          description=engine.rates_text(game), color=0xB06FE0)
    embed.add_field(name='連続ガチャの累計保証', value=f'{rules.batch_size}連を{BATCH_GUARANTEE[game]}回引くごとに、最後の1枚が{rules.normal[0][0]}確定。途中で最高レアが出ても回数はリセットしないぞ。', inline=False)
    if game == 'relink':
        embed.set_field_at(0, name='累計カウント保証', value='10連1回で10カウント。100カウント到達ごとの1枚が★3確定。途中の★3ではリセットせず、端数も繰り越すぞ。', inline=False)
        embed.add_field(name='誕生日ピックアップ', value='日本時間の誕生日当日は、★3抽選内で対象の子が合計50％。同日が複数なら均等に分け、残り50％は対象外の★3から抽選。100カウント保証にも適用。★3全体の排出率は変わらないぞ。', inline=False)
    if game == 'vierge':
        embed.add_field(name='7連の周期初回保証', value='カウントが1/4になる7連（累計1・5・9回目…）は最後の1枚がSR以上。UR・SRはそのまま、HR以下ならSRに引き上げるぞ。', inline=False)
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
    @app_commands.describe(作品='ヴィエルジュは7連、リリンクは10連')
    @app_commands.choices(作品=GAME_CHOICES)
    @app_commands.checks.cooldown(1, 5, key=lambda interaction: interaction.user.id)
    async def draw(interaction: discord.Interaction, 作品: str):
        if not store.url and 作品 in RULES:
            await interaction.response.send_message('連続ガチャの保証回数を保存するため、DATABASE_URLの設定が必要だぜ。', ephemeral=True)
            return
        try:
            cards = engine.draw(作品, RULES[作品].batch_size)
        except (ValueError, KeyError):
            message = '作品を選び直してくれ！'
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
        if 作品 == 'relink':
            try:
                ids = list(dict.fromkeys(card.id for card in cards if card.rarity == '★3'))
                for offset in range(0, len(ids), 5):
                    batch = [card for card in cards if card.id in ids[offset:offset + 5]]
                    presentations = star3_embeds(batch)
                    files = presentation_files(batch)
                    try:
                        # Two embeds per card, at most ten embeds in one message.
                        if presentations:
                            await interaction.followup.send(embeds=presentations, files=files,
                                                            allowed_mentions=discord.AllowedMentions.none())
                    finally:
                        for file in files:
                            file.close()
            except Exception as exc:
                # The saved result was already delivered; optional art must not hide it.
                logging.warning('Relink presentation skipped: type=%s', type(exc).__name__)

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
    @app_commands.describe(作品='省略すると両作品', キャラ='名前の一部で絞り込み', レアリティ='省略すると全レアリティ')
    @app_commands.choices(作品=GAME_CHOICES, レアリティ=[app_commands.Choice(name=r, value=r) for r in ('UR', 'SR', 'HR', 'R', '★3', '★2', '★1')])
    async def owned(interaction: discord.Interaction, 作品: str = None, キャラ: app_commands.Range[str, 0, 100] = '',
                    レアリティ: str = None):
        await show_cards(interaction, 作品, キャラ, レアリティ)

    @bot.tree.command(name='未所持カード', description='今のガチャでまだ持っていないカードを探す')
    @app_commands.describe(作品='省略すると両作品', キャラ='名前の一部で絞り込み', レアリティ='省略すると全レアリティ')
    @app_commands.choices(作品=GAME_CHOICES, レアリティ=[app_commands.Choice(name=r, value=r) for r in ('UR', 'SR', 'HR', 'R', '★3', '★2', '★1')])
    async def missing(interaction: discord.Interaction, 作品: str = None, キャラ: app_commands.Range[str, 0, 100] = '',
                      レアリティ: str = None):
        await show_cards(interaction, 作品, キャラ, レアリティ, unowned=True)

    async def show_cards(interaction, 作品, キャラ, レアリティ, unowned=False):
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
        lines = [('⭐ ' if (game, card.id) == favorite_key else '') + f"**{card.rarity}** {discord.utils.escape_markdown(card.label)}" + ('' if unowned else f' — **{count}枚**')
                 for game, card, count in rows]
        empty = ('この条件の未所持カードはないぜ！' if query or レアリティ else '今のガチャ対象は全部そろってるぜ！') if unowned else '該当するカードはまだないぜ！ `/ガチャ`で集めてみてくれ。'
        view = CardListView(interaction.user.id, lines, '未所持カード' if unowned else '所持カード') if len(lines) > 10 else None
        embed = view.embed() if view else discord.Embed(title='未所持カード' if unowned else '所持カード', description='\n'.join(lines) or empty, color=0xB06FE0)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def favorite_autocomplete(interaction: discord.Interaction, current: str):
        try:
            rows = await asyncio.wait_for(asyncio.to_thread(store.owned, interaction.user.id), timeout=2)
        except (MemoryUnavailable, asyncio.TimeoutError):
            return []
        query = current.strip().casefold()
        namespace = getattr(interaction, 'namespace', None)
        character = (getattr(namespace, 'プログレス', None) or '').strip().casefold()
        if not character:
            return []
        rank = {'UR': 0, 'SR': 1, 'HR': 2, 'R': 3, '★3': 0, '★2': 1, '★1': 2}
        rows = sorted(rows, key=lambda row: (0 if row[0] == 'vierge' else 1,
                      rank.get(row[1].rarity, 9), row[1].character, row[1].label, row[1].id))
        return [app_commands.Choice(name=f"{card.rarity} {card.label}（{'ヴィエルジュ' if game == 'vierge' else 'リリンク'}）"[:100],
                                    value=f'{game}:{card.id}') for game, card, _ in rows
                if character in card.character.casefold()
                and (not query or query in (card.character + card.label).casefold())][:25]

    async def progress_autocomplete(interaction: discord.Interaction, current: str):
        try:
            rows = await asyncio.wait_for(asyncio.to_thread(store.owned, interaction.user.id), timeout=2)
        except (MemoryUnavailable, asyncio.TimeoutError):
            return []
        query = current.strip().casefold()
        names = sorted({card.character for _, card, _ in rows if query in card.character.casefold()})
        return [app_commands.Choice(name=name[:100], value=name) for name in names[:25]]

    @bot.tree.command(name='お気に入り', description='プログレスと所持候補から登録・確認（同じカードの再選択で解除）')
    @app_commands.describe(プログレス='先にプログレス名を選ぶ。両項目とも省略すると現在のお気に入りを確認', 選択='プログレスに合う両作品の所持候補から選ぶ')
    @app_commands.autocomplete(プログレス=progress_autocomplete, 選択=favorite_autocomplete)
    async def favorite_command(interaction: discord.Interaction, プログレス: app_commands.Range[str, 1, 100] = None,
                               選択: app_commands.Range[str, 1, 100] = None):
        await interaction.response.defer(ephemeral=True)
        if (プログレス is None) != (選択 is None):
            await interaction.followup.send('先に「プログレス」を入力して、「選択」の候補から選んでくれ！ 確認だけなら両方省略だ。', ephemeral=True)
            return
        try:
            if 選択 is not None:
                game, separator, card_id = 選択.partition(':')
                if not separator or game not in RULES or not card_id:
                    raise ValueError('カード名を入力して、表示される所持カードの候補から選んでくれ！')
                owned_rows = await asyncio.to_thread(store.owned, interaction.user.id)
                if not any(row_game == game and card.id == card_id and プログレス.strip().casefold() in card.character.casefold()
                           for row_game, card, _ in owned_rows):
                    raise ValueError('指定したプログレスに合う自分の所持候補から選んでくれ！')
                selected = await asyncio.to_thread(store.set_favorite, interaction.user.id, game, card_id, toggle=True)
                if selected is None:
                    await interaction.followup.send('お気に入りを解除したぜ。所持カードや枚数はそのままだぞ！', ephemeral=True)
                    return
            else:
                selected = await asyncio.to_thread(store.favorite, interaction.user.id)
            if selected is None:
                await interaction.followup.send('お気に入りはまだないぜ。`/お気に入り`の「プログレス」に名前を入れて、「選択」の候補から選んでくれ！', ephemeral=True)
                return
            game, card, count = selected
            embed = discord.Embed(title='⭐ お気に入り' + ('を登録したぜ！' if 選択 else ''),
                                  description=f'**{card.rarity}** {discord.utils.escape_markdown(card.label)}\n{RULES[game].name}｜所持{count}枚', color=0xB06FE0)
            introduction, comment = favorite_details(card)
            comment = await ai_comment(collection_facts(game, [card], favorite=selected, viewing=True), comment)
            embed.add_field(name='ジョージのプログレス紹介', value=discord.utils.escape_markdown(introduction)[:1024], inline=False)
            embed.add_field(name='ジョージの一言', value=discord.utils.escape_markdown(comment)[:1024], inline=False)
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
        await interaction.followup.send(embed=embed, ephemeral=True)
