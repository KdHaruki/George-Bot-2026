import discord

SLASH_COMMANDS = [
    ('/プログレス ロザリー', '名前でプロフィールを検索。世界名でも探せるぞ。'),
    ('/おみくじ', '今日の運勢・ラッキーアイテム・ラッキープログレス。'),
    ('/ガチャ アンジュ・ヴィエルジュ', '7連ガチャ。'),
    ('/ガチャ アンジュ・リリンク', '10連ガチャ。'),
    ('/所持カード ロザリー', 'プログレスの所持カードと枚数を確認。'),
    ('/お気に入り ロザリー', 'お気に入りを登録。再指定すると解除。'),
    ('/エクシーズバトル', 'お気に入りとリンクして模擬戦！ 1日3回、勝つと絆が深まるぜ。'),
    ('/収集率', '両作品のコレクションの完成度をまとめて確認。'),
    ('/ガチャ確率', '排出率と保証を確認。'),
    ('/ヘルプ', 'この案内を表示。'),
]
DM_COMMANDS = [
    ('@ジョージ ヘルプ', 'この案内を表示するぜ。'),
    ('@ジョージ ロザリーのことどう思う？', 'メンションや俺への返信で会話できるぜ。'),
]


PUBLIC_COMMANDS = frozenset(('プログレス', 'おみくじ', 'ガチャ'))


def format_commands(entries):
    return '\n\n'.join('`' + command + '`' + ('\n' + explanation if explanation else '') for command, explanation in entries)


def command_help(in_guild, introduction=None):
    embed = discord.Embed(color=0xE2AD48)
    intro = introduction or 'よう、みんな！ 楽しそうな雑談には俺もたまに混ざるし、俺が絵文字でリアクションすることもあるぜ！'
    embed.add_field(name='【ジョージの機能一覧】', value=discord.utils.escape_markdown(intro)[:400] + '\n\u200b', inline=False)
    entries = [(command, explanation + ('' if command.split()[0][1:] in PUBLIC_COMMANDS else '（あなただけに表示されます）'))
               for command, explanation in SLASH_COMMANDS]
    embed.add_field(name='【スラッシュコマンド一覧】', value=format_commands(entries) + '\n\u200b', inline=False)
    embed.add_field(name='【メンション一覧】', value=format_commands(DM_COMMANDS), inline=False)
    return embed
