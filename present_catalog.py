"""Bot gift categories. Stable item IDs retain inventories and title progress."""
from progress_profiles import profile_for


CATEGORIES = {
    'food': ('食べ物・飲み物', ('sweets', 'food')),
    'fashion': ('ファッション・美容', ('fashion', 'mirror')),
    'knowledge': ('本・知識', ('book', 'pen')),
    'play': ('遊び・芸術', ('game', 'music')),
    'adventure': ('運動・冒険', ('towel', 'charm')),
    'craft': ('魔法・機械', ('magic', 'tools')),
    'comfort': ('花・癒やし', ('plant', 'aroma')),
}
ITEMS = {
    'sweets': ('🍪', 'チョコクッキー'), 'food': ('☕', '紅茶'),
    'fashion': ('🎀', 'リボン'), 'mirror': ('🪞', '手鏡'),
    'book': ('📖', '本'), 'pen': ('🖋️', '万年筆'),
    'game': ('🧸', 'ぬいぐるみ'), 'music': ('🎵', 'オルゴール'),
    'towel': ('🧺', 'タオル'), 'charm': ('🧿', 'お守り'),
    'magic': ('📕', '魔道書'), 'tools': ('🧰', '工具セット'),
    'plant': ('🪴', '鉢植え'), 'aroma': ('🕯️', 'アロマセット'),
    'rare': ('💐', '花束（虹）'),
}
NORMAL_ITEMS = tuple(key for key in ITEMS if key != 'rare')
ITEM_CATEGORY = {item: category for category, (_, items) in CATEGORIES.items() for item in items}

# These are Bot-specific interpretations, not a claim about canonical gift preferences.
CATEGORY_WORDS = {
    'food': ('ご飯', 'パン', '牛乳', '食', '料理', 'お菓子', '甘', 'クレープ', 'チョコ', 'ケーキ', '羊羹', 'ようかん', '果物', 'いちご', 'イチゴ', 'アイス', 'カレー', '紅茶', '茶', 'コーラ', 'ジュース', '飲料', 'プリン', 'メロン', 'オレンジ', 'りんご', '林檎', 'みかん', 'せんべい', 'マカロン', 'マコロン', '砂糖', '焼き芋', '黒飴', 'スコーン', 'パイ', 'ラーメン', 'もやし', 'ぶどう', '桃', '柿', '豆腐', '湯葉', 'ぎんつば', '氷砂糖', 'おにぎり', 'はんばーぐ', 'ハンバーグ'),
    'fashion': ('服', 'おしゃれ', 'オシャレ', 'お洒落', 'おしゃれ', '買い物', 'ショッピング', '小物', 'アクセサリー', '眼鏡', '鏡', '自分磨き'),
    'knowledge': ('読書', '本', '学問', '真理', '図書', '研究', '勉強', '推理', '情報', '解析', '数式', '英語', '探求', '探究', '知識'),
    'play': ('ゲーム', 'ネトゲ', 'バーチャル', 'コンボ', '人形', 'ぬいぐるみ', '動物', '猫', 'ねこ', 'ぱんだ', '恐竜', '鳥', '犬', '獣', 'リス', '熊', 'ペンギン', 'ライオン', 'ハヤブサ', 'チーター', '音楽', '歌', '絵', '芸術', '舞踊', '踊', 'ハープ', 'オルゴール', '落語', 'ポエム', 'いたずら', 'イタズラ', 'からか', '驚', '遊び', 'カジノ', 'ロック'),
    'adventure': ('走る', '弓道', '鍛錬', '訓練', '運動', '空手', 'カラテ', '剣', '戦闘', '戦い', 'バトル', '観戦', 'サッカー', 'トレーニング', '狩り', '冒険', 'プロテイン', '軍'),
    'craft': ('魔法', '魔石', '鉱石', '錬金術', '手品', '幽霊', '占い', 'スパナ', 'ロボ', '機械', '改良', '電波', '粒子', '爆発', 'ビリビリ', '魔道'),
    'comfort': ('花', '植物', '自然', '草木', 'クローバー', '百合', '薔薇', '森林', '野草', '風呂', '昼寝', '睡眠', '休暇', 'こたつ', '平穏', '平和', '静か', '安らぎ', '潮風'),
}


def preferred_categories(character):
    record = profile_for(character)
    if not record:
        return ()
    def matches(text):
        return tuple(category for category, words in CATEGORY_WORDS.items() if any(word in text for word in words))[:2]
    liked = matches(record.get('progressLike', ''))
    if liked:
        return liked
    # Infer a suitable gift from personality, excluding the explicit dislikes field.
    details = ' '.join(record.get(key, '') for key in ('progressDetail1', 'progressDetail2', 'progressDetail3'))
    return matches(details) or ('comfort',)


def preferred_items(character):
    return tuple(item for category in preferred_categories(character) for item in CATEGORIES[category][1])
