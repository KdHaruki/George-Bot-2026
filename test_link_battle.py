import asyncio
import random
from contextlib import contextmanager
from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, MagicMock, patch
import discord
from discord import app_commands
from gacha import Gacha
from link_battle import Battle, BattleStore, BattleView, register_link_battle, character_identity, recovered_hp, level_progress, migrate_bond_experience, ENEMY_HP, ENEMY_EXP, ENEMY_NAMES, BattleReward
from registered_memory import MemoryUnavailable

class BattleTests(unittest.TestCase):
    def setUp(self):
        patcher=patch('link_battle.roll_drop',return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_actions_exceed_once_and_terminal_immutable(self):
        state = Battle('ロザリー')
        self.assertEqual(state.hp, 100)
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
        stronger = Battle('ロザリー',points=100000)
        self.assertEqual(stronger.level,100)
        cap = sum(50 + 10*((level - 1)//5) for level in range(1,100))
        self.assertEqual(Battle('ロザリー', points=cap-1).level, 99)
        self.assertEqual(Battle('ロザリー', points=cap).level, 100)
        self.assertEqual(level_progress(250), (6,60))
        self.assertEqual(level_progress(550), (11,70))
        stronger.act('attack',rng)
        self.assertLess(stronger.enemy_hp,90-20)
        losing = Battle('ロザリー',hp=1)
        losing.act('defend',rng)
        self.assertEqual(losing.result,'lost')

    def test_golem_strength_matches_bond_level_with_guarded_heavy_attacks(self):
        def points_for(level):
            return sum(50+10*((n-1)//5) for n in range(1,level))
        def win_rate(player_level,golem_level,guard=True):
            wins=0
            for seed in range(500):
                rng=random.Random(seed)
                state=Battle.spawn('ロザリー',points_for(player_level),enemy_level=golem_level,rng=rng)
                for _ in range(60):
                    action='defend' if guard and (state.turn+1)%3==0 else 'attack' if state.exceed_used else 'exceed'
                    state.act(action,rng)
                    if state.result!='active':
                        break
                self.assertNotEqual(state.result,'active')
                wins+=state.result=='won'
            return wins/500
        for level in ENEMY_HP:
            rate=win_rate(level,level)
            self.assertGreaterEqual(rate,0.80)
            self.assertGreater(rate,win_rate(level,level,False)+0.35)
        for level in (10,20):
            self.assertLess(win_rate(level-5,level),win_rate(level,level)-0.15)
            self.assertGreater(win_rate(level+5,level),0.90)
        with self.assertRaises(ValueError):
            Battle('ロザリー',enemy_level=2)

    def test_individual_stats_roll_once_and_affect_damage(self):
        roller=Mock()
        roller.randint.side_effect=[85,115,85]
        individual=Battle.spawn('ロザリー',rng=roller)
        self.assertEqual(roller.randint.call_count,3)
        self.assertEqual(individual.enemy_hp_percent,85)
        self.assertEqual(individual.enemy_attack_percent,115)
        self.assertEqual(individual.enemy_defense_percent,85)
        self.assertEqual(individual.enemy_hp,(ENEMY_HP[1]*85+50)//100)
        neutral=Battle('ロザリー')
        rng=SimpleNamespace(randint=lambda low,high:low)
        before=individual.enemy_hp
        individual.act('attack',rng)
        neutral.act('attack',rng)
        self.assertGreater(before-individual.enemy_hp,ENEMY_HP[1]-neutral.enemy_hp)
        self.assertLess(individual.hp,neutral.hp)
        individual.act('defend',rng)
        self.assertEqual((individual.enemy_hp_percent,individual.enemy_attack_percent,individual.enemy_defense_percent),(85,115,85))
        self.assertEqual(roller.randint.call_count,3)
        armored=Battle('ロザリー',enemy_defense_percent=115)
        armored.act('attack',rng)
        self.assertLess(ENEMY_HP[1]-armored.enemy_hp,ENEMY_HP[1]-neutral.enemy_hp)

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
            conn.execute.return_value.fetchone.side_effect = [(None,),(10,)] if first else [None,(10,None,False),(10,)]
            self.assertEqual(store.finish(1,7,'ロザリー','won',70).points,10)
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
        conn.execute.return_value.fetchone.side_effect = [(100,datetime.now(timezone.utc),None,None),None,None,None]
        with self.assertRaises(ValueError):
            store.start(1,7,"quote'",date(2026,10,18))
        self.assertFalse(any('INSERT INTO george_link_battles' in call.args[0] for call in conn.execute.call_args_list))
        self.assertEqual(conn.execute.call_args.args[1],(7,date(2026,10,18),3))

    def test_experience_reward_depends_on_golem_and_no_reward_on_loss(self):
        store=BattleStore('test'); conn=MagicMock()
        @contextmanager
        def connect():
            yield conn
        store.connect=connect
        for level,exp in ENEMY_EXP.items():
            conn.reset_mock()
            conn.execute.return_value.fetchone.side_effect=[(1,),(exp,)]
            self.assertEqual(store.finish(1,7,'ロザリー','won',80,level).points,exp)
            insert=next(c for c in conn.execute.call_args_list if 'INSERT INTO george_link_bonds' in c.args[0])
            self.assertEqual(insert.args[1],(7,'ロザリー',exp))
        conn.reset_mock()
        conn.execute.return_value.fetchone.side_effect=[(1,),(50,)]
        store.finish(1,7,'ロザリー','lost',0,20)
        self.assertFalse(any('INSERT INTO george_link_bonds' in c.args[0] for c in conn.execute.call_args_list))
        self.assertEqual(level_progress(49),(1,1))
        self.assertEqual(level_progress(50),(2,50))
        self.assertEqual(level_progress(80),(2,20))

    def test_existing_wins_migrate_once_and_concurrent_recheck_skips(self):
        for reads,converted in (([None,None],True),([(1,)],False),([None,(1,)],False)):
            conn=MagicMock()
            conn.execute.return_value.fetchone.side_effect=reads
            migrate_bond_experience(conn)
            updates=[c for c in conn.execute.call_args_list if 'SET points=points*10' in c.args[0]]
            self.assertEqual(bool(updates),converted)
        for wins in (0,1,24,25,55,500):
            remaining=wins; old_level=1
            while old_level<100:
                cost=5+(old_level-1)//5
                if remaining<cost: break
                remaining-=cost; old_level+=1
            self.assertEqual(level_progress(wins*10)[0],old_level)

    def test_healing_preserves_partial_ticks_and_caps_at_100(self):
        base=datetime(2026,10,18,tzinfo=timezone.utc)
        self.assertEqual(recovered_hp(40,base,base+timedelta(seconds=179)),(40,base))
        self.assertEqual(recovered_hp(40,base,base+timedelta(seconds=181)),(41,base+timedelta(seconds=180)))
        hp,anchor=recovered_hp(40,base,base+timedelta(seconds=181))
        self.assertEqual(recovered_hp(hp,anchor,base+timedelta(seconds=360))[0],42)
        later=base+timedelta(hours=10)
        self.assertEqual(recovered_hp(0,base,later),(100,later))
        self.assertEqual(recovered_hp(0,base,base+timedelta(seconds=180))[0],1)
        self.assertEqual(recovered_hp(30,base,base-timedelta(seconds=10))[0],30)

    def test_start_returns_recovered_hp_and_marks_active_without_polls(self):
        store=BattleStore('test'); conn=MagicMock()
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        @contextmanager
        def connect():
            yield conn
        store.connect=connect
        conn.execute.return_value.fetchone.side_effect=[(40,now-timedelta(seconds=370),None,None),None,None,(2,),(25,)]
        with patch('link_battle.datetime') as clock:
            clock.now.return_value=now
            self.assertEqual(store.start(1,7,'ロザリー',date(2026,10,18)),(25,2,42,None))
        update=next(c for c in conn.execute.call_args_list if 'UPDATE george_link_vitality SET hp=' in c.args[0])
        self.assertEqual(update.args[1],(42,now,1,now+timedelta(minutes=5),7,'ロザリー'))

    def test_unexpired_battle_lease_blocks_a_second_start(self):
        store=BattleStore('test'); conn=MagicMock()
        now=datetime.now(timezone.utc)
        @contextmanager
        def connect():
            yield conn
        store.connect=connect
        conn.execute.return_value.fetchone.return_value=(40,now,123,now+timedelta(minutes=3))
        with self.assertRaisesRegex(ValueError,'進行中'):
            store.start(1,7,'ロザリー',now.date())
        self.assertFalse(any('INSERT INTO george_link_daily' in c.args[0] for c in conn.execute.call_args_list))

    def test_low_hp_cannot_start_or_consume_daily_attempt(self):
        store=BattleStore('test'); conn=MagicMock()
        @contextmanager
        def connect():
            yield conn
        store.connect=connect
        conn.execute.return_value.fetchone.return_value=(0,datetime.now(timezone.utc),None,None)
        with self.assertRaisesRegex(ValueError,'HPが0'):
            store.start(1,7,'ロザリー',date(2026,10,18))
        self.assertFalse(any('INSERT INTO george_link_daily' in c.args[0] for c in conn.execute.call_args_list))

class BattleCommandTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self):
        return SimpleNamespace(id=1,user=SimpleNamespace(id=7),response=SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def test_requires_favorite_and_starts_private_then_blocks_parallel(self):
        client = discord.Client(intents=discord.Intents.none())
        card = Gacha().pools['relink']['★3'][0]
        favorites = Mock(return_value=None)
        bot = SimpleNamespace(tree=app_commands.CommandTree(client), collection_store=SimpleNamespace(favorite=favorites))
        store = SimpleNamespace(start=Mock(return_value=(0,1,100,None)), finish=Mock(return_value=BattleReward(1,10)))
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
        store=SimpleNamespace(finish=Mock(side_effect=[MemoryUnavailable('offline'),BattleReward(1,10)]))
        active={}
        view=BattleView(SimpleNamespace(),store,active,7,1,card,0,1)
        active[7]=view
        other=self.interaction(); other.user.id=8
        self.assertFalse(await view.interaction_check(other))
        interaction=self.interaction()
        view.battle.enemy_hp=1
        await view.play(interaction,'attack')
        self.assertFalse(view.saved)
        self.assertEqual(view.children[0].label,'保存を再試行')
        self.assertNotIn(7,active)
        await view.play(interaction,'retry')
        self.assertTrue(view.saved)
        self.assertEqual(view.battle.points,1)
        await view.play(interaction,'attack')
        self.assertEqual(store.finish.call_count,2)
        self.assertIn('ロザリーからの一言',[f.name for f in view.embed().fields])
        self.assertFalse(view.children)
        view.stop()

    async def test_midbattle_hp_retry_does_not_repeat_the_action(self):
        card=Gacha().pools['relink']['★3'][0]
        store=SimpleNamespace(checkpoint=Mock(side_effect=[MemoryUnavailable('offline'),None]), finish=Mock(return_value=BattleReward(0)))
        view=BattleView(SimpleNamespace(),store,{},7,1,card,0,1,hp=47)
        interaction=self.interaction()
        await view.play(interaction,'attack')
        self.assertTrue(view.pending_checkpoint)
        hp,turn=view.battle.hp,view.battle.turn
        await view.play(interaction,'retry')
        self.assertEqual((view.battle.hp,view.battle.turn),(hp,turn))
        self.assertFalse(view.pending_checkpoint)
        self.assertEqual(len(view.children),3)
        self.assertEqual(store.checkpoint.call_args_list[0],store.checkpoint.call_args_list[1])
        await view.on_timeout()
        store.finish.assert_called_once_with(1,7,view.battle.character,'abandoned',hp)
        view.stop()

    async def test_golem_choice_is_used_and_invalid_choice_does_not_consume_attempt(self):
        client=discord.Client(intents=discord.Intents.none())
        card=Gacha().pools['relink']['★3'][0]
        bot=SimpleNamespace(tree=app_commands.CommandTree(client),collection_store=SimpleNamespace(favorite=Mock(return_value=('relink',card,1))))
        store=SimpleNamespace(start=Mock(return_value=(55,1,100,None)),finish=Mock(return_value=BattleReward(55)))
        register_link_battle(bot,store)
        command=bot.tree.get_command('エクシーズバトル')
        self.assertEqual(command.parameters[0].name,'敵')
        self.assertEqual([choice.value for choice in command.parameters[0].choices],[1,5,10,15,20,30,50])
        self.assertIn('リグレスLv50',command.parameters[0].choices[-1].name)
        interaction=self.interaction()
        await command.callback(interaction,2)
        store.start.assert_not_called()
        for level,max_hp in ENEMY_HP.items():
            await command.callback(interaction,level)
            view=interaction.followup.send.call_args.kwargs['view']
            self.assertEqual(view.battle.enemy_level,level)
            field=view.embed().fields[1]
            self.assertEqual(field.name,f'{ENEMY_NAMES[level]} Lv.{level}')
            self.assertIn(f'HP {view.battle.enemy_max_hp}/{view.battle.enemy_max_hp}',field.value)
            self.assertGreaterEqual(view.battle.enemy_max_hp,round(max_hp*.85)-1)
            self.assertLessEqual(view.battle.enemy_max_hp,round(max_hp*1.15)+1)
            self.assertIn('個体差：',field.value)
            self.assertIn(f'適正：絆Lv.{level}',field.value)
            await view.on_timeout()
            view.stop()
        await client.close()

    async def test_view_saves_selected_golem_reward_and_displays_exp(self):
        card=next(c for c in Gacha().pools['relink']['★3'] if c.character=='ロザリー')
        for level,reward in ENEMY_EXP.items():
            store=SimpleNamespace(finish=Mock(return_value=BattleReward(reward,reward)))
            view=BattleView(SimpleNamespace(),store,{},7,1,card,0,1,enemy_level=level)
            view.battle.enemy_hp=1
            await view.play(self.interaction(),'attack')
            self.assertEqual(store.finish.call_args.args[-1],level)
            self.assertIn(f'＋{reward}EXP',view.battle.last)
            self.assertIn(f'絆経験値 {reward}EXP',view.embed().description)
            self.assertNotIn('あと5勝',view.embed().description)
            view.stop()
