import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from album_view import AlbumView
from gacha import Card


class AlbumViewTests(unittest.IsolatedAsyncioTestCase):
    def make(self, dates=None, opened=True, guild=True):
        card = Card('test', 'ロザリー', 'ロザリー【制服】', 'R')
        return AlbumView(42, card, dates or (datetime(2026, 10, 19, 16, tzinfo=timezone.utc), None, None, None, None),
                         opened=opened, guild=guild)

    async def test_only_recorded_milestones_and_private_owner_access(self):
        view = self.make()
        self.assertEqual(len(view.children[0].options), 1)
        embed, files = view.content()
        self.assertIn('2026年10月20日', embed.description)
        self.assertEqual(files, [])
        interaction = SimpleNamespace(user=SimpleNamespace(id=43), response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await view.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        view.stop()

    async def test_open_is_private_and_dm_has_no_share_button(self):
        view = self.make(opened=False)
        interaction = SimpleNamespace(guild=None, response=SimpleNamespace(send_message=AsyncMock()))
        await view.open_album(interaction)
        args = interaction.response.send_message.call_args.kwargs
        self.assertTrue(args['ephemeral'])
        self.assertEqual(len(args['view'].children), 1)
        args['view'].stop()
        view.stop()

    async def test_explicit_share_to_current_channel_once(self):
        view = self.make()
        interaction = SimpleNamespace(user=SimpleNamespace(display_name='春樹'),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            channel=SimpleNamespace(send=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()),
            edit_original_response=AsyncMock())
        await view.share(interaction)
        await view.share(interaction)
        interaction.channel.send.assert_awaited_once()
        self.assertEqual(interaction.channel.send.call_args.kwargs['allowed_mentions'].to_dict(), {'parse': []})
        self.assertTrue(view.children[1].disabled)
        view.stop()

    async def test_unrecorded_album_disables_open(self):
        view = self.make((None,) * 5, opened=False)
        self.assertTrue(view.children[0].disabled)
        view.stop()
