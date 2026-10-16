import random



FORTUNES = [
    ("大吉", "今日はいい流れが来そうだぜ！ やりたかったことを一つ試してみな。"),
    ("中吉", "焦らずいけばいい感じだな。小さな楽しみを見つけようぜ！"),
    ("小吉", "小さなラッキーも見逃すなよ。好きなものでひと息だぜ！"),
    ("吉", "いつもの一日にも楽しみはあるぜ。気楽にいこうな！"),
    ("末吉", "楽しみは後から来るかもな。今日はじっくりいこうぜ！"),
    ("凶", "そんな日もあるぜ。これは遊びのおみくじだ、気にしすぎず休もうな！"),
]


def draw_fortune(fortune=None):
    if fortune is None:
        fortune, comment = random.choice(FORTUNES)
    else:
        comment = dict(FORTUNES)[fortune]
    return f"🎍 今日のおみくじ：**{fortune}**\n{comment}\nラッキーアイテム：{random.choice(['温かい飲み物', 'お気に入りの曲', 'ハンカチ', 'おやつ', '本', '帽子'])}"
