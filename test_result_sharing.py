import asyncio
import io
import random
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from unittest.mock import patch

import discord

from result_sharing import ShareButton, ShareView


class SharingTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, user=42, guild=True):
        return SimpleNamespace(id=123, user=SimpleNamespace(id=user, display_name='春樹 @everyone'),
            guild=SimpleNamespace(id=8) if guild else None,
            channel=SimpleNamespace(id=9, send=AsyncMock()),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def test_public_snapshot_owner_and_duplicate_guard(self):
        snapshot = discord.Embed(title='クイズ', description='ヒント1回目で正解・贈り物・プロフィール')
        view = ShareView(42, lambda: ([snapshot], []))
        button = view.children[0]
        other = self.interaction(43)
        await button.callback(other)
        other.channel.send.assert_not_awaited()
        self.assertTrue(other.response.send_message.call_args.kwargs['ephemeral'])
        owner = self.interaction()
        await asyncio.gather(button.callback(owner), button.callback(owner))
        owner.channel.send.assert_awaited_once()
        kwargs = owner.channel.send.call_args.kwargs
        self.assertEqual(kwargs['embeds'][0].to_dict(), snapshot.to_dict())
        self.assertEqual(kwargs['allowed_mentions'].to_dict(), discord.AllowedMentions.none().to_dict())
        self.assertNotIn('view', kwargs)
        self.assertTrue(button.disabled)
        view.stop()

    async def test_dm_cannot_publish(self):
        view = ShareView(42, Mock())
        interaction = self.interaction(guild=False)
        await view.children[0].callback(interaction)
        interaction.channel.send.assert_not_awaited()
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        view.stop()

    async def test_failed_send_closes_files_and_never_retries(self):
        close = Mock()
        file = SimpleNamespace(close=close)
        view = ShareView(42, lambda: ([discord.Embed(title='お気に入り')], [file]))
        interaction = self.interaction()
        interaction.channel.send.side_effect = TimeoutError('private')
        await view.children[0].callback(interaction)
        await view.children[0].callback(interaction)
        interaction.channel.send.assert_awaited_once()
        close.assert_called_once()
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        view.stop()

    async def test_large_inventory_shares_all_pages_with_discord_limits(self):
        from gacha_commands import CardListView
        lines = [f'カード{i} — 2枚' for i in range(115)]
        view = CardListView(42, lines, '所持カード', can_share=True)
        button = next(child for child in view.children if isinstance(child, ShareButton))
        interaction = self.interaction()
        await button.callback(interaction)
        embeds = [embed for call in interaction.channel.send.call_args_list for embed in call.kwargs['embeds']]
        self.assertEqual('\n'.join(embed.description for embed in embeds), '\n'.join(lines))
        for call in interaction.channel.send.call_args_list:
            self.assertLessEqual(len(call.kwargs['embeds']), 10)
            self.assertLessEqual(sum(len(e) for e in call.kwargs['embeds']), 6000)
        view.stop()

    async def test_quiz_share_appears_only_after_correct_and_rewards_unchanged(self):
        from ange_quiz import QuizView
        store = SimpleNamespace(claim_quiz=Mock(return_value={'granted': True, 'item': 'food'}))
        quiz = QuizView(42, rng=random.Random(1), reward_store=store, reward_id=100)
        self.assertFalse(any(isinstance(child, ShareButton) for child in quiz.children))
        correct = next(child for child in quiz.children if child.label == quiz.answer['progressName'])
        interaction = self.interaction()
        await correct.callback(interaction)
        result = interaction.edit_original_response.call_args.kwargs
        shared = result['view']
        self.assertIsInstance(shared, ShareView)
        await shared.children[0].callback(interaction)
        await shared.children[0].callback(interaction)
        store.claim_quiz.assert_called_once_with(42, 100, 1)
        public = interaction.channel.send.call_args.kwargs['embeds'][0]
        self.assertEqual(public.to_dict(), result['embed'].to_dict())
        self.assertIn('紅茶', public.description)
        self.assertIn('ヒント1回目', public.description)
        shared.stop()

    async def test_title_shares_only_selected_earned_title_and_remembers_publication(self):
        from title_commands import TitleView
        view = TitleView(42, [('fortune10', '神頼み', None), ('quiz10', '青蘭学園の知恵袋', None)],
                         None, SimpleNamespace(id=8))
        view.selected = 'fortune10'
        view.build()
        button = next(child for child in view.children if isinstance(child, ShareButton))
        interaction = self.interaction()
        await button.callback(interaction)
        public = interaction.channel.send.call_args.kwargs['embeds'][0]
        self.assertIn('神頼み', public.title)
        self.assertIn('獲得日', public.description)
        self.assertNotIn('知恵袋', str(public.to_dict()))
        view.build()
        self.assertTrue(next(child for child in view.children if isinstance(child, ShareButton)).disabled)
        view.mode = 'pending'
        view.build()
        self.assertFalse(any(isinstance(child, ShareButton) for child in view.children))
        view.stop()

    async def test_favorite_publishes_stats_album_and_reuploaded_art_without_new_lookup(self):
        from discord import app_commands
        from gacha import Gacha
        from gacha_commands import register_gacha_commands
        card = next(card for card in Gacha().pools['relink']['★3'] if card.character == 'ロザリー')
        store = SimpleNamespace(url='test', favorite=Mock(return_value=('relink', card, 2)))
        client = discord.Client(intents=discord.Intents.default())
        presents = SimpleNamespace(affection_status=Mock(return_value=(51, 0)),
                                  album=Mock(return_value=(None,) * 6))
        bot = SimpleNamespace(tree=app_commands.CommandTree(client), present_store=presents)
        register_gacha_commands(bot, store)
        interaction = self.interaction()
        created = []
        def files(cards):
            file = discord.File(io.BytesIO(b'art'), filename='art.png')
            created.append(file)
            return [file]
        def images(cards):
            return [discord.Embed(title='カード画像').set_image(url='attachment://art.png')]
        with patch('gacha_commands.presentation_files', files), patch('gacha_commands.star3_embeds', images):
            await bot.tree.get_command('お気に入り').get_command('プログレス確認').callback(interaction)
            private = interaction.followup.send.call_args_list[0].kwargs
            self.assertTrue(private['ephemeral'])
            view = private['view']
            await view.children[0].callback(interaction)
            await view.children[0].callback(interaction)
        public = interaction.channel.send.call_args.kwargs
        self.assertEqual(public['embeds'][0].to_dict(), private['embed'].to_dict())
        self.assertIn('51/100', str(public['embeds'][0].to_dict()))
        self.assertIn('アルバム', str(public['embeds'][0].to_dict()))
        self.assertEqual(public['embeds'][1].image.url, 'attachment://art.png')
        self.assertEqual(len(created), 2)
        self.assertIsNot(created[0], created[1])
        self.assertEqual(len(public['files']), 1)
        store.favorite.assert_called_once()
        presents.affection_status.assert_called_once()
        view.stop()
        await client.close()
