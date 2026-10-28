import discord

SLASH_COMMANDS = [
    ('/ガチャ アンジュ・ヴィエルジュ', '7連ガチャ。'),
    ('/ガチャ アンジュ・リリンク', '10連ガチャ。'),
    ('/おみくじ', '今日の運勢占い。1日1回アイテムをプレゼント！\nお気に入りに登録したプログレスがラッキーに選ばれると、応援ボーナスでさらにもう1個！（1日1回）'),
    ('/ガチャ確率', 'ガチャの排出率を確認。'),
    ('/クイズ', '4択クイズ。正解で1日1回アイテムをプレゼント！'),
    ('/所持カード ロザリー', 'プログレスの所持カードと枚数を確認。'),
    ('/プログレス ロザリー', '名前でプロフィールを検索。世界名でも探せるぜ。'),
    ('/お気に入り プログレス登録 ロザリー カード', 'レアリティ・衣装を選んで登録。同じカードの再指定で解除。'),
    ('/お気に入り プログレス確認', 'お気に入り・好感度・アルバムを確認。'),
    ('/お気に入り プレゼント', '所持アイテムを贈って好感度アップ。'),
    ('/称号', '獲得済み称号を確認。サーバーごとに1つ装着・解除。'),
    ('/ヘルプ', 'この案内を表示するぜ。'),
]
DM_COMMANDS = [
    ('@ジョージ ヘルプ', 'この案内を表示するぜ。'),
    ('@ジョージ ロザリーのことどう思う？', 'メンションや返信で会話できるぜ。'),
]


PUBLIC_COMMANDS = frozenset(('おみくじ', 'ガチャ'))
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
    public = [entry for entry in SLASH_COMMANDS if entry[0].split()[0][1:] in PUBLIC_COMMANDS]
    private = [entry for entry in SLASH_COMMANDS if entry[0].split()[0][1:] not in PUBLIC_COMMANDS]
    embed.add_field(name='【スラッシュコマンド一覧】', value=format_commands(public) + '\n\u200b', inline=False)
    embed.add_field(name='【スラッシュコマンド一覧（あなただけに表示されます）】', value=format_commands(private) + '\n\u200b', inline=False)
    embed.add_field(name='【メンション一覧】', value=format_commands(DM_COMMANDS), inline=False)
    return embed
