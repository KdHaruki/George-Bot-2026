#################################################
# メッセージ
#################################################

def response(num):
    messages = {
        2: "",
        3: "かわいこちゃんが見つからなかったぜ！",
        4: "かわいこちゃんが多すぎるぜ！",
        5: "かわいこちゃんが複数人見つかったぜ！",
        6: "かわいこちゃんだぜ！"
    }
    return messages.get(num, "")

#################################################
# データ
#################################################

progressData = [
    {"progressName":"東条遥","progressNickname1":"パンチ","progressNickname2":"","progressNickname3":"とうじょうはるか","progressWorld":"青","progressLike":"ご飯、パン、牛乳","progressDisLike":"ナメクジ、くせっ毛","progressInscription":"友情、努力、勝利！！","progressDetail1":"明るくて活発な青の世界の地球人！意志の強さは人1倍！憧れた姉が所属していた風紀委員に自身も入ろうと大奮闘！他人を巻き込んでしまう性格をちょっと気にしているけど、そんな彼女が皆大好き！","progressDetail2":"青蘭学園を救った風紀委員副委員長！５つの世界を巡り、更なるパワーアップを遂げた遥に死角はない…！？","progressDetail3":"","progressEx":"",},
]

#################################################
# 検索
#################################################

def progressSearch(text):

    result = ""

    exact = []
    nickname = []
    name_partial = []
    other = []

    for p in progressData:

        # 名前完全一致
        if text == p["progressName"]:
            exact.append(p)

        # ニックネーム完全一致
        elif text == p["progressNickname1"] or text == p["progressNickname2"] or text == p["progressNickname3"]:
            nickname.append(p)

        # 名前部分一致
        elif text in p["progressName"]:
            name_partial.append(p)

        # その他検索
        elif (
            text in p["progressWorld"] or
            text in p["progressLike"] or
            text in p["progressDisLike"] or
            text in p["progressInscription"] or
            text in p["progressDetail1"] or
            text in p["progressDetail2"] or
            text in p["progressDetail3"] or
            text in p["progressEx"]
        ):
            other.append(p)

    # 優先順位
    if exact:
        found = exact
    elif nickname:
        found = nickname
    elif name_partial:
        found = name_partial
    else:
        found = other

    if len(found) == 0:
        return response(3)

    elif len(found) == 1:

        p = found[0]

        result += f"【名前】{p['progressName']}\n"

        if p["progressWorld"]:
            result += f"【世界】{p['progressWorld']}\n"

        if p["progressLike"]:
            result += f"【好きなもの】{p['progressLike']}\n"

        if p["progressDisLike"]:
            result += f"【嫌いなもの】{p['progressDisLike']}\n"

        if p["progressInscription"]:
            result += f"【座右の名】{p['progressInscription']}\n"

        if p["progressDetail1"]:
            result += f"【情報】{p['progressDetail1']}\n"

        if p["progressDetail2"]:
            result += f"【情報】{p['progressDetail2']}\n"

        if p["progressDetail3"]:
            result += f"【情報】{p['progressDetail3']}\n"

        if p["progressEx"]:
            result += f"【EX】{p['progressEx']}\n"

        return result

    else:

        if len(found) > 10:
            return response(4)

        result = response(5) + "\n\n"

        for p in found:
            result += p["progressName"] + "\n"

        return result

#################################################
# 世界別一覧
#################################################

def progressSearchAll(type):

    blue = []
    black = []
    red = []
    white = []
    green = []

    for p in progressData:

        if p["progressWorld"] == "青":
            blue.append(p["progressName"])

        if p["progressWorld"] == "黒":
            black.append(p["progressName"])

        if p["progressWorld"] == "赤":
            red.append(p["progressName"])

        if p["progressWorld"] == "白":
            white.append(p["progressName"])

        if p["progressWorld"] == "緑":
            green.append(p["progressName"])

    result = response(6)

    def make(world, data):
        text = f"\n\n【{world}の世界】\n"
        for n in data:
            text += "・" + n + "\n"
        return text

    if type == 0:
        result += make("青", blue)

    elif type == 1:
        result += make("黒", black)

    elif type == 2:
        result += make("赤", red)

    elif type == 3:
        result += make("白", white)

    elif type == 4:
        result += make("緑", green)

    elif type == 5:
        result += make("青", blue)
        result += make("黒", black)
        result += make("赤", red)
        result += make("白", white)
        result += make("緑", green)

    return result