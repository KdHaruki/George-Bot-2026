"""Discord entry points for the local, free gacha simulator."""
import discord
from discord import app_commands

from gacha import Gacha, RULES


GAME_CHOICES = [app_commands.Choice(name=rules.name, value=key) for key, rules in RULES.items()]


def result_embed(engine, game, cards):
    rules = RULES[game]
    catalog = engine.catalog['games'][game]
    lines = []
    for index, card in enumerate(cards, 1):
        guaranteed = len(cards) == rules.batch_size and index == len(cards)
        text = discord.utils.escape_markdown(card.label)
        lines.append(f'{index}. **{card.rarity}** {text}' + (' 【確定枠】' if guaranteed else ''))
    embed = discord.Embed(title=f'{rules.name}：{len(cards)}回ガチャ',
                          description='\n'.join(lines), color=0xB06FE0)
    embed.add_field(name='ジョージの一言', value='いい出会いはあったか？ また気軽に引いてくれよな！', inline=False)
    if game == 'vierge':
        missing = len(catalog['missing_characters'])
        embed.add_field(name='収録範囲', value=f'資料で確認できたカードのプールだぜ。未確認のキャラは{missing}人。\n当時のガチャ収録内容とは異なるぞ。詳細は `/ガチャ確率`。', inline=False)
    embed.set_footer(text='無料シミュレーター・所持品の保存なし・同じレアリティ内は均等抽選')
    return embed


def rates_embed(engine, game):
    rules = RULES[game]
    catalog = engine.catalog['games'][game]
    embed = discord.Embed(title=f'{rules.name}：排出率・収録範囲',
                          description=engine.rates_text(game), color=0xB06FE0)
    embed.add_field(name='このBotの収録内容', value=catalog['note'], inline=False)
    if game == 'vierge':
        embed.add_field(name='確率の根拠', value='提供してもらったゲーム内「通常時」の提供割合。UR/SR2倍は適用しないぞ。', inline=False)
    missing = catalog['missing_characters']
    if missing:
        embed.add_field(name=f'カード情報未確認：{len(missing)}人', value='、'.join(missing), inline=False)
    links = []
    for index, url in enumerate(catalog['sources'], 1):
        link = f'[資料{index}]({url})'
        if len('\n'.join(links + [link])) > 900:
            embed.add_field(name='カード情報の資料', value='\n'.join(links), inline=False)
            links = []
        links.append(link)
    if links:
        embed.add_field(name='カード情報の資料', value='\n'.join(links), inline=False)
    return embed


def register_gacha_commands(bot):
    engine = Gacha()

    @bot.tree.command(name='ガチャ', description='2作品のカードガチャを無料で試す')
    @app_commands.describe(作品='引きたい作品', 回数='1回／ヴィエルジュ7連／リリンク10連')
    @app_commands.choices(作品=GAME_CHOICES, 回数=[app_commands.Choice(name='1回', value=1),
                         app_commands.Choice(name='7連（ヴィエルジュ）', value=7),
                         app_commands.Choice(name='10連（リリンク）', value=10)])
    @app_commands.checks.cooldown(1, 5, key=lambda interaction: interaction.user.id)
    async def draw(interaction: discord.Interaction, 作品: str, 回数: int = 1):
        try:
            cards = engine.draw(作品, 回数)
        except (ValueError, KeyError):
            size = RULES[作品].batch_size if 作品 in RULES else None
            message = f'この作品は1回か{size}連で引いてくれ！' if size else '作品を選び直してくれ！'
            await interaction.response.send_message(message, ephemeral=True)
            return
        await interaction.response.send_message(embed=result_embed(engine, 作品, cards),
                                                allowed_mentions=discord.AllowedMentions.none())

    @draw.error
    async def on_draw_error(interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message('ちょっとひと息だぜ！ 数秒待ってから引いてくれ。', ephemeral=True)
        else:
            raise error

    @bot.tree.command(name='ガチャ確率', description='作品ごとの排出率・収録範囲・未確認キャラを確認する')
    @app_commands.describe(作品='確認したい作品')
    @app_commands.choices(作品=GAME_CHOICES)
    async def rates(interaction: discord.Interaction, 作品: str):
        if 作品 not in RULES:
            await interaction.response.send_message('作品を選び直してくれ！', ephemeral=True)
            return
        await interaction.response.send_message(embed=rates_embed(engine, 作品), ephemeral=True)
