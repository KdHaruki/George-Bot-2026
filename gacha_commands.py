"""ガチャ・所持カード・お気に入りのコマンドを登録し、保存と結果表示を進める。"""

# 表示は collection_display / gacha_display、保存は CollectionStore に任せる。
# 保存成功を確認してから結果を返し、AIコメントや画像の失敗で保存結果を失わない。

import asyncio
import logging

import discord
from discord import app_commands

from collection_display import CardListView, favorite_art, favorite_card_label, favorite_details, favorite_matches, owned_card_lines
from discord_layout import space_headings
from favorite_album import album_display
from favorite_confirmation import FavoriteRemovalView
from gacha import Card, Gacha, RULES
from gacha_activity import DrawActivity
from gacha_collection import CollectionStore
from gacha_display import collection_facts, gacha_comment, rapid_comment_counts_match, rates_embed, result_embed
from database import MemoryUnavailable
from operation_logging import event as log_event
from present_view import open_presents
from presents import PresentStore, affection_display
from progress_profiles import character_key, normalize, george_name
from relink_presentations import star3_embeds, presentation_files
from result_sharing import ShareView
from title_notifications import notify_titles


GAME_CHOICES = [app_commands.Choice(name=rules.name, value=key) for key, rules in RULES.items()]


def register_gacha_commands(bot, store=None):
    engine = Gacha()
    store = store if store is not None else CollectionStore()
    bot.collection_store = store
    presents = getattr(bot, 'present_store', None) or PresentStore(store.url)
    comment_slots = asyncio.Semaphore(2)
    draw_activity = DrawActivity()

    async def ai_comment(facts, fallback):
        chat = getattr(bot, 'george_chat', None)
        if chat is None:
            log_event('AI・ガチャなどの一言', '定型文に切り替え', reason='AIが未設定')
            return fallback
        try:
            async def generate():
                async with comment_slots:
                    answer = await chat.collection_comment(facts)
                    if facts.get('action') == 'draw':
                        if facts.get('favorite_relation') != 'none' and george_name(facts['favorite_character']) not in answer:
                            log_event('AI・ガチャの一言', '定型文に切り替え', reason='お気に入りへの言及がない')
                            return fallback
                        if facts.get('highest_count', 0) >= 2 and str(facts['highest_count']) not in answer:
                            log_event('AI・ガチャの一言', '定型文に切り替え', reason='最高レアの枚数への言及がない')
                            return fallback
                        if facts.get('rapid_draws') and '球筋に出てるぜ' not in answer:
                            log_event('AI・ガチャの一言', '定型文に切り替え', reason='連続ガチャの決め台詞がない')
                            return fallback
                        if not rapid_comment_counts_match(facts, answer):
                            log_event('AI・ガチャの一言', '定型文に切り替え', reason='ガチャの回数とカード枚数が正しく区別されていない')
                            return fallback
                    return answer
            return await asyncio.wait_for(generate(), timeout=12)
        except Exception as exc:
            log_event('AI・ガチャなどの一言', '定型文に切り替え', error=exc)
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
                log_event('ガチャ', '結果のDB保存を確認できない', 操作ID=interaction.id)
                await interaction.followup.send('ガチャ結果の保存を確認できなかったぜ。`/所持カード`で確認してから、時間をおいて試してくれ。', ephemeral=True)
                return
            log_event('ガチャ', '結果のDB保存完了', 操作ID=interaction.id, 枚数=len(cards))
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
        rapid_count = draw_activity.record(interaction.user.id, interaction.id)
        comment = await ai_comment(collection_facts(作品, cards, saved, favorite, rapid_count), gacha_comment(作品, cards, saved, favorite, rapid_count))
        embed.set_field_at(0, name='【ジョージの一言】', value=discord.utils.escape_markdown(comment), inline=False)
        await interaction.followup.send(embed=space_headings(embed),
                                        allowed_mentions=discord.AllowedMentions.none())
        await notify_titles(interaction, getattr(bot, 'title_store', None))
        if 作品 == 'relink':
            try:
                ids = list(dict.fromkeys(card.id for card in cards if card.rarity == '★3'))
                for offset in range(0, len(ids), 5):
                    batch = [card for card in cards if card.id in ids[offset:offset + 5]]
                    presentations = star3_embeds(batch)
                    files = presentation_files(batch)
                    try:
                        # Each card's art and quote share one embed.
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
            log_event('ガチャ', '受付見送り', reason='連続実行の待ち時間中', 操作ID=interaction.id)
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

    @bot.tree.command(name='所持カード', description='指定したプログレスの所持カードと枚数を確認')
    @app_commands.describe(プログレス='所持しているプログレスを候補から選択。名前を入力して絞り込める')
    async def owned(interaction: discord.Interaction, プログレス: app_commands.Range[str, 1, 100]):
        if not プログレス.strip():
            await interaction.response.send_message('プログレスの名前を指定してくれ！', ephemeral=True)
            return
        await show_cards(interaction, プログレス)

    async def show_cards(interaction, プログレス):
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await asyncio.to_thread(store.owned, interaction.user.id)
        except MemoryUnavailable as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        query = normalize(character_key(プログレス.strip()))
        rows = [(game, card, count) for game, card, count in rows
                if (not query or query in normalize(character_key(card.character) + card.name))]
        lines = owned_card_lines(rows)
        empty = '該当するカードはまだないぜ！ `/ガチャ`で集めてみてくれ。'
        view = CardListView(interaction.user.id, lines, '所持カード', can_share=getattr(interaction, 'guild', None) is not None) if len(lines) > 10 else None
        embed = view.embed() if view else discord.Embed(title='所持カード', description='\n'.join(lines) or empty, color=0xE2AD48)
        if view is None and lines:
            snapshot = embed.copy()
            view = ShareView(interaction.user.id, lambda: ([snapshot.copy()], []), enabled=getattr(interaction, 'guild', None) is not None)
        options = {'view': view} if view is not None else {}
        message = await interaction.followup.send(embed=space_headings(embed), ephemeral=True, wait=True,
            allowed_mentions=discord.AllowedMentions.none(), **options)
        if view is not None:
            view.message = message

    async def progress_autocomplete(interaction: discord.Interaction, current: str):
        try:
            rows = await asyncio.wait_for(asyncio.to_thread(store.owned, interaction.user.id), timeout=2)
        except (MemoryUnavailable, asyncio.TimeoutError):
            return []
        query = normalize(current)
        names = sorted({character_key(card.character) for _, card, _ in rows
                        if query in normalize(character_key(card.character)) or query in normalize(card.character)})
        return [app_commands.Choice(name=name[:100], value=name) for name in names[:25]]

    # お気に入り登録と同じ、本人の所持カードだけから作る候補を使う。
    owned.autocomplete('プログレス')(progress_autocomplete)

    favorite_group = app_commands.Group(name='お気に入り', description='プログレスの登録・確認・プレゼント')
    bot.tree.add_command(favorite_group)

    @favorite_group.command(name='プログレス登録', description='ガチャで獲得したプログレスを登録（同じ本人の再指定で解除確認）')
    @app_commands.describe(プログレス='ガチャで獲得したプログレス名。同じプログレスの再指定で解除確認')
    @app_commands.autocomplete(プログレス=progress_autocomplete)
    async def favorite_command(interaction: discord.Interaction, プログレス: app_commands.Range[str, 1, 100]):
        await show_favorite(interaction, プログレス)

    @favorite_group.command(name='プログレス確認', description='お気に入りのプロフィール・好感度・アルバムを確認')
    async def favorite_view(interaction: discord.Interaction):
        await show_favorite(interaction)

    @favorite_group.command(name='プレゼント', description='所持しているプレゼントをお気に入りに贈る')
    async def favorite_present(interaction: discord.Interaction):
        await open_presents(interaction, presents)

    async def show_favorite(interaction, プログレス=None):
        await interaction.response.defer(ephemeral=True)
        try:
            if プログレス is not None:
                rows = await asyncio.to_thread(store.owned, interaction.user.id)
                matches = favorite_matches(rows, プログレス)
                names = {character_key(row[1].character) for row in matches}
                if not matches:
                    raise ValueError('そのプログレスはまだ持っていないぜ。`/ガチャ` で獲得したプログレスを登録してくれ！')
                if len(names) > 1:
                    raise ValueError('複数のプログレスが見つかったぜ。候補から名前を選び直してくれ！')
                # Persist an owned anchor for compatibility with existing affection/title data.
                picked = sorted(matches, key=lambda row: (row[0], row[1].id))[0]
                game, card, _ = picked
                current = await asyncio.to_thread(store.favorite, interaction.user.id)
                if current and character_key(current[1].character) == character_key(card.character):
                    character = character_key(card.character)
                    view = FavoriteRemovalView(interaction.user.id, store, character)
                    view.message = await interaction.followup.send(
                        f'**{discord.utils.escape_markdown(character)}**のお気に入り登録を解除する？\n'
                        '所持カード・好感度・アルバムは残るぜ。\n操作期限：3分。何も押さなければ登録はそのままだぞ！',
                        view=view, ephemeral=True, wait=True, allowed_mentions=discord.AllowedMentions.none())
                    return
                # 確認前の再指定や同時操作で、意図せず解除しない。
                selected = await asyncio.to_thread(store.set_favorite, interaction.user.id, game, card.id)
            else:
                selected = await asyncio.to_thread(store.favorite, interaction.user.id)
            if selected is None:
                await interaction.followup.send('お気に入りはまだないぜ。`/お気に入り プログレス登録`でプログレスを選んでくれ！', ephemeral=True)
                return
            game, card, count = selected
            rows = await asyncio.to_thread(store.owned, interaction.user.id)
            character_rows = [row for row in rows if character_key(row[1].character) == character_key(card.character)]
            embed = discord.Embed(title='⭐ お気に入り' + ('を登録したぜ！' if プログレス else ''),
                                  description=f'**{discord.utils.escape_markdown(character_key(card.character))}**', color=0xE2AD48)
            introduction = favorite_details(card)
            embed.add_field(name='【ジョージのプログレス紹介】', value=discord.utils.escape_markdown(introduction)[:1024], inline=False)
            try:
                points, perfect = await asyncio.to_thread(presents.affection_status, interaction.user.id, card.character)
                embed.add_field(name='【好感度】', value=affection_display(points, perfect), inline=False)
            except MemoryUnavailable:
                embed.add_field(name='【好感度】', value='保存先を確認できなかったぜ。あとでもう一度試してくれ。', inline=False)
            try:
                dates = await asyncio.to_thread(presents.album, interaction.user.id, card.character)
                embed.add_field(name='【アルバム】', value=album_display(dates), inline=False)
            except MemoryUnavailable:
                embed.add_field(name='【アルバム】', value='保存先を確認できなかったぜ。あとでもう一度試してくれ。', inline=False)
            lines = owned_card_lines(character_rows)
            chunks, chunk = [], ''
            for line in lines:
                if chunk and len(chunk) + len(line) + 1 > 1000:
                    chunks.append(chunk)
                    chunk = ''
                chunk += ('\n' if chunk else '') + line
            chunks.append(chunk or '所持カードはまだないぜ。')
            for index, text in enumerate(chunks):
                embed.add_field(name='【所持カード】' if index == 0 else '【所持カード（続き）】', value=text, inline=False)
            # The character's saved Relink artwork is independent of owned rarity/outfit.
            art = favorite_art(engine, card.character)
            snapshot = space_headings(embed).copy()
            def public_favorite():
                files = presentation_files([art]) if art is not None else []
                try:
                    images = star3_embeds([art])[:1] if files else []
                except Exception:
                    for file in files:
                        file.close()
                    raise
                for image in images:
                    image.title = favorite_card_label(art)
                return [snapshot.copy(), *images], files
            share = ShareView(interaction.user.id, public_favorite, enabled=getattr(interaction, 'guild', None) is not None)
            share.message = await interaction.followup.send(embed=snapshot, view=share, wait=True,
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            await notify_titles(interaction, getattr(bot, 'title_store', None))
            if art is not None:
                files = presentation_files([art])
                try:
                    if files:
                        images = star3_embeds([art])[:1]
                        for image in images:
                            image.title = favorite_card_label(art)
                        await interaction.followup.send(embeds=images, files=files, ephemeral=True,
                                                        allowed_mentions=discord.AllowedMentions.none())
                except Exception as exc:
                    logging.warning('Favorite presentation skipped: type=%s', type(exc).__name__)
                finally:
                    for file in files:
                        file.close()
        except (ValueError, MemoryUnavailable) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
