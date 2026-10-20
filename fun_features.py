import random
import discord
from progress import progressData
from discord_layout import space_headings


# The complete profile list includes Relink-only characters too. Do not use
# the Vierge gacha pool, which deliberately excludes those four characters.
LUCKY_PROGRESS = tuple(sorted({record['progressName'] for record in progressData}))


def fortune_embed(fortune, comment, lucky_progress=None):
    embed = discord.Embed(title='🎍 今日のおみくじ', description=f'## 【{fortune}】', color=0xE2AD48)
    embed.add_field(name='【ジョージの一言】', value=discord.utils.escape_markdown(comment)[:1024], inline=False)
    embed.add_field(name='【ラッキープログレス】', value=discord.utils.escape_markdown(lucky_progress if lucky_progress is not None else random.choice(LUCKY_PROGRESS)), inline=False)
    return space_headings(embed, space_first=False)



FORTUNES = [
    ("大吉", "今日はいい流れが来そうだぜ！ やりたかったことを一つ試してみな。"),
    ("中吉", "焦らずいけばいい感じだな。小さな楽しみを見つけようぜ！"),
    ("小吉", "小さなラッキーも見逃すなよ。好きなものでひと息だぜ！"),
    ("吉", "いつもの一日にも楽しみはあるぜ。気楽にいこうな！"),
    ("末吉", "楽しみは後から来るかもな。今日はじっくりいこうぜ！"),
    ("凶", "そんな日もあるぜ。これは遊びのおみくじだ、気にしすぎず休もうな！"),
]
