import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from george_chat import GeorgeChat, ChatBusy, ChatUnavailable, describe_chat_error, character_context
from google.genai import errors


class ErrorDiagnosticsTests(unittest.TestCase):
    def test_api_status_and_secret_redaction(self):
        for code, reason in [(400, "invalid_request"), (403, "authentication"),
                             (404, "model_not_found"), (429, "quota"),
                             (503, "provider_unavailable")]:
            with self.subTest(code=code):
                exc = errors.APIError(code, {"error": {"message": "SECRET_KEY private user text"}})
                diagnostic, answer = describe_chat_error(exc)
                self.assertIn(f"reason={reason}", diagnostic)
                self.assertIn(f"HTTP {code}", answer)
                self.assertNotIn("SECRET_KEY", diagnostic + answer)
                self.assertNotIn("private user text", diagnostic + answer)

    def test_timeout_and_unknown(self):
        self.assertIn("reason=timeout", describe_chat_error(TimeoutError())[0])
        self.assertIn("reason=unknown", describe_chat_error(RuntimeError("secret"))[0])

    def test_bad_request_causes_without_provider_text(self):
        cases = [
            ("API key not valid. SECRET", "invalid_api_key"),
            ("Your API key was reported as leaked. SECRET", "blocked_api_key"),
            ("User location is not supported for the API use. SECRET", "unsupported_location"),
            ("Free tier is not available in your country. SECRET", "free_tier_unavailable"),
            ("Model is not supported for generateContent. SECRET", "unsupported_model"),
        ]
        for message, reason in cases:
            with self.subTest(reason=reason):
                diagnostic, answer = describe_chat_error(errors.APIError(400, {"error": {"message": message}}))
                self.assertIn(f"reason={reason}", diagnostic)
                self.assertNotIn("SECRET", diagnostic + answer)


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

    async def test_registered_subject_is_grounded_on_followup(self):
        await self.chat.reply((1, 1), "ロザリーについて教えて")
        self.assertIn('"progressName": "ロザリー"', self.generate.call_args.kwargs["config"].system_instruction)
        await self.chat.reply((1, 1), "好きなものは？")
        self.assertIn('"progressLike": "手品、鏡"', self.generate.call_args.kwargs["config"].system_instruction)
        await self.chat.reply((2, 1), "好きなものは？")
        self.assertNotIn('"progressName": "ロザリー"', self.generate.call_args.kwargs["config"].system_instruction)

    def test_unknown_subject_has_no_invented_record(self):
        self.assertEqual(character_context("未登録の人物について"), "")

    async def test_ambient_skip_and_no_personal_history(self):
        await self.chat.reply((1, 1), "個人の話")
        messages = [(1, 100, "天気いいね"), (2, 200, "散歩した"), (3, 100, "楽しそう")]
        self.generate.return_value = SimpleNamespace(text="__SKIP__")
        self.assertIsNone(await self.chat.ambient_reply(messages))
        payload = self.generate.call_args.kwargs["contents"]
        self.assertNotIn("個人の話", payload)
        self.assertEqual(len(self.chat.sessions[(1, 1)].history), 2)
        for answer in ("どうだった？", "長" * 151, "一行\n二行"):
            self.generate.return_value = SimpleNamespace(text=answer)
            self.assertIsNone(await self.chat.ambient_reply(messages))
        self.generate.return_value = SimpleNamespace(text="散歩日和だな！")
        self.assertEqual(await self.chat.ambient_reply(messages), "散歩日和だな！")

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
