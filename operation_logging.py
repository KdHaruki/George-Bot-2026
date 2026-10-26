"""Readable operational events; never pass message bodies, options or exception text."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger('george.operations')
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(handler)


def event(feature, result, *, reason=None, error=None, **numbers):
    parts = [f'【{feature}】{result}']
    if reason:
        parts.append('理由：' + reason)
    if error is not None:
        code = getattr(error, 'code', None)
        api_labels = {400: 'AIへのリクエストが拒否された', 401: 'AIの認証に失敗',
                      403: 'AIの利用権限を確認', 404: 'AIのモデル・対象が見つからない',
                      429: 'AIの利用上限または回数制限に到達',
                      500: 'AI側の一時的なエラー', 503: 'AI側が一時的に利用できない'}
        labels = {'TimeoutError': '待ち時間の上限に到達',
                  'MemoryUnavailable': 'DBを利用できない',
                  'Forbidden': 'Discordの権限不足',
                  'NotFound': 'Discordの対象が見つからない',
                  'HTTPException': 'Discordとの通信に失敗',
                  'ValueError': '入力または返答内容が条件に合わない',
                  'ChatUnavailable': 'AIを利用できない'}
        if not reason:
            api_reason = api_labels.get(code) if type(code) is int and type(error).__name__ in ('ClientError', 'ServerError', 'APIError') else None
            parts.append('理由：' + (api_reason or labels.get(type(error).__name__, '処理中にエラーが発生')))
        parts.append('エラー種別：' + type(error).__name__)
    # IDs and counts only. Reject unexpected strings rather than logging private values.
    parts.extend(f'{key}：{value}' for key, value in numbers.items()
                 if isinstance(value, (int, float)) and not isinstance(value, bool))
    logger.log(logging.WARNING if error is not None else logging.INFO, ' / '.join(parts))


def command_finished(interaction, command, error=None):
    seconds = max(0, (datetime.now(timezone.utc) - interaction.created_at).total_seconds())
    # Registered names only; interaction options are never included.
    event('コマンド /' + command.qualified_name, '失敗' if error else '処理終了',
          error=error, 秒=round(seconds, 2), 操作ID=interaction.id)
