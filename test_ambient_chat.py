import unittest
from ambient_chat import AmbientChat, COOLDOWN


class AmbientTests(unittest.TestCase):
    def conversation(self, chat):
        chat.observe(1, 10, "今日はいい天気", now=100)
        chat.observe(1, 20, "散歩したよ", now=101)
        return chat.observe(1, 10, "気持ちよさそう", now=102)

    def test_default_enabled_and_two_speakers(self):
        self.assertIsNotNone(self.conversation(AmbientChat()))
        chat = AmbientChat()
        for i in range(4):
            self.assertIsNone(chat.observe(1, 10, "こんにちは", now=i))
        self.assertIsNotNone(chat.observe(1, 20, "いい天気", now=4))

    def test_cooldown_and_evicted_pending(self):
        chat = AmbientChat()
        state = self.conversation(chat)
        chat.reserve(state, now=102)
        state.busy = False
        self.assertIsNone(chat.observe(1, 20, "そうだね", now=103))
        self.assertEqual(state.next_attempt, 102 + COOLDOWN)
        chat.states.pop(1)
        self.assertFalse(chat.still_current(1, state))

    def test_directed_serious_and_expired_context(self):
        chat = AmbientChat()
        self.conversation(chat)
        self.assertIsNone(chat.observe(1, 20, "個別の返事", directed=True, now=103))
        self.assertEqual(len(chat.states[1].messages), 0)
        self.conversation(chat)
        self.assertIsNone(chat.observe(1, 20, "真剣に相談したい", now=104))
        self.assertIsNone(chat.observe(1, 20, "天気いいね", now=500))
        self.assertEqual(len(chat.states[1].messages), 1)

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
