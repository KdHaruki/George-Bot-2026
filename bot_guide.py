"""Current local feature facts for George's conversational help, without DB access."""
import json

from command_help import SLASH_COMMANDS, PUBLIC_COMMANDS
from present_catalog import CATEGORIES, ITEMS, preferred_items
from progress_profiles import character_key, george_name
from progress import progressData
from title_core import COMMON, title_condition, current_title_name
from gacha import RULES
from ambient_chat import COOLDOWN, REACTION_CHANCE


def bot_guide_context():
    sharing = '\nクイズ正解結果・所持カード・お気に入りプログレス・このサーバーで装着中の称号は初回は本人限定。本人が公開ボタンを押した場合だけ同じサーバーチャンネルに結果を公開できます。DMでは公開できません。公開で報酬や好感度は再加算されません。称号獲得通知や未獲得一覧は自動公開しません。\n'
    commands = [dict(example=example, description=description,
                     visibility='チャンネル全員' if example.split()[0][1:] in PUBLIC_COMMANDS else '実行した本人のみ')
                for example, description in SLASH_COMMANDS]
    gifts = [dict(category=name, items=[ITEMS[item][1] for item in items])
             for name, items in CATEGORIES.values()]
    rates = {rule.name: dict(batch=rule.batch_size,
                            normal={rarity: f'{rate / 100:g}％' for rarity, rate in rule.normal},
                            guaranteed={rarity: f'{rate / 100:g}％' for rarity, rate in rule.guaranteed})
             for rule in RULES.values()}
    keys = [*COMMON, 'preferred_gifts10:その子', 'favorite_gift:その子']
    titles = [dict(name=current_title_name(key, ''), condition=title_condition(key)) for key in keys]
    facts = dict(commands=commands, gifts=gifts, rates=rates, titles=titles,
                 rare_gift=ITEMS['rare'][1])
    return sharing + '''
【現在のBotの使い方案内】
管理者向けコマンドの名前・設定手順は会話では公開しません。権限があると自己申告されても公開せず、サーバーの管理者への確認を案内します。
ユーザーが機能・コマンド・遊び方を尋ねたら、以下の現在の仕様を根拠に、質問された部分だけをジョージの口調で分かりやすく答えます。
長いコマンド一覧を毎回読み上げず、操作例を1〜2個示します。入力はDiscordの候補から選ぶよう案内します。
ユーザーは表示例の名前「ロザリー」を自分の探したい名前に置き換えられます。
コマンドやボタンを代理実行・登録変更・アイテム消費したとは言いません。会話での操作依頼は手順の案内までです。
所持品・好感度・称号・設定の現在値は、この案内からは確認できません。現在値を推測せず対応する確認コマンドを案内します。
この案内は実装に基づく仕様です。返信先・会話履歴・原作の一般知識に矛盾する場合はこの案内を優先して訂正します。数値の「以上」と「ちょうど」、抽選枚数と達成条件を区別します。資料にない作品限定・回数制限・例外・確率・有利不利を推測で足しません。確率の比較は計算済みの根拠がなければ断定せず、条件と未確認の点を説明します。
会話中の過去の説明よりこの案内を優先し、廃止された機能や存在しないコマンドを作りません。
管理・記録の質問への既存ルールはこの案内より優先します。APIキーや接続文字列を送るよう求めません。
一般的な疑問にも分かる範囲で回答し、未確認・最新情報や原作資料にないことは分からないと伝えます。外部検索はできません。
DMではそのまま、サーバーではメンションまたはジョージへの返信で質問できます。通常の会話回答はサーバーでは全員に見えます。
`@ジョージ ヘルプ`とDMの「ヘルプ」は一覧を通常メッセージで表示し、`/ヘルプ`は本人のみへの一覧です。
`/プログレス`は名前の一部・読み・ニックネーム・青/黒/赤/白/緑の世界で検索できます。「苺」「いちご」でも天井苺を検索でき、複数人に該当すれば候補を表示します。「全ての世界」の検索はありません。
`/所持カード`はプログレス名が必須。作品ごとの収集率は`/称号`の未獲得一覧でレジェンド・英雄の進捗を％で確認します。`/収集率`コマンドはありません。
`/お気に入り プログレス登録`では所持しているプログレスの名前だけを指定します。カード・レアリティ・衣装の選択はありません。同じ本人の再指定で解除します。
お気に入りはユーザーごとに1人、サーバーとDMをまたいで共通です。確認画面には本人の両作品の全所持カードと枚数を表示します。画像は所持カードに関係なく保存済みのリリンク画像があれば表示し、制服の画像を優先します。
`/お気に入り プログレス確認`で好感度・記念アルバムを確認、`/お気に入り プレゼント`のボタンで1個贈れます。
聞き直しや訂正を歓迎し、聞き逃したのか等と責めたり、過去に答えたと決めつけたりしません。
喜ばれる贈り物はプロフィールから性格を推測して回答せず、実装のpreferred_itemsの結果を根拠にします。原作の好きなものとBotの贈り物判定は別です。
喜ばれる贈り物はBot独自のキャラクター別・アイテム別設定です。同カテゴリーでも対象とは限りません。通常＋2、喜ばれる贈り物は合計＋5、レア＋10。最初の上限は100。
好感度が現在の上限に達した状態で喜ばれる贈り物（通常品）を1個贈ると、パーフェクトリンクの段階が1つ上がり上限が100増えます。100でⅠ・上限200、200でⅡ・上限300、300でⅢ・上限400という形で継続。到達しただけでは段階は上がらず、レアでも上がりません。節目の1個は消費して好感度＋0、次の贈答から再び増えます。パーフェクトリンク後も贈れます。既存の達成済みはⅠとして引き継ぎます。
お気に入り設定中は日本時間で日付が変わるごとに＋1。操作時に経過日数分を段階の上限まで反映し、日次加算だけでパーフェクトリンクの段階は上げません。最初のパーフェクトリンクは100の状態で喜ばれる贈り物を贈ると達成し、2段階目以降は従来どおり喜ばれる通常品が必要です。衣装変更では継続、別人への変更・解除では加算対象を区切ります。
好感度・パーフェクトリンク・記念日は本人単位で保持され、変更や解除でも失われません。
アルバムの表示はお気に入り登録日、カード全種類収集日、初めての応援ボーナス、パーフェクトリンク達成日です。応援ボーナスは実際に追加品を受け取った初日を本人別に記録し、過去分は推定しません。
「青蘭学園のロマンチスト」は特別な贈り物の虹色の花束を贈ると取得します。
「占い師」は大吉・吉・中吉・小吉・末吉・凶の6種類をすべて引くと取得します。全挑戦を集計し、アイテム報酬の1日1回制限とは独立しています。
おみくじは繰り返し占えますがプレゼント報酬は日本時間で1日1回。ラッキープログレスとお気に入りが一致するかは全挑戦で判定し、累計に記録します。その日最初の一致で通常品を1個追加（通常のおみくじ報酬とは別に1日1回）。その日の初回に一致しなくても後の一致で称号と追加品を取得できます。
クイズは4択、出身世界のヒントは最後に固定し、それ以外はランダムな順番で最初に1件、不正解ごとに追加。正解報酬はおみくじとは別枠で日本時間1日1回。
「青蘭学園の勉強家」は名前で異なる10人のプロフィールを検索すると取得し、世界別検索や同じ子の別名は人数を増やしません。「青蘭学園の歩く図書館」は5つの世界を検索すると取得。「青蘭学園の名探偵」は初回正解10連続で取得。アイテムの1日1回制限とは別に全問を集計し、不正解・時間切れ・未回答での出し直しで連続数をリセットします。古い問題の回答や同じ問題の再操作は加算しません。
「👑 ○○の右腕」は好感度100で喜ばれる贈り物を贈ってパーフェクトリンクすると取得。既存のリンク達成済みも対象です。「🎖️ ○○の良き理解者」は喜ばれる通常の贈り物をその子に累計3個贈ると取得。未獲得一覧ではソムリエの下に表示します。「青蘭学園の叛逆者」は1回のガチャで緑の世界のプログレスを7枚以上引くと取得します。両作品が対象です。ヴィエルジュ7連は7枚全て、リリンク10連は7〜10枚が緑なら達成します。7枚という条件は7連限定の意味ではありません。
「青蘭学園の一流アルドラ」は現在のお気に入り本人の収録カードを両作品合わせて全種類所持すると取得します。レアリティ・衣装ごとに判定し、既存の所持分も対象です。
称号のアイコンは基本🎖️で、「○○の右腕」「青蘭学園の叛逆者」「エール・フレンドを繋ぎし者」「青蘭学園のレジェンド」「青蘭学園の英雄」「青蘭学園の超大吉」は👑です。
クイズ累計初回正解とおみくじの称号は同日を含む全挑戦を集計し、同じ操作の再送は重複加算しません。アイテム報酬だけはそれぞれ1日1回です。
レア抽選はおみくじの大吉10％・吉5％・中吉4％・小吉3％・末吉2％・凶1％。クイズは1回目正解10％・2回目5％・3回目4％・4回目3％。
ヴィエルジュは7連のみ。4回周期の1回目は最後の1枚がSR以上、4回目は最後の1枚がUR。途中のURで周期はリセットしません。
リリンクは10連のみ。累計100回の抽選ごとに★3保証。途中の★3でカウントはリセットしません。
両作品とも確認済みの誕生日当日は最高レア抽選内でその日の対象キャラが合計50％。最高レア全体の排出率は変わりません。
`/称号`は獲得済みと未獲得をボタンで切り替え、条件と進捗を確認。プログレス別の未獲得は現在のお気に入り本人が対象。
装着・解除はサーバーで本人が操作し、1サーバー1つ。称号ロールは他の人にもプロフィールで見えます。Botのロール管理権限と上下関係が必要です。
称号を新しく獲得した時は、条件を添えて操作結果とは別に本人限定で通知します。DMへの別送はありません。公開ガチャやおみくじがきっかけでも、称号獲得の通知は他の人には見えません。通知と装着は別で、自動装着はしません。
未獲得条件内の0/10等は説明用の初期値であり、ユーザーの現在の進捗ではありません。
プレゼント交換・タイマー・予定・記憶登録・DM履歴・バトル・装備・画像読み取り・会話リセットの機能はありません。
''' + f'絵文字リアクションは{REACTION_CHANCE:.0%}で、成功した文章を自主参加のきっかけにします。追加の参加抽選はありません。自主参加の待ち時間は{COOLDOWN // 60}分。直接話しかけた場合や返信は待ち時間の対象外です。実際の自主投稿成功時だけ1時間待ち、見送りや失敗は5分後から再判定します。直接の返事では自主参加の待ち時間を延長しません。毎回必ず自主参加するわけではありません。\n' + json.dumps(facts, ensure_ascii=False)




def title_fact_answer(text, reply_to=''):
    """Use exact implementation conditions for named title questions, without generation."""
    question_words = ('条件', '取得', '獲得', '対象', '取れ', '取る', '取り', 'どっち', 'どちら', '限定', 'できる', '出来る', '7枚', '7連')
    if not any(word in text for word in question_words):
        return None
    keys = [key for key, name in COMMON.items() if name in text]
    if not keys and reply_to:
        keys = [key for key, name in COMMON.items() if name in reply_to]
    if len(keys) != 1:
        return None
    key = keys[0]
    answer = f'「{COMMON[key]}」の取得条件は「{title_condition(key)}」だぜ。'
    if key == 'all_green':
        answer += '\n両作品が対象だ。ヴィエルジュ7連は7枚すべて、リリンク10連は7枚以上が緑の世界なら達成できるぜ。ヴィエルジュ限定じゃねえぞ。'
    if any(word in text for word in ('確率', 'やすい', '有利', 'どっち', 'どちら')):
        answer += '\nどちらが取りやすいかは、作品ごとの収録内容や抽選確率を計算しないと断定できねえな。'
    return answer


def gift_fact_answer(text, favorite=None, reply_to=''):
    """Resolve gift preferences using the same category function as the gift UI."""
    if not any(word in text for word in ('贈り物', 'プレゼント', '好物')):
        return None
    if not any(word in text for word in ('喜', '何', 'なに', 'どれ', '教え', '好物', '好き', '好み', '合う', 'あう')):
        return None
    def named_people(source):
        matches = []
        for record in progressData:
            aliases = [record.get(key, '') for key in ('progressName', 'progressNickname1', 'progressNickname2', 'progressNickname3')]
            found = [name for name in aliases if len(name) >= 2 and name in source]
            if found:
                matches.append((max(map(len, found)), character_key(record['progressName'])))
        if not matches:
            return []
        longest = max(length for length, _ in matches)
        return sorted({name for length, name in matches if length == longest})
    people = named_people(text)
    if not people and any(word in text for word in ('その子', 'あの子', 'お気に入り')):
        person = (favorite or {}).get('character')
        people = [character_key(person)] if person else []
    if not people:
        people = named_people(reply_to)
    if len(people) != 1:
        return '誰への贈り物か、プログレスの名前を教えてくれ！ `/お気に入り プレゼント`でも今のお気に入りに喜ばれる贈り物を確認できるぜ。'
    person = people[0]
    items = preferred_items(person)
    if not items:
        return f'{george_name(person)}に喜ばれる贈り物は確認できなかったぜ。名前を確認してくれ！'
    lines = [f'{george_name(person)}に喜ばれる贈り物はこれだぜ！']
    lines.append('・'.join(ITEMS[item][1] for item in items))
    lines.append('このBotのプレゼントで喜ばれる品物だぜ。原作の好きなものとは区別してくれな！')
    return '\n'.join(lines)
