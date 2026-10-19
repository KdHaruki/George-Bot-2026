import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main
from fun_features import FORTUNES


class FortuneFavoriteTests(unittest.IsolatedAsyncioTestCase):
    async def run_fortune(self, favorite, failure=False):
        generate = AsyncMock(return_value='いい一日にしようね！')
        if failure:
            generate.side_effect = ValueError('invalid response')
        bot = SimpleNamespace(george_chat=SimpleNamespace(fortune_details=generate))
        interaction = SimpleNamespace(user=SimpleNamespace(id=42),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(main, 'client', bot), patch.object(main, 'conversation_favorite',
                AsyncMock(return_value=favorite)) as lookup:
            await main.omikuji.callback(interaction)
        lookup.assert_not_awaited()
        self.assertEqual(generate.await_count, 1)
        return generate, interaction.followup.send.call_args.kwargs['embed']

    async def test_default_speaker_is_george(self):
        generate, embed = await self.run_fortune(None)
        self.assertEqual(embed.fields[0].name, '【ジョージの一言】')
        self.assertEqual(generate.call_args.kwargs, {})

    async def test_generation_failure_uses_george_fallback(self):
        generate, embed = await self.run_fortune({'character': 'ロザリー'}, failure=True)
        fortune = generate.call_args.args[0]
        self.assertEqual(embed.fields[0].name, '【ジョージの一言】')
        self.assertIn(dict(FORTUNES)[fortune], embed.fields[0].value)
