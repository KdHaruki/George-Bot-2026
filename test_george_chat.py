import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from george_chat import GeorgeChat, ChatBusy, ChatUnavailable


class GeorgeChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.chat = GeorgeChat()
        self.generate = AsyncMock(return_value=SimpleNamespace(text="こんにちはだぜ！"))
        self.chat.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=self.generate)))

    async def test_history_is_separate_and_bounded(self):
        for i in range(12):
            await self.chat.reply((1, 1), str(i))
        self.assertEqual(len(self.chat.sessions[(1, 1)].history), 20)
        await self.chat.reply((1, 2), "別の人")
        self.assertEqual(len(self.generate.call_args.kwargs["contents"]), 1)
        self.chat.reset((1, 1))
        self.assertNotIn((1, 1), self.chat.sessions)
        self.assertIn((1, 2), self.chat.sessions)

    async def test_failure_does_not_commit_history(self):
        await self.chat.reply((1, 1), "最初")
        self.generate.side_effect = RuntimeError("provider failed")
        with self.assertRaises(RuntimeError):
            await self.chat.reply((1, 1), "失敗")
        self.assertEqual(len(self.chat.sessions[(1, 1)].history), 2)
        self.assertFalse(self.chat.sessions[(1, 1)].lock.locked())

    async def test_busy_reply_and_reset(self):
        session = self.chat._session((1, 1))
        async with session.lock:
            with self.assertRaises(ChatBusy):
                await self.chat.reply((1, 1), "同時送信")
            with self.assertRaises(ChatBusy):
                self.chat.reset((1, 1))

    async def test_empty_response_and_missing_key(self):
        self.generate.return_value = SimpleNamespace(text=None)
        self.assertTrue(await self.chat.reply((1, 1), "こんにちは"))
        self.assertEqual(self.chat.sessions[(1, 1)].history, [])
        self.chat.client = None
        with self.assertRaises(ChatUnavailable):
            await self.chat.reply((1, 1), "こんにちは")

    async def test_eviction_preserves_active_session(self):
        active = self.chat._session((1, 0))
        async with active.lock:
            for i in range(1, 257):
                self.chat._session((1, i))
            self.assertEqual(len(self.chat.sessions), 256)
            self.assertIn((1, 0), self.chat.sessions)
            self.assertNotIn((1, 1), self.chat.sessions)


if __name__ == "__main__":
    unittest.main()
