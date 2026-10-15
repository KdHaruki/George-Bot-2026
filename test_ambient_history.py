import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import discord

from ambient_history import load_ambient_history


def message(number, text='いい天気だね', author=None, **kwargs):
    return SimpleNamespace(id=number, content=text,
                           author=SimpleNamespace(id=author or (number % 2 + 1), bot=kwargs.get('bot', False)),
                           attachments=kwargs.get('attachments', []), mentions=kwargs.get('mentions', []),
                           role_mentions=[], mention_everyone=False, reference=kwargs.get('reference'),
                           created_at=datetime.now(timezone.utc))


def trigger_with(rows, error=None):
    async def history(**kwargs):
        if error:
            raise error
        for row in rows:
            yield row
    trigger = message(100)
    trigger.channel = SimpleNamespace(history=Mock(side_effect=history))
    return trigger


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_history_permission_does_not_request_discord(self):
        trigger = trigger_with([message(100), message(99), message(98)])
        trigger.guild = SimpleNamespace(me=object())
        trigger.channel.permissions_for = Mock(return_value=SimpleNamespace(view_channel=True, read_message_history=False))
        self.assertEqual(await load_ambient_history(trigger), [])
        trigger.channel.history.assert_not_called()

    async def test_fetches_before_trigger_and_sends_latest_eight_in_time_order(self):
        trigger = trigger_with([message(i, str(i)) for i in range(100, 85, -1)])
        context = await load_ambient_history(trigger)
        self.assertEqual([item[2] for item in context], [str(i) for i in range(93, 101)])
        options = trigger.channel.history.call_args.kwargs
        self.assertEqual(options['limit'], 30)
        self.assertEqual(options['before'].id, 101)
        self.assertFalse(options['oldest_first'])

    async def test_keeps_images_and_skips_bots(self):
        image = SimpleNamespace(filename='photo.png')
        trigger = trigger_with([message(100, '', attachments=[image]), message(99, bot=True), message(98), message(97)])
        context = await load_ambient_history(trigger)
        self.assertEqual(len(context), 3)
        self.assertEqual(context[-1][3], (image,))

    async def test_directed_or_command_is_a_boundary(self):
        for separator in [message(98, mentions=[1]), message(98, reference=object()), message(98, '/command')]:
            trigger = trigger_with([message(100), message(99), separator, message(97)])
            self.assertEqual(await load_ambient_history(trigger), [])

    async def test_serious_old_context_and_missing_trigger_are_skipped(self):
        for rows in [[message(100), message(99), message(98, '真剣な相談がある')],
                     [message(99), message(98), message(97)],
                     [message(100, author=1), message(99, author=1), message(98, author=1)]]:
            self.assertEqual(await load_ambient_history(trigger_with(rows)), [])

    async def test_timeout_and_permission_failure_skip_without_fallback(self):
        response = SimpleNamespace(status=403, reason='Forbidden')
        for error in [asyncio.TimeoutError(), discord.Forbidden(response, 'Missing permissions')]:
            self.assertEqual(await load_ambient_history(trigger_with([], error)), [])
