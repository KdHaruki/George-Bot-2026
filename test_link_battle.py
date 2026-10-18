import asyncio
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, MagicMock, patch
import discord
from discord import app_commands
from gacha import Gacha
from link_battle import Battle, BattleStore, BattleView, register_link_battle, character_identity
from registered_memory import MemoryUnavailable

class BattleTests(unittest.TestCase):
    def test_actions_exceed_once_and_terminal_immutable(self):
        state = Battle('ロザリー')
        rng = SimpleNamespace(randint=lambda low, high: low)
        self.assertTrue(state.act('exceed', rng))
        snapshot = (state.hp, state.enemy_hp, state.turn)
        self.assertFalse(state.act('exceed', rng))
        self.assertEqual(snapshot, (state.hp,state.enemy_hp,state.turn))
        state.enemy_hp = 1
        self.assertTrue(state.act('attack', rng))
        self.assertEqual(state.result, 'won')
        self.assertEqual(state.hp, snapshot[0])
        self.assertFalse(state.act('attack', rng))

    def test_defense_reduces_telegraphed_heavy_hit_and_bonds_help(self):
        rng = SimpleNamespace(randint=lambda low, high: high)
        attack, defend = Battle('ロザリー',turn=2), Battle('ロザリー',turn=2)
        attack.act('attack',rng)
        defend.act('defend',rng)
        self.assertGreater(defend.hp,attack.hp)
        stronger = Battle('ロザリー',points=500)
        self.assertEqual(stronger.level,6)
        stronger.act('attack',rng)
        self.assertLess(stronger.enemy_hp,90-20)
        losing = Battle('ロザリー',hp=1)
        losing.act('defend',rng)
        self.assertEqual(losing.result,'lost')

    def test_same_character_across_games_has_same_identity(self):
        engine = Gacha()
        for name in ('ロザリー','クラリス','ユフィ','カレン','葵','空'):
            card = next(c for pool in engine.pools['relink'].values() for c in pool if c.character==name)
            self.assertIn(character_identity(card), [c.character for c in engine.pools['vierge']['UR']] + ['久遠空'])

    def test_reward_only_on_first_completed_transition(self):
        store = BattleStore('test')
        conn = MagicMock()
        @contextmanager
        def connect():
            yield conn
        store.connect = connect
        for first in (True,False):
            conn.reset_mock()
            conn.execute.return_value.fetchone.side_effect = [(1,) if first else None,(1,)]
            self.assertEqual(store.finish(1,7,'ロザリー','won'),1)
            inserts = [call for call in conn.execute.call_args_list if 'INSERT' in call.args[0]]
            self.assertEqual(len(inserts),int(first))
            self.assertEqual(conn.execute.call_args_list[0].args[1],('won',1,7,'ロザリー'))

    def test_daily_limit_rolls_back_start_and_queries_parameterized(self):
        store = BattleStore('test')
        conn = MagicMock()
        @contextmanager
        def connect():
            yield conn
        store.connect = connect
        # Advisory lock has no fetch; first lookup absent then daily update rejected.
        conn.execute.return_value.fetchone.side_effect = [None,None]
        with self.assertRaises(ValueError):
            store.start(1,7,"quote'",date(2026,10,18))
        self.assertFalse(any('INSERT INTO george_link_battles' in call.args[0] for call in conn.execute.call_args_list))
        self.assertEqual(conn.execute.call_args.args[1],(7,date(2026,10,18),3))

class BattleCommandTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self):
        return SimpleNamespace(id=1,user=SimpleNamespace(id=7),response=SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def test_requires_favorite_and_starts_private_then_blocks_parallel(self):
        client = discord.Client(intents=discord.Intents.none())
        card = Gacha().pools['relink']['★3'][0]
        favorites = Mock(return_value=None)
        bot = SimpleNamespace(tree=app_commands.CommandTree(client), collection_store=SimpleNamespace(favorite=favorites))
        store = SimpleNamespace(start=Mock(return_value=(0,1)), finish=Mock(return_value=1))
        register_link_battle(bot,store)
        interaction = self.interaction()
        command = bot.tree.get_command('エクシーズバトル')
        await command.callback(interaction)
        store.start.assert_not_called()
        favorites.return_value=('relink',card,1)
        await command.callback(interaction)
        call=interaction.followup.send.call_args
        self.assertTrue(call.kwargs['ephemeral'])
        view=call.kwargs['view']
        self.assertEqual(view.battle.character,character_identity(card))
        await command.callback(interaction)
        store.start.assert_called_once()
        self.assertIn('今のバトル',interaction.followup.send.call_args.args[0])
        await view.on_timeout()
        self.assertFalse(view.active)
        view.stop()
        await client.close()

    async def test_buttons_owner_only_reward_failure_retry_and_stale_click(self):
        card=next(c for c in Gacha().pools['relink']['★3'] if c.character=='ロザリー')
        store=SimpleNamespace(finish=Mock(side_effect=[MemoryUnavailable('offline'),1]))
        active={}
        view=BattleView(SimpleNamespace(),store,active,7,1,card,0,1)
        active[7]=view
        other=self.interaction(); other.user.id=8
        self.assertFalse(await view.interaction_check(other))
        interaction=self.interaction()
        view.battle.enemy_hp=1
        await view.play(interaction,'attack')
        self.assertFalse(view.saved)
        self.assertEqual(view.children[0].label,'結果の保存を再試行')
        self.assertNotIn(7,active)
        await view.play(interaction,'retry')
        self.assertTrue(view.saved)
        self.assertEqual(view.battle.points,1)
        await view.play(interaction,'attack')
        self.assertEqual(store.finish.call_count,2)
        self.assertIn('ロザリーからの一言',[f.name for f in view.embed().fields])
        self.assertFalse(view.children)
        view.stop()
