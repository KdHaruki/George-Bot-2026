"""コマンドとメッセージの履歴保存を非同期で行い、保存待ち件数と並列数を制限する。"""

import asyncio

from operation_logging import event as log_event


class HistoryWriter:
    feature = '履歴DB'

    def __init__(self, store):
        self.store = store
        self.slots = asyncio.Semaphore(2)
        self.tasks = set()

    def schedule(self, record):
        if not self.store.url:
            return
        # 保存待ちを無制限に積まない。超過は本文を出さずログだけ残す。
        if len(self.tasks) >= 32:
            log_event(self.feature, '保存見送り', reason='保存待ちが上限32件に到達', 記録ID=record[0])
            return

        async def save():
            try:
                async with self.slots:
                    deleted = await asyncio.to_thread(self.store.save, record)
                log_event(self.feature, '保存完了', 記録ID=record[0])
                if isinstance(deleted, int) and deleted > 0:
                    log_event(self.feature, '30日を過ぎた履歴を削除', 削除件数=deleted)
            except Exception as exc:
                log_event(self.feature, '保存失敗', error=exc, 記録ID=record[0])

        task = asyncio.create_task(save())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self):
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
