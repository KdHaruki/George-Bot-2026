import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from george_chat import GeorgeChat
from gacha import Gacha
from registered_memory import MemoryUnavailable

class FavoriteConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_favorite_is_user_scoped_and_failure_is_optional(self):
        from main import conversation_favorite
        card = next(c for c in Gacha().pools['vierge']['UR'] if c.character == 'ロザリー')
        store = SimpleNamespace(url='test', favorite=Mock(return_value=('vierge', card, 1)))
        result = await conversation_favorite(SimpleNamespace(collection_store=store), 42)
        store.favorite.assert_called_once_with(42)
        self.assertEqual(result['character'], 'ロザリー')
        self.assertNotIn('quantity', result)
        store.favorite.return_value = None
        self.assertIsNone(await conversation_favorite(SimpleNamespace(collection_store=store), 43))
        store.favorite.side_effect = MemoryUnavailable('offline')
        self.assertIsNone(await conversation_favorite(SimpleNamespace(collection_store=store), 42))

    async def test_preference_does_not_leak_between_users(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            chat = GeorgeChat()
        generate = AsyncMock(return_value=SimpleNamespace(text='いい調子だぜ！'))
        chat.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        await chat.reply((1, 42), 'あの子は？', favorite={'character': 'ロザリー', 'profile': '幻影の魔女'})
        self.assertIn('今回話しているユーザーのお気に入り', generate.call_args.kwargs['config'].system_instruction)
        await chat.reply((1, 43), 'こんにちは')
        self.assertNotIn('今回話しているユーザーのお気に入り', generate.call_args.kwargs['config'].system_instruction)

    async def test_character_line_uses_own_instruction(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            chat = GeorgeChat()
        generate = AsyncMock(return_value=SimpleNamespace(text='今日も楽しんでいこうね！'))
        chat.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        await chat.collection_comment({'action': 'character_line', 'character': 'ロザリー', 'profile': '幻影の魔女'})
        self.assertIn('本人として', generate.call_args.kwargs['config'].system_instruction)
        self.assertNotIn('俺はジョージ', generate.call_args.kwargs['config'].system_instruction)
