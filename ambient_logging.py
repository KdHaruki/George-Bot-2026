"""Visible ambient diagnostics without message text, credentials or DB writes."""
import logging
import copy
import re

REASONS = {
    'model_advice': 'AIが相談・助言を求める話と判断した',
    'model_serious': 'AIが真剣な話と判断した',
    'model_conflict': 'AIが対立を含む話と判断した',
    'model_directed': 'AIが特定の相手への呼びかけと判断した',
    'model_unclear': 'AIが話題や文脈をつかめないと判断した',
    'model_not_natural': 'AIが自然に参加できないと判断した',
    'model_unspecified': 'AIが参加を見送ったが理由を特定できない',
    'admin_input': '管理情報を含む会話のため',
    'admin_output': '生成した返答に管理情報が含まれたため',
    'empty_response': 'AIの返答が空だった',
    'too_long': 'AIの返答が文字数の上限を超えた',
    'multiline': 'AIの返答が複数行だった',
    'question': 'AIの返答に質問が含まれた',
    'direct_conversation': 'DM・メンション・返信の個別会話として対応',
    'no_guild': 'サーバー内のメッセージではない',
    'cooldown': '次の参加までの待ち時間中',
    'generation_busy': '別の返答を生成中',
    'serious_context': '会話に慎重に扱う話題が含まれる',
    'directed_message': '特定の相手への呼びかけ・返信がある',
    'empty_or_command': '本文が空、またはコマンド形式だった',
    'channel_capacity': '保持できるチャンネル数の上限に到達',
    'ai_unavailable': 'AIを利用できない',
    'history_unavailable': '会話履歴が参加条件を満たさない、または取得できない',
    'context_invalidated': '生成中に個別会話などで会話の状態が変わった',
    'generation_declined': '投稿できる返答が得られなかった（詳細は直前の見送り理由）',
    'exception': '処理中にエラーが発生した',
}


class AmbientFormatter(logging.Formatter):
    def format(self, record):
        # Copy so other handlers still receive the original structured codes.
        rendered = copy.copy(record)
        text = record.getMessage()
        for code, label in (('generation_skipped', '【会話への自主参加】生成後に見送り'),
                            ('reaction_added', '【リアクション】絵文字を追加'),
                            ('attempt_started', '【会話への自主参加】参加を試行'),
                            ('reply_sent', '【会話への自主参加】投稿完了'),
                            ('skip', '【会話への自主参加】見送り')):
            if text.startswith(code + ' '):
                text = label + text[len(code):]
                break
        text = re.sub(r'(?<!\S)reason=([a-z_]+)',
                      lambda match: '理由：' + REASONS.get(match[1], '未分類の理由'), text)
        text = text.replace(' channel=', ' / チャンネルID：').replace(' message=', ' / メッセージID：')
        text = text.replace(' diagnostic=', ' / エラー診断：')
        rendered.msg, rendered.args = text, ()
        return super().format(rendered)

logger = logging.getLogger('george.ambient')
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(AmbientFormatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(handler)
