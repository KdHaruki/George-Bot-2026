"""会話で管理者向け機能や非公開の管理情報を案内しないよう判定する。"""

import re

ADMIN_TOPICS = frozenset(('seasonal', 'health'))
ADMIN_REPLY = '管理者向けのコマンドや操作方法は、ここでは公開しないぜ。サーバーの管理者に確認してくれ！'


def mentions_admin_details(text):
    compact = re.sub(r'[\s`*＿_]', '', text).replace('／', '/')
    return bool(re.search(r'/状態|季節通知|健康診断|管理者(?:用|向け)?(?:の)?(?:コマンド|機能|操作)', compact))


def public_conversation_answer(text):
    return ADMIN_REPLY if mentions_admin_details(text) else text
