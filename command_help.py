import discord

SLASH_COMMANDS = [
    ('/プログレス ロザリー', '名前でプロフィールを検索。世界名でも探せるぞ。'),
    ('/おみくじ', '今日の運勢'),
    ('/アンジュクイズ', 'ヒント付き4択クイズ。正解で1日1回プレゼント！'),
    ('/ガチャ アンジュ・ヴィエルジュ', '7連ガチャ。'),
    ('/ガチャ アンジュ・リリンク', '10連ガチャ。'),
    ('/所持カード ロザリー', 'プログレスの所持カードと枚数を確認。'),
    ('/お気に入り 登録 ロザリー カード', 'レアリティ・衣装を選んで登録。同じカードの再指定で解除。'),
    ('/お気に入り 確認', 'お気に入り・好感度・記念日を確認。'),
    ('/お気に入り プレゼント', '所持アイテムを贈って好感度アップ。'),
    ('/お気に入り 交換', '通常プレゼント3個を別の1個に交換。'),
    ('/称号', '獲得済み称号を確認。サーバーごとに1つ装着・解除。'),
    ('/収集率', '作品のカードコレクションを確認。'),
    ('/ガチャ確率', 'ガチャの排出率を確認。'),
    ('/ヘルプ', 'この案内を表示。'),
]
DM_COMMANDS = [
    ('@ジョージ ヘルプ', 'この案内を表示するぜ。'),
    ('@ジョージ ロザリーのことどう思う？', 'メンションや返信で会話できるぜ。'),
]


PUBLIC_COMMANDS = frozenset(('プログレス', 'おみくじ', 'ガチャ'))
PRIVATE_NOTICE = '（あなただけに表示されます）'


def annotate_private_commands(tree):
    for command in tree.walk_commands():
        if command.qualified_name.split()[0] not in PUBLIC_COMMANDS and not command.description.endswith(PRIVATE_NOTICE):
            command.description = command.description[:100 - len(PRIVATE_NOTICE)] + PRIVATE_NOTICE


def format_commands(entries):
    return '\n\n'.join('`' + command + '`' + ('\n' + explanation if explanation else '') for command, explanation in entries)


def command_help(in_guild, introduction=None):
    embed = discord.Embed(color=0xE2AD48)
    intro = introduction or 'よう、みんな！ 楽しそうな雑談には俺もたまに混ざるし、俺が絵文字でリアクションすることもあるぜ！'
    embed.add_field(name='【ジョージの機能一覧】', value=discord.utils.escape_markdown(intro)[:400] + '\n\u200b', inline=False)
    entries = [(command, explanation + ('' if command.split()[0][1:] in PUBLIC_COMMANDS else PRIVATE_NOTICE))
               for command, explanation in SLASH_COMMANDS]
    embed.add_field(name='【スラッシュコマンド一覧】', value=format_commands(entries) + '\n\u200b', inline=False)
    embed.add_field(name='【メンション一覧】', value=format_commands(DM_COMMANDS), inline=False)
    return embed
