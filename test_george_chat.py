import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from george_chat import GeorgeChat, ChatBusy, ChatUnavailable, describe_chat_error, character_context, finish_reply
from google.genai import errors


class ErrorDiagnosticsTests(unittest.TestCase):
    def test_question_suffix(self):
        self.assertEqual(finish_reply("どうした？  \n"), "どうした？")
        self.assertEqual(finish_reply("元気?"), "元気?")
        self.assertEqual(finish_reply("絶好調だな？__BALL_LINE__"), "絶好調だな？球筋に出てるぜ。")
        self.assertEqual(finish_reply("元気だぜ！__BALL_LINE__"), "元気だぜ！")
        self.assertEqual(finish_reply("途中__BALL_LINE__の目印"), "途中の目印")
        self.assertEqual(finish_reply("どうした？ 話を聞くぜ。"), "どうした？ 話を聞くぜ。")
        self.assertEqual(finish_reply("元気だぜ！"), "元気だぜ！")

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

    async def test_gift_preferences_match_ui_for_current_favorite(self):
        answer = await self.chat.reply((1, 42), 'その子に喜ばれる贈り物ってなに？', favorite={'character': 'ロザリー'})
        self.assertIn('ファッション・美容', answer)
        self.assertIn('魔法・機械', answer)
        self.assertNotIn('食べ物・飲み物', answer)
        self.generate.assert_not_awaited()
        answer = await self.chat.reply((1, 42), 'もう一度ロザリーの喜ばれる贈り物を教えて')
        self.assertIn('魔法・機械', answer)
        self.assertNotIn('聞き逃', answer)
        self.generate.assert_not_awaited()

    async def test_title_condition_is_authoritative_without_generation(self):
        answer = await self.chat.reply((1, 42), '青蘭学園の叛逆者はどちらが取得しやすい？')
        self.assertIn('リリンク10連は7枚以上', answer)
        self.assertIn('両作品が対象', answer)
        self.generate.assert_not_awaited()
        followup = await self.chat.reply((1, 42), 'リリンクでも取得できるよね？', reply_to='青蘭学園の叛逆者はヴィエルジュ限定だぜ')
        self.assertIn('ヴィエルジュ限定じゃねえ', followup)
        self.generate.assert_not_awaited()
        self.assertEqual(len(self.chat.sessions[(1, 42)].history), 4)

    async def test_conversation_includes_current_usage_without_extra_generation(self):
        from command_help import SLASH_COMMANDS
        from present_catalog import ITEMS, CATEGORIES
        await self.chat.reply((1, 42), '今日は元気だよ！')
        self.generate.assert_awaited_once()
        instruction = self.generate.call_args.kwargs['config'].system_instruction
        self.assertIn('【現在のBotの使い方案内】', instruction)
        for example, _ in SLASH_COMMANDS:
            self.assertIn(example, instruction)
        for _, name in ITEMS.values():
            self.assertIn(name, instruction)
        for name, _ in CATEGORIES.values():
            self.assertIn(name, instruction)
        self.assertIn('通常＋2、喜ばれる贈り物は合計＋5、レア＋10', instruction)
        self.assertIn('パーフェクトリンク後も贈れます', instruction)
        self.assertIn('所持品・好感度・称号・設定の現在値は、この案内からは確認できません', instruction)
        self.assertIn('廃止された機能や存在しないコマンドを作りません', instruction)
        self.assertIn('コマンドやボタンを代理実行', instruction)

    async def test_followup_keeps_usage_guide_alongside_reply_reference(self):
        answer = await self.chat.reply((1, 42), '称号って何？')
        self.assertIn('獲得済み・未獲得', answer)
        answer = await self.chat.reply((1, 42), 'それってどうやるの？', reply_to='未獲得に切り替えると条件が見えるぜ。')
        self.assertIn('/称号', answer)
        self.generate.assert_not_awaited()

    async def test_history_is_separate_and_bounded(self):
        for i in range(12):
            await self.chat.reply((1, 1), str(i))
        self.assertEqual(len(self.chat.sessions[(1, 1)].history), 20)
        await self.chat.reply((1, 2), "別の人")
        self.assertEqual(len(self.generate.call_args.kwargs["contents"]), 1)
        self.assertIn((1, 1), self.chat.sessions)
        self.assertIn((1, 2), self.chat.sessions)

    async def test_reply_quote_is_included_without_other_users_history(self):
        await self.chat.reply((1, 1), "別の人の話")
        await self.chat.reply((1, 2), "詳しく教えて", reply_to="ロザリーについての返事")
        contents = self.generate.call_args.kwargs["contents"]
        self.assertEqual(len(contents), 1)
        self.assertIn("ロザリーについての返事", contents[0].parts[0].text)
        self.assertNotIn("別の人の話", contents[0].parts[0].text)

    async def test_ambient_character_records_are_scoped_to_current_conversation(self):
        await self.chat.ambient_reply([(1, 100, 'ロザリーの好みは？'), (2, 200, '気になるね')])
        instruction = self.generate.call_args.kwargs['config'].system_instruction
        self.assertIn('"progressName": "ロザリー"', instruction)
        self.assertIn('"progressLike": "手品、鏡"', instruction)
        await self.chat.ambient_reply([(3, 100, '今日は晴れたね'), (4, 200, '散歩しよう')])
        instruction = self.generate.call_args.kwargs['config'].system_instruction
        self.assertNotIn('"progressName": "ロザリー"', instruction)
        self.assertFalse(self.chat.sessions)

    async def test_collection_comment_is_bounded_and_isolated(self):
        await self.chat.reply((1, 1), '個人の会話')
        self.generate.return_value = SimpleNamespace(text='ロザリーが来たぜ！')
        facts = {'action': 'draw', 'new_count': 1}
        self.assertEqual(await self.chat.collection_comment(facts), 'ロザリーが来たぜ！')
        self.assertNotIn('個人の会話', self.generate.call_args.kwargs['contents'])
        self.assertIn('かわいこちゃん', self.generate.call_args.kwargs['config'].system_instruction)
        for answer in ('', 'あ' * 141, 'https://example.com'):
            self.generate.return_value = SimpleNamespace(text=answer)
            with self.assertRaises(ValueError):
                await self.chat.collection_comment(facts)

    async def test_fortune_comment_uses_selected_progress_profile(self):
        self.generate.return_value = SimpleNamespace(text='{"comment":"大吉だぜ！ ロザリーみたいにおしゃれを楽しんでみな！"}')
        await self.chat.fortune_details('大吉', 'ロザリー')
        args = self.generate.call_args.kwargs
        self.assertIn('ロザリー', args['contents'])
        self.assertIn('progressLike', args['contents'])
        self.assertIn('運勢とラッキープログレスの両方', args['config'].system_instruction)

    async def test_fortune_rejects_reannouncement_or_missing_character(self):
        import json
        for comment in ('大吉だぜ！ 今日のラッキープログレスはロザリーだ！', '大吉だぜ！ 楽しもうな！'):
            self.generate.return_value = SimpleNamespace(text=json.dumps({'comment': comment}, ensure_ascii=False))
            with self.assertRaises(ValueError):
                await self.chat.fortune_details('大吉', 'ロザリー')

    async def test_ai_fortune_is_validated_and_has_no_chat_history(self):
        await self.chat.reply((1, 1), "個人の会話")
        self.generate.return_value = SimpleNamespace(text='{"comment":"いい流れだぜ！"}')
        self.assertEqual(await self.chat.fortune_details("大吉"), "いい流れだぜ！")
        self.assertNotIn("個人の会話", self.generate.call_args.kwargs["contents"])
        self.assertNotIn("lucky_item", str(self.generate.call_args.kwargs["config"]))
        self.assertEqual(len(self.chat.sessions[(1, 1)].history), 2)
        for text in ('{}', '{"comment":123}', '{"comment":""}'):
            self.generate.return_value = SimpleNamespace(text=text)
            with self.assertRaises(ValueError):
                await self.chat.fortune_details("凶")

    async def test_seasonal_greeting_uses_only_event_names(self):
        await self.chat.reply((1, 1), "個人の会話")
        self.generate.return_value = SimpleNamespace(text="今日はハロウィンだぜ！")
        self.assertEqual(await self.chat.seasonal_comment(["ハロウィン"]), "今日はハロウィンだぜ！")
        self.assertIn('呼びかけは「みんな」', self.generate.call_args.kwargs['config'].system_instruction)
        for answer in ('オマエも新しいことに挑戦するのか？', 'キミも楽しんでくれ！'):
            self.generate.return_value = SimpleNamespace(text=answer)
            with self.assertRaises(ValueError):
                await self.chat.seasonal_comment(['テスト投稿の日'])
        self.assertNotIn("個人の会話", self.generate.call_args.kwargs["contents"])
        self.assertEqual(len(self.chat.sessions[(1, 1)].history), 2)
        self.generate.return_value = SimpleNamespace(text="")
        with self.assertRaises(ValueError):
            await self.chat.seasonal_comment(["元日"])

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

    async def test_ambient_skip_logs_reason_without_content(self):
        messages = [(123, 100, '秘密の会話本文')]
        cases = [('__SKIP__:serious', 'model_serious'),
                 ('__SKIP__:秘密の返答', 'model_unspecified'),
                 ('', 'empty_response'), ('長' * 151, 'too_long'),
                 ('一行\n二行', 'multiline'), ('どうだった？', 'question')]
        for answer, reason in cases:
            with self.subTest(reason=reason):
                self.generate.return_value = SimpleNamespace(text=answer)
                with self.assertLogs('george.ambient', level='INFO') as logs:
                    self.assertIsNone(await self.chat.ambient_reply(messages))
                output = '\n'.join(logs.output)
                self.assertIn('reason=' + reason, output)
                self.assertIn('message=123', output)
                self.assertNotIn('秘密', output)

    async def test_failure_does_not_commit_history(self):
        await self.chat.reply((1, 1), "最初")
        self.generate.side_effect = RuntimeError("provider failed")
        with self.assertRaises(RuntimeError):
            await self.chat.reply((1, 1), "失敗")
        self.assertEqual(len(self.chat.sessions[(1, 1)].history), 2)
        self.assertFalse(self.chat.sessions[(1, 1)].lock.locked())

    async def test_busy_reply(self):
        session = self.chat._session((1, 1))
        async with session.lock:
            with self.assertRaises(ChatBusy):
                await self.chat.reply((1, 1), "同時送信")

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
