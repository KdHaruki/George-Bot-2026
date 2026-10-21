import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from feature_qa import resolve, catalog, topic_for, CLARIFY
from george_chat import GeorgeChat
from command_help import SLASH_COMMANDS
from present_catalog import ITEMS


class FeatureQATests(unittest.TestCase):
    def test_all_registered_help_commands_have_answers(self):
        for example, _ in SLASH_COMMANDS:
            answer, topic, person = resolve(example + 'の使い方を教えて')
            self.assertIsNotNone(answer, example)
            self.assertIn(topic, catalog())
        for question in ['/季節通知 設定の使い方は？', '/状態って何？']:
            self.assertIsNotNone(resolve(question)[0])

    def test_followup_subject_and_item_values(self):
        answer, topic, person = resolve('ロザリーには何あげたら喜ぶ？')
        self.assertIn('魔法・機械', answer)
        answer, topic, person = resolve('美海は？', previous_topic=topic, previous_person=person)
        self.assertEqual(person, '日向美海')
        answer, _, _ = resolve('紅茶でも＋5？', previous_topic='gifts', previous_person='ロザリー')
        self.assertIn('紅茶：好感度＋2', answer)
        answer, _, _ = resolve('手鏡でも＋5？', previous_topic='gifts', previous_person='ロザリー')
        self.assertIn('手鏡：好感度＋5', answer)
        answer, _, _ = resolve('虹色の花束って何？')
        self.assertIsNotNone(answer)

    def test_acquisition_and_visibility_are_not_preferences(self):
        answer, _, _ = resolve('プレゼントは1日に何回もらえる？', previous_topic='gifts', previous_person='ロザリー')
        self.assertIn('それぞれ日本時間1日1回', answer)
        answer, topic, _ = resolve('/ガチャは誰に見える？')
        self.assertEqual(topic, 'visibility')
        self.assertIn('チャンネル全員', answer)
        answer, topic, _ = resolve('お気に入りのアルバムは何？')
        self.assertEqual(topic, 'album')
        self.assertIn('4項目', answer)

    def test_unrelated_chat_does_not_reuse_previous_subject(self):
        self.assertIsNone(resolve('今日の夕飯は何がいい？', previous_topic='gifts', previous_person='ロザリー')[0])
        answer, _, _ = resolve('ロザリーと日向美海に何をプレゼントしたら喜ぶ？')
        self.assertIn('1人ずつ', answer)


class FeatureRoutingTests(unittest.IsolatedAsyncioTestCase):
    def make_chat(self, response):
        with patch.dict('os.environ', {'GEMINI_API_KEY': ''}):
            chat = GeorgeChat()
        generate = AsyncMock(return_value=SimpleNamespace(text=response))
        chat.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        return chat, generate

    async def test_unknown_command_cannot_create_feature_even_on_bad_model_output(self):
        chat, generate = self.make_chat('{"topic":"invented","answer":"使えるぜ"}')
        answer = await chat.reply((1, 42), '/未実装コマンドって使える？')
        self.assertEqual(answer, CLARIFY)
        self.assertNotIn('使えるぜ', answer)
        generate.assert_awaited_once()

    async def test_semantic_router_only_selects_approved_answer(self):
        chat, generate = self.make_chat('{"topic":"seasonal","answer":"誕生日も通知する"}')
        answer = await chat.reply((1, 42), 'ジョージの機能でカレンダーのお知らせは出来る？')
        self.assertEqual(answer, CLARIFY)
        self.assertNotIn('季節通知', answer)
        generate.assert_awaited_once()

    async def test_known_facts_work_without_ai_and_context_is_per_user(self):
        chat, generate = self.make_chat('unused')
        chat.client = None
        answer = await chat.reply((1, 42), 'ロザリーに喜ばれる贈り物は？')
        self.assertIn('魔法・機械', answer)
        answer = await chat.reply((1, 43), 'その子に喜ばれる贈り物は何？')
        self.assertIn('名前を教えて', answer)
        self.assertNotIn('ロザリー', answer)
        generate.assert_not_awaited()
