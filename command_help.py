import discord

HELP_CATEGORIES = {
    'overview': 'まずはここから',
    'chat': '会話・画像・キャラ検索',
    'gacha': 'ガチャ・コレクション',
}

SLASH_COMMANDS = [
    ('/プログレス ロザリー', '名前でプロフィールを検索。世界名でも探せるぞ。'),
    ('/おみくじ', '今日の運勢とラッキーアイテム。'),
    ('/ガチャ アンジュ・ヴィエルジュ', '7連ガチャ。'),
    ('/ガチャ アンジュ・リリンク', '10連ガチャ。'),
    ('/所持カード ロザリー', 'プログレスの所持カードと枚数を確認。'),
    ('/お気に入り ロザリー', 'お気に入りを登録。再指定すると解除。'),
    ('/収集率 アンジュ・ヴィエルジュ', 'コレクションの完成度を確認。'),
    ('/収集率 アンジュ・リリンク', 'コレクションの完成度を確認。'),
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


SECTIONS = {
    'chat': [
        ('会話・画像', '- **@ジョージ こんにちは**：サーバーで話しかける。俺の発言への返信でもOK。DMではそのまま話せるぞ。\n- **@ジョージ この画像に一言**：添付画像も参照。PNG・JPEG・WebPを最大2枚、各4MiB。画像はGoogleへ送信するぞ。'),
        ('プログレスを探す', '- **/プログレス ロザリー**：名前からプロフィールを検索。\n- **/プログレス 黒の世界**：世界から探す。\n- **リセット**：この場所のオマエとの短期会話履歴を消す。ウェブ検索・最新ニュースの取得は未対応だ。'),
    ],
    'gacha': [
        ('ガチャ・運試し', '- **/ガチャ アンジュ・ヴィエルジュ**：209人×4レアリティの7連。周期の1回目はSR以上、4回目はURが最後の1枚で確定。\n- **/ガチャ アンジュ・リリンク**：限定衣装も含む10連。100カウント到達ごとに★3確定、誕生日当日の★3は対象キャラ合計50％。★3の画像・原作台詞も表示。\n- **/おみくじ**：運勢とAIの一言・ラッキーアイテム。'),
        ('所持・お気に入り', '- **/所持カード ロザリー**：「プログレス」に名前を指定して確認。省略すると両作品の全所持。「前へ・次へ」で続きを表示。\n- **/お気に入り ロザリー**：所持している同名の最高レアを自動登録。同順位ならヴィエルジュを優先。同じプログレスの再指定で解除。\n- **/お気に入り**：登録中の子の紹介とジョージの一言を確認。両作品合わせて1人1枚。'),
        ('確率・保存', '- **/収集率**：種類ごとの完成度と合計所持枚数。\n- **/ガチャ確率**：レアリティの排出率と保証の詳細。\n- 保証カウント・所持数は再起動後も保存。ガチャにはDB設定が必要。初入手は **✨ NEW**。過去の結果は遡って登録しないぞ。'),
    ],
}


def command_help(in_guild, category='overview'):
    category = category if category in HELP_CATEGORIES else 'overview'
    embed = discord.Embed(title='ジョージの機能一覧' if category == 'overview' else 'ジョージのコマンド案内｜' + HELP_CATEGORIES[category], color=0xE2AD48)
    if category == 'overview':
        embed.title = None
        embed.add_field(name='【ジョージの機能一覧】', value='面白そうな話題にはリアクションしたり、口を挟むぜ！', inline=False)
        embed.add_field(name='【スラッシュコマンド】', value=format_commands(SLASH_COMMANDS), inline=False)
        embed.add_field(name='【DM・メンション】', value=format_commands(DM_COMMANDS), inline=False)
    else:
        for name, value in SECTIONS[category]:
            embed.add_field(name=name, value=value, inline=False)
    if not in_guild and category != 'overview':
        embed.add_field(name='DMで使うとき', value='ここに載せているコマンドはDMでも使えるぞ。季節通知はサーバー専用だ。', inline=False)
    return embed
