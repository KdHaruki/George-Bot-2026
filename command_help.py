import discord


def command_help(in_guild):
    embed = discord.Embed(title="ジョージのコマンド案内", color=0xE2AD48,
                          description="サーバーではメンションか俺の発言への返信、DMではそのまま話しかけてくれ！\n「リセット」で、その場所のキミとの短期会話履歴を消せるぜ。")
    embed.add_field(name="どちらでも使える", inline=False, value=(
        "`/ヘルプ`：この案内\n"
        "`/状態`：Gemini・DB・予定通知の健康診断（API利用枠を消費、確認は5分間再利用）\n"
        "`/progress name:ロザリー`：プログレス検索。世界名でも検索できるぞ\n"
        "`/おみくじ`：運勢＋AIの一言とラッキーアイテム\n"
        "`/タイマー 時間:10分 内容:休憩`：1秒〜24時間のタイマー\n"
        "`/タイマー取消`：この場所の自分のタイマーを全件解除"))
    embed.add_field(name="サーバー専用：予定", inline=False, value=(
        "`/予定 日時:明日21時 内容:ゲーム集合`：日本時間で登録\n"
        "`/予定一覧`：このサーバーの自分の予定を確認\n"
        "`/予定取消 id:123`：自分の予定をIDで取消\n"
        "通知は登録したチャンネルへ。通常は約1分以内、停止中に過ぎた予定は復帰後に通知するぜ。"))
    embed.add_field(name="サーバー専用：共有記憶", inline=False, value=(
        "`/記憶登録 タイトル:呼び方 内容:春樹と呼ぶ`：登録・同名更新【サーバー管理権限が必要】\n"
        "`/記憶一覧`：共有設定を確認【全員利用可】\n"
        "`/記憶削除 タイトル:呼び方`：削除【サーバー管理権限が必要】\n"
        "最大20件・内容300文字。そのサーバー内で共有し、DMや別サーバーには持ち込まないぞ。"))
    embed.add_field(name="保存と利用条件", inline=False, value=(
        "短期会話履歴とタイマーは再起動で消えるぜ。\n"
        "共有記憶と予定は管理者が `DATABASE_URL` を設定すればDBに保存するぞ。\n"
        "会話・AIおみくじはGeminiの利用枠を消費するぜ。ウェブ検索は未対応だ。"))
    embed.add_field(name="画像も見られるぜ", inline=False, value=(
        "画像と `@ジョージ この画像に一言` を送ってくれ。DMではメンションなしでOK。\n"
        "PNG・JPEG・WebP、最大2枚・各4MiB。雑談参加時も直近の画像を参照するぞ。\n"
        "画像はGoogleへ送信するぜ。画像本体は記憶しないから、再確認したい画像は再添付してくれ。"))
    if not in_guild:
        embed.add_field(name="今はDMだぜ！", value="予定・記憶コマンドはDMには出ないぞ。使いたいサーバーのチャンネルで実行してくれ。", inline=False)
    embed.set_footer(text="コマンド入力後、Discordの入力欄で項目を選んで指定してくれ！")
    return embed
