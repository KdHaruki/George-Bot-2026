import unittest
from ambient_chat import AmbientChat, COOLDOWN, RETRY_DELAY


class AmbientTests(unittest.TestCase):
    def conversation(self, chat):
        chat.observe(1, 10, "今日はいい天気", now=100)
        chat.observe(1, 20, "散歩したよ", now=101)
        return chat.observe(1, 10, "気持ちよさそう", now=102)

    def test_default_enabled_and_two_speakers(self):
        self.assertIsNotNone(self.conversation(AmbientChat()))
        chat = AmbientChat()
        for i in range(4):
            self.assertIsNotNone(chat.observe(1, 10, "こんにちは", now=i))
        self.assertIsNotNone(chat.observe(1, 20, "いい天気", now=4))

    def test_cooldown_and_evicted_pending(self):
        chat = AmbientChat()
        state = self.conversation(chat)
        chat.reserve(state, now=102)
        state.busy = False
        self.assertIsNone(chat.observe(1, 20, "そうだね", now=103))
        self.assertEqual(state.next_attempt, 102 + RETRY_DELAY)
        chat.states.pop(1)
        self.assertFalse(chat.still_current(1, state))

    def test_only_successful_ambient_reply_starts_hour_cooldown(self):
        chat = AmbientChat()
        state = self.conversation(chat)
        chat.reserve(state, now=102)
        self.assertEqual(state.next_attempt, 102 + RETRY_DELAY)
        chat.note_reply(1)
        self.assertEqual(state.next_attempt, 102 + RETRY_DELAY)
        chat.note_auto_reply(1, now=500)
        self.assertEqual(state.next_attempt, 500 + COOLDOWN)
        self.assertEqual(len(state.messages), 0)

    def test_directed_and_serious_context(self):
        chat = AmbientChat()
        self.conversation(chat)
        self.assertIsNone(chat.observe(1, 20, "個別の返事", directed=True, now=103))
        self.assertEqual(len(chat.states[1].messages), 0)
        self.conversation(chat)
        self.assertIsNone(chat.observe(1, 20, "真剣に相談したい", now=104))
        self.assertIsNone(chat.observe(1, 20, "天気いいね", now=500))
        self.assertEqual(len(chat.states[1].messages), 5)

    def test_context_survives_time_gaps_but_is_limited_to_latest_eight(self):
        chat = AmbientChat()
        chat.observe(1, 10, "散歩したよ", now=0)
        chat.observe(1, 20, "どこに行ったの", now=3600)
        state = chat.observe(1, 10, "公園まで行ったよ", now=7200)
        self.assertIsNotNone(state)
        self.assertEqual(state.messages[0][2], "散歩したよ")
        for i in range(10):
            chat.observe(1, 10 + i % 2, str(i), now=8000 + i)
        self.assertEqual(len(state.messages), 8)
        self.assertEqual([item[2] for item in state.messages], [str(i) for i in range(2, 10)])

    def test_multiple_channels_have_separate_context_and_cooldown(self):
        chat = AmbientChat()
        first = self.conversation(chat)
        chat.reserve(first, now=102)
        chat.observe(2, 30, "ゲーム楽しい", now=103)
        chat.observe(2, 40, "一緒に遊んだ", now=104)
        second = chat.observe(2, 30, "また遊ぼう", now=105)
        self.assertIsNotNone(second)
        self.assertEqual(second.next_attempt, 0)
        self.assertEqual({m[1] for m in second.messages}, {30, 40})


if __name__ == "__main__":
    unittest.main()
