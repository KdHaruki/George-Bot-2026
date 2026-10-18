import discord

SLASH_COMMANDS = [
    ('/プログレス ロザリー', '名前でプロフィールを検索。世界名でも探せるぞ。'),
    ('/おみくじ', '今日の運勢とラッキーアイテム。'),
    ('/ガチャ アンジュ・ヴィエルジュ', '7連ガチャ。'),
    ('/ガチャ アンジュ・リリンク', '10連ガチャ。'),
    ('/所持カード ロザリー', 'プログレスの所持カードと枚数を確認。'),
    ('/お気に入り ロザリー', 'お気に入りを登録。再指定すると解除。'),
    ('/収集率', '両作品のコレクションの完成度をまとめて確認。'),
    ('/ガチャ確率', '排出率と保証を確認。'),
    ('/ヘルプ', 'この案内を表示。'),
]
DM_COMMANDS = [
    ('@ジョージ ヘルプ', 'この案内を表示。サーバーでは全員に見えるぞ。DMでも「ヘルプ」で確認できる。'),
    ('@ジョージ ロザリーのことどう思う？', 'メンションや俺への返信で会話。DMならそのまま話しかけてくれ。'),
    ('@ジョージ 画像添付', '画像を参照。PNG・JPEG・WebPの最大2枚、各4MiBまで。'),
    ('@ジョージ リセット', 'この場所のオマエとの短期会話履歴を消す。'),
]


def format_commands(entries):
    return '\n\n'.join('`' + command + '`' + ('\n' + explanation if explanation else '') for command, explanation in entries)


def command_help(in_guild):
    embed = discord.Embed(color=0xE2AD48)
    embed.add_field(name='【ジョージの機能一覧】', value='よう！ みんな、いい調子か？ 楽しそうな話なら俺も混ぜてくれよな！\n\u200b', inline=False)
    embed.add_field(name='【スラッシュコマンド】', value=format_commands(SLASH_COMMANDS) + '\n\u200b', inline=False)
    embed.add_field(name='【メンション】', value=format_commands(DM_COMMANDS), inline=False)
    return embed
