"""Read-only, bounded feature answers. The model selects facts, never writes them."""
import re
from conversation_access import ADMIN_TOPICS, ADMIN_REPLY, mentions_admin_details

from command_help import SLASH_COMMANDS
from bot_guide import gift_fact_answer, title_fact_answer
from title_core import COMMON, title_condition
from present_catalog import ITEMS
from progress_profiles import character_key, profile_for, NAME_ALIASES, george_name
from progress import progressData
from gacha import RULES, BATCH_GUARANTEE, VIERGE_CHARACTERS
from ambient_chat import COOLDOWN, RETRY_DELAY, REACTION_CHANCE


CLARIFY = 'その点は今ある仕様だけでは確認できねえな。どの機能の何を知りたいか、もう少し具体的に教えてくれ！ `/ヘルプ`でも使い方を確認できるぜ。'
ALIASES = {
    'gifts': ('贈り物', 'プレゼント', '好物', '何あげ', '何をあげ', '何渡', '何を渡', '喜ぶもの'),
    'affection': ('好感度', '毎日', '日次'),
    'link': ('パーフェクトリンク', 'リンクの段階', '上限'),
    'album': ('アルバム', '記念日', '初登録日'),
    'favorite': ('お気に入り', '衣装変更', '水着', '制服'),
    'fortune': ('おみくじ', '応援ボーナス', 'ラッキープログレス'),
    'quiz': ('クイズ', 'ヒント'),
    'rates': ('排出率', 'ガチャ確率', '誕生日ピックアップ'),
    'gacha': ('ガチャ', '7連', '10連', '天井', '保証'),
    'collection': ('所持カード', '収集率', 'コレクション'),
    'profile': ('プロフィール', '/プログレス', '世界別検索'),
    'titles': ('称号', 'ロール'),
    'seasonal': ('季節通知', '祝日', '季節の通知'),
    'health': ('/状態', '健康診断'),
    'conversation': ('会話に', '口を挟', 'リアクション', 'メンション', '自動発言', '返信してくれる'),
    'visibility': ('公開ボタン', '結果を公開', '公開でき', '非公開', '公開情報', '誰に見', '全員に見', '自分だけ', '本人だけ', 'みんなに見'),
    'removed': ('タイマー', 'リマインダー', 'DM履歴', 'エクシーズ', '装備', '記憶登録', 'リセット機能', 'プレゼント交換'),
    'help': ('ヘルプ', 'コマンド一覧', '何ができ', '何が出来', '使える機能'),
}


def catalog():
    """Values here are answers, not open-ended model instructions or user data."""
    rates = []
    for game, rule in RULES.items():
        normal = '・'.join(f'{rarity} {rate / 100:g}％' for rarity, rate in rule.normal)
        last = '・'.join(f'{rarity} {rate / 100:g}％' for rarity, rate in rule.guaranteed if rate)
        rates.append(f'【{rule.name}】通常枠：{normal}。最後の枠：{last}。')
    share_note = ' クイズの正解結果・所持カードの全ページ・お気に入りプログレスの好感度やアルバムと画像・このサーバーで装着中の称号は、本人が公開ボタンを押した時だけ同じサーバーチャンネルに公開できるぜ。DMでは公開不可、同じ画面からは1回限りで約3分間だ。公開しても報酬などは再付与しないぞ。'
    return {
        'gifts': '贈り物は `/お気に入り プレゼント` のボタンで1個ずつ贈れるぜ。通常は好感度＋2、喜ばれる通常品は＋5、虹色の花束は＋10だ。おみくじとクイズでそれぞれ日本時間1日1回もらえるぞ。誰に何を贈るか教えてくれれば、喜ばれる品物も確認するぜ。',
        'affection': '好感度は `/お気に入り プログレス確認` で見られるぜ。お気に入り設定中は日本時間の日付が変わるごとに＋1、操作時に経過分を反映する。現在の上限までで、日次加算だけではパーフェクトリンクにならねえぞ。本人ごとに全サーバー・DM共通で保持し、変更・解除でも消えないぜ。',
        'link': '好感度が現在の上限に達した状態で、喜ばれる通常の贈り物を改めて1個贈るとパーフェクトリンクの段階が上がるぜ。最初は100でⅠになり上限200、次は200でⅡ・上限300。その繰り返しで段階の上限は設けていない。節目の品物は消費するが好感度＋0だ。虹色の花束や日次加算だけでは段階は上がらないぜ。',
        'album': 'アルバムは `/お気に入り プログレス確認` で見られるぜ。お気に入り登録日・カード全種類収集・初めての応援ボーナス・パーフェクトリンク達成の4項目だ。本人別の初回記録で、変更・解除でも残る。過去の未記録日は推定しないぞ。',
        'favorite': 'お気に入りはユーザーごとに1人、全サーバー・DM共通だ。`/お気に入り プログレス登録` で所持しているプログレス名だけを指定する。同じ本人の再指定で解除だ。カード・レアリティ・衣装は選ばない。画像は所持カードに関係なく保存済みのリリンク画像があれば表示し、制服を優先する。本人の両作品の全所持カードと枚数も表示するぞ。好感度やアルバムは変更・解除でも本人別に残るぜ。確認は `/お気に入り プログレス確認` だ。' + share_note,
        'fortune': 'おみくじは何度でも挑戦できるぜ。大吉・吉・中吉・小吉・末吉・凶の6種類を均等抽選する。通常の贈り物は日本時間1日1個。お気に入りがラッキープログレスに選ばれたら、その日最初の一致で通常品をもう1個もらえる。応援ボーナスは初回の占いに限らず全挑戦で判定するぜ。',
        'quiz': 'クイズは `/クイズ` の4択で、本人だけに表示するぜ。出身世界のヒントは最後に固定し、それ以外はランダム順に出して不正解ごとに追加する。回答時間は3分、間違えた選択肢は再選択できない。何度でも挑戦でき、称号は全挑戦が対象。正解の贈り物はおみくじと別枠で日本時間1日1個だ。' + share_note,
        'rates': '\n'.join(rates) + '\n誕生日当日は確認済みの対象本人が最高レア抽選内で合計50％になる。最高レア自体の確率は変わらず、保証にも適用する。複数の誕生日なら対象内で均等だ。詳しくは `/ガチャ確率` を確認してくれ。',
        'gacha': f'ヴィエルジュは{RULES["vierge"].batch_size}連、リリンクは{RULES["relink"].batch_size}連のみだ。ヴィエルジュは{BATCH_GUARANTEE["vierge"]}回周期で、1回目の最後はSR以上、4回目の最後はUR確定。リリンクは累計100抽選ごとに1枚★3確定。途中で最高レアが出てもカウントはリセットしない。\nヴィエルジュはプログレス一覧の対象{len(VIERGE_CHARACTERS)}人×4レアリティでWikiカードは使わない。リリンクは保存済みのレアリティ・衣装別カードを使う。結果は保存後に表示し、レアリティ順に並ぶぜ。',
        'collection': '`/所持カード` はプログレス名を指定して、その子のカードと枚数を確認するぜ。作品ごとの収集率は `/称号` の未獲得一覧で、ヴィエルジュはレジェンド、リリンクは英雄の進捗を％で確認する。`/収集率` コマンドは廃止したぜ。重複は種類数に加えない。所持データは全サーバー・DM共通だ。ガチャ結果には収集率を表示しないぞ。' + share_note,
        'profile': '`/プログレス` に本人の名前、または青・黒・赤・白・緑の世界を指定して探すぜ。結果は本人限定だ。全ての世界を一度に出す検索はないぞ。',
        'titles': '`/称号` で獲得済み・未獲得を切り替えて条件と進捗を確認できるぜ。取得は全サーバー・DM共通、装着はサーバーごとに1つだ。本人が装着・解除でき、Botにロール管理権限と適切なロール順が必要。獲得通知は本人限定で、装着した称号ロールは他の人にも見える。取得条件は称号名を教えてくれ！' + share_note,
        'conversation': f'サーバーではメンションや俺への返信、DMではそのまま話しかけてくれ。各文章への絵文字リアクションは{REACTION_CHANCE:.0%}で、リアクション成功した文章だけを自動参加のきっかけにする。追加の参加抽選はないが、話題や会話状況で見送ることもある。自動投稿成功後は{COOLDOWN // 60}分、見送り・失敗は{RETRY_DELAY // 60}分後から再判定する。メンションや返信はこの待ち時間の対象外だ。',
        'visibility': 'サーバーの `/おみくじ` と `/ガチャ` はチャンネル全員に表示する。それ以外のスラッシュコマンドの結果と称号獲得通知は本人限定だ。メンション・俺への返信の回答と `@ジョージ ヘルプ` は通常メッセージとしてチャンネル全員に見える。装着した称号ロールも他の人に見えるぜ。' + share_note,
        'removed': 'タイマー・予定のリマインダー・記憶登録・DM履歴コマンド・エクシーズバトル・装備・プレゼント交換・会話リセット・画像読み取りは今は使えないぜ。使えるコマンドは `/ヘルプ` で確認してくれ。',
        'help': '\n'.join(f'`{example}`：{description}' for example, description in SLASH_COMMANDS),
    }


def person_in(text):
    hits = []
    for record in progressData:
        names = [record.get(key, '') for key in ('progressName', 'progressNickname1', 'progressNickname2', 'progressNickname3')]
        found = [name for name in names if len(name) >= 2 and name in text]
        if found:
            hits.append((max(map(len, found)), character_key(record['progressName'])))
    for alias, canonical in NAME_ALIASES.items():
        if re.search(re.escape(alias) + r'(?:には|への|の|は|なら|[？?])', text):
            hits.append((len(alias), canonical))
    for query in re.findall(r'([一-龥ぁ-んァ-ヶー・]{2,30})(?:への|には|の)', text):
        record = profile_for(query)
        if record:
            hits.append((len(query), character_key(record['progressName'])))
    # Remove a shorter name only when it is part of another matched name.
    people = {name for _, name in hits}
    if not people:
        query = re.sub(r'(?:には|なら|は)?[？?！!。]*$', '', text.strip())
        record = profile_for(query) if 2 <= len(query) <= 30 else None
        if record:
            people.add(character_key(record['progressName']))
    return sorted(name for name in people if not any(name != other and name in other for other in people))


def topic_for(text):
    if any(label in text for _, label in ITEMS.values()):
        return 'gifts'
    for topic in ('visibility', 'link', 'album', 'seasonal', 'removed', 'rates'):
        if any(word in text for word in ALIASES[topic]):
            return topic
    for topic, words in ALIASES.items():
        if any(word in text for word in words):
            return topic
    if any(name in text for name in COMMON.values()):
        return 'titles'
    return None


def is_question(text):
    return bool(re.search(r'[?？]|教え|どう|何|なに|どれ|どこ|いつ|でき|出来|ある|あるの|ない|方法|条件|違い|仕組み|確率|なの|だっけ|ください|くれる|知りたい|増え|上が|減る|リセット', text))


def resolve(text, favorite=None, previous_topic=None, previous_person=None, reply_to=''):
    """Return (answer, topic, person). None answer means ordinary conversation."""
    if mentions_admin_details(text):
        return ADMIN_REPLY, None, None
    facts = catalog()
    topic = topic_for(text)
    if topic is None and previous_topic == 'gifts' and any(label in text for _, label in ITEMS.values()):
        topic = 'gifts'
    people = person_in(text)
    followup = previous_topic and len(text) < 100 and (bool(people) or text.startswith(('それ', 'これ', 'じゃ', '何回', 'いつ', '一日', '1日', '毎日', '上限', 'その子', 'あの子')))
    if topic is None and followup:
        topic = previous_topic
    if topic is None and reply_to and is_question(text):
        topic = topic_for(reply_to)
    if topic in ADMIN_TOPICS:
        return ADMIN_REPLY, None, None
    if topic is None or not (is_question(text) or (people and previous_topic)):
        return None, None, None
    if topic == 'titles':
        exact = title_fact_answer(text, reply_to)
        if exact:
            return exact, topic, None
        matches = [key for key, name in COMMON.items() if name in text]
        if matches:
            return '\n'.join(f'【{COMMON[key]}】{title_condition(key)}' for key in matches), topic, None
    if len(people) > 1 and topic == 'gifts':
        return '贈り物は1人ずつ確認するぜ。誰について聞きたいか名前を教えてくれ！', topic, None
    person = people[0] if len(people) == 1 else None
    if topic == 'gifts':
        if any(word in text for word in ('もらえ', '貰え', '入手', '手に入', 'どこで', '獲得方法', '何回')):
            from presents import RARE_RATES, QUIZ_FORTUNES
            rates = '・'.join(f'{fortune}{rate}％' for fortune, rate in RARE_RATES.items())
            quiz_rates = '・'.join(f'{attempt}回目{RARE_RATES[fortune]}％' for attempt, fortune in QUIZ_FORTUNES.items())
            return facts[topic] + f'\n特別な贈り物の{ITEMS["rare"][1]}は、おみくじでは{rates}。クイズでは正解までの回答{quiz_rates}で抽選するぜ。', topic, person
        if not person and any(word in text for word in ('その子', 'あの子', 'お気に入り')):
            person = (favorite or {}).get('character')
        person = person or previous_person
        if not person:
            return facts[topic] + '\n誰への贈り物か名前を教えてくれ！', topic, None
        from presents import affection_gain
        mentioned = [key for key, (_, label) in ITEMS.items() if label in text]
        if mentioned:
            lines = [f'{george_name(person)}への贈り物だな！']
            for item in mentioned:
                lines.append(f'{ITEMS[item][1]}：好感度＋{affection_gain(person, item)}。')
            lines.append('現在の上限を超える分は増えないぜ。上限で喜ばれる通常品を贈る場合は＋0で次のパーフェクトリンクになるぞ。')
            return '\n'.join(lines), topic, person
        return gift_fact_answer(f'{person}に喜ばれる贈り物は何？'), topic, person
    # Unknown comparisons / personal state must not be guessed from a generic FAQ.
    if any(word in text for word in ('俺の', '私の', '自分の', '何個持', '残り何', '今いくつ', '取得済み')):
        return facts[topic] + '\nオマエの現在値はこの会話では確認できねえから、該当コマンドで確認してくれ！', topic, person
    if any(word in text for word in ('どっち', 'どちら', '何分の', '何％', '何%', '確率どれ', '確率は')) and topic not in ('rates', 'conversation'):
        return facts[topic] + '\nその具体的な確率や有利不利は、ここでは計算済みの根拠がないので断定できねえな。', topic, person
    return facts[topic], topic, person


def router_candidates():
    return {key: list(values) for key, values in ALIASES.items() if key not in ADMIN_TOPICS}
