import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from george_chat import GeorgeChat
from gacha import Gacha
from database import MemoryUnavailable

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

    async def test_help_intro_is_cached_and_retried_after_failure(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            chat = GeorgeChat()
        chat.collection_comment = AsyncMock(return_value='みんな、俺も雑談に混ざるし、俺が絵文字でリアクションするぜ！')
        first = await chat.help_comment()
        self.assertEqual(await chat.help_comment(), first)
        chat.collection_comment.assert_awaited_once_with({'action': 'help_intro'})
        chat.help_cache = ('', 0)
        chat.collection_comment.side_effect = ValueError('offline')
        with self.assertRaises(ValueError):
            await chat.help_comment()
        self.assertEqual(await chat.help_comment(), '')
        self.assertEqual(chat.collection_comment.await_count, 2)

    async def test_help_visibility_and_generation_fallback(self):
        from main import help_embed
        from command_help import command_help
        bot = SimpleNamespace(george_chat=SimpleNamespace(help_comment=AsyncMock(return_value='みんな、いい調子か？')))
        embed = await help_embed(bot, True)
        self.assertIn('みんな、いい調子か？', embed.fields[0].value)
        self.assertNotIn('会話への参加・絵文字リアクションもするぜ！', embed.fields[0].value)
        text = '\n'.join(field.value for field in embed.fields[1:3])
        self.assertIn('`/おみくじ`\n今日の運勢', text)
        self.assertIn('`/お気に入り プログレス登録 ロザリー`\nプログレス名で登録。同じプログレスの再指定で解除。', text)
        self.assertNotIn('（公開情報）', text)
        self.assertNotIn('（非公開情報）', text)
        self.assertNotIn('【公開情報】', text)
        self.assertNotIn('【非公開情報】', text)
        bot.george_chat.help_comment.side_effect = ValueError('offline')
        self.assertEqual((await help_embed(bot, True)).to_dict(), command_help(True).to_dict())

    async def test_help_rejects_individual_address_and_uses_fallback(self):
        from main import help_embed
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            chat = GeorgeChat()
        chat.collection_comment = AsyncMock(return_value='よう、オマエ。俺もリアクションするぜ！')
        embed = await help_embed(SimpleNamespace(george_chat=chat), True)
        text = embed.fields[0].value
        self.assertNotIn('オマエ', text)
        self.assertEqual(text.count('リアクション'), 1)
        self.assertEqual(chat.help_cache[0], '')

    async def test_help_rejects_asking_users_for_reactions(self):
        from main import help_embed
        for answer in ('みんな、絵文字でリアクションしてくれたら嬉しいぜ！',
                       '俺が絵文字でリアクションするぜ。みんなもリアクションをお願いするぜ！'):
            with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
                chat = GeorgeChat()
            chat.collection_comment = AsyncMock(return_value=answer)
            embed = await help_embed(SimpleNamespace(george_chat=chat), True)
            self.assertIn('俺が絵文字でリアクションする', embed.fields[0].value)
            self.assertEqual(chat.help_cache[0], '')
