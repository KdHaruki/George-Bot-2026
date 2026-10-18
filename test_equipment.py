import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, MagicMock, patch
import discord
from discord import app_commands
from equipment import ITEMS, roll_drop, register_equipment
from link_battle import Battle, BattleStore, BattleReward, BattleView, recovered_hp, migrate_equipment_schema

LOW=SimpleNamespace(randint=lambda low,high:low)

class EquipmentEffectTests(unittest.TestCase):
    def test_drop_boundaries_and_pools(self):
        for ticket,rare in ((0,True),(299,True),(300,False),(1999,False)):
            rng=SimpleNamespace(randrange=Mock(return_value=ticket),choice=Mock(side_effect=lambda pool:pool[0]))
            result=roll_drop(rng)
            pool=rng.choice.call_args.args[0]
            self.assertEqual(len(pool),7 if rare else 5)
            self.assertTrue(all(ITEMS[key].rare==rare for key in pool))
            self.assertEqual(ITEMS[result].rare,rare)
        for ticket in (2000,9999):
            rng=SimpleNamespace(randrange=lambda _:ticket,choice=Mock())
            self.assertIsNone(roll_drop(rng));rng.choice.assert_not_called()

    def test_immortal_works_once_and_not_after_enemy_defeat(self):
        state=Battle('test',hp=1,equipment_id='immortal')
        state.act('attack',LOW)
        self.assertEqual(state.hp,1);self.assertTrue(state.immortal_used)
        state.act('attack',LOW)
        self.assertEqual(state.result,'lost')
        state=Battle('test',hp=1,enemy_hp=1,equipment_id='immortal')
        state.act('attack',LOW)
        self.assertFalse(state.immortal_used)

    def test_miracle_does_not_revive_or_heal_after_winning(self):
        state=Battle('test',hp=50,equipment_id='miracle')
        state.act('attack',LOW);self.assertEqual(state.hp,45)
        dead=Battle('test',hp=1,equipment_id='miracle')
        dead.act('attack',LOW);self.assertEqual(dead.hp,0)
        winner=Battle('test',hp=50,enemy_hp=1,equipment_id='miracle')
        winner.act('attack',LOW);self.assertEqual(winner.hp,50)
        capped=Battle('test',hp=99,equipment_id='miracle',enemy_attack_percent=1)
        capped.act('attack',LOW);self.assertEqual(capped.hp,100)

    def test_resonance_allows_two_exceeds_and_no_third(self):
        state=Battle('test',equipment_id='resonance')
        self.assertTrue(state.act('exceed',LOW));self.assertTrue(state.can_exceed)
        self.assertTrue(state.act('exceed',LOW));self.assertFalse(state.can_exceed)
        snapshot=(state.hp,state.enemy_hp,state.turn)
        self.assertFalse(state.act('exceed',LOW));self.assertEqual((state.hp,state.enemy_hp,state.turn),snapshot)

    def test_counter_uses_maximum_hp_and_can_prevent_retaliation(self):
        state=Battle('test',turn=2,equipment_id='counter')
        maximum=state.enemy_max_hp;state.act('defend',LOW)
        self.assertEqual(state.enemy_hp,maximum-6-maximum*3//100)
        winner=Battle('test',turn=2,enemy_hp=8,equipment_id='counter')
        winner.act('defend',LOW);self.assertEqual(winner.result,'won');self.assertEqual(winner.hp,100)
        plain=Battle('test',equipment_id='counter');plain.act('defend',LOW)
        self.assertEqual(plain.enemy_hp,plain.enemy_max_hp-6)

    def test_rebellion_threshold_and_focus_attack_only(self):
        for hp,damage in ((30,19),(31,14)):
            state=Battle('test',hp=hp,equipment_id='rebellion');state.act('attack',LOW)
            self.assertEqual(state.enemy_max_hp-state.enemy_hp,damage)
        focus=Battle('test',equipment_id='focus');focus.act('attack',LOW)
        self.assertEqual(focus.enemy_max_hp-focus.enemy_hp,17)
        focus=Battle('test',equipment_id='focus');focus.act('defend',LOW)
        self.assertEqual(focus.enemy_max_hp-focus.enemy_hp,6)

    def test_normal_damage_defense_and_max_hp_effects(self):
        for item,action,damage,hp in [('power','attack',16,92),('skill','exceed',28,92),
                                      ('guard','attack',14,93),('wall','defend',6,99),('wall','attack',14,92)]:
            state=Battle('test',equipment_id=item);state.act(action,LOW)
            self.assertEqual(state.enemy_max_hp-state.enemy_hp,damage)
            self.assertEqual(state.hp,hp)
        state=Battle('test',equipment_id='vitality');self.assertEqual(state.max_hp,105)
        now=datetime.now(timezone.utc)
        self.assertEqual(recovered_hp(105,now,now,100)[0],100)
        wall=Battle('test',equipment_id='wall',enemy_attack_percent=1);wall.act('defend',LOW)
        self.assertEqual(wall.hp,99)

class EquipmentStoreTests(unittest.TestCase):
    def test_reward_and_drop_are_replayed_without_reroll_or_bonus_twice(self):
        for already_owned in (False,True):
            state={'active':True,'points':0,'owned':already_owned,'receipt':None,'hp_writes':0}
            def execute(sql,params=None):
                result=None
                if "SET result=%s" in sql:
                    if state['active']:state['active']=False;result=('bond',)
                elif 'INSERT INTO george_link_bonds' in sql:state['points']+=params[2]
                elif 'INSERT INTO george_link_items' in sql:
                    if not state['owned']:state['owned']=True;result=(params[1],)
                elif 'SET awarded_exp=' in sql:state['receipt']=params[:3]
                elif 'UPDATE george_link_vitality' in sql:state['hp_writes']+=1
                elif 'SELECT awarded_exp' in sql:result=state['receipt']
                elif 'SELECT points' in sql:result=(state['points'],)
                return SimpleNamespace(fetchone=lambda:result)
            connection=SimpleNamespace(execute=Mock(side_effect=execute));store=BattleStore('test')
            @contextmanager
            def connect():yield connection
            store.connect=connect
            with patch('link_battle.roll_drop',return_value='immortal') as drop:
                first=store.finish(1,7,'test','won',40,20)
                second=store.finish(1,7,'test','won',40,20)
            self.assertEqual(first,second);self.assertEqual(first.experience,55)
            self.assertEqual(first.points,55);self.assertEqual(first.item_id,'immortal')
            self.assertEqual(first.new_item,not already_owned)
            self.assertEqual(state['hp_writes'],1);drop.assert_called_once()

    def test_cannot_equip_while_active_or_equip_unowned(self):
        store=BattleStore('test');connection=MagicMock()
        @contextmanager
        def connect():yield connection
        store.connect=connect
        connection.execute.return_value.fetchone.return_value=(1,)
        with self.assertRaisesRegex(ValueError,'戦闘中'):store.equip(7,'power')
        connection.reset_mock();connection.execute.return_value.fetchone.side_effect=[None,None]
        with self.assertRaisesRegex(ValueError,'持っていない'):store.equip(7,'power')
        self.assertFalse(any('UPDATE george_link_equipment' in c.args[0] for c in connection.execute.call_args_list))

    def test_unequip_vitality_clamps_hp_without_free_healing(self):
        store=BattleStore('test');connection=MagicMock();now=datetime.now(timezone.utc)
        @contextmanager
        def connect():yield connection
        store.connect=connect
        connection.execute.return_value.fetchone.side_effect=[None,('vitality',)]
        connection.execute.return_value.fetchall.return_value=[('test',105,now,None,None)]
        store.equip(7,None)
        update=next(c for c in connection.execute.call_args_list if 'UPDATE george_link_vitality' in c.args[0])
        self.assertEqual(update.args[1][0],100)
        self.assertIn('DELETE FROM george_link_equipment',connection.execute.call_args.args[0])

    def test_equipment_schema_migration_does_not_repeat_ddl(self):
        for reads,expected in (([None,None],True),([(1,)],False),([None,(1,)],False)):
            connection=MagicMock();connection.execute.return_value.fetchone.side_effect=reads
            migrate_equipment_schema(connection)
            self.assertEqual(any('ALTER TABLE' in c.args[0] for c in connection.execute.call_args_list),expected)

class EquipmentCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_and_equip_use_only_invoking_user_and_are_private(self):
        client=discord.Client(intents=discord.Intents.none())
        store=SimpleNamespace(inventory=Mock(return_value=(['power','immortal'],'power')),equip=Mock())
        bot=SimpleNamespace(tree=app_commands.CommandTree(client),battle_store=store)
        register_equipment(bot)
        interaction=SimpleNamespace(user=SimpleNamespace(id=7),response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        command=bot.tree.get_command('装備')
        await command.callback(interaction)
        store.inventory.assert_called_with(7);store.equip.assert_not_called()
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        self.assertIn('力のお守り',interaction.followup.send.call_args.kwargs['embed'].description)
        await command.callback(interaction,'不死のお守り');store.equip.assert_called_once_with(7,'immortal')
        await command.callback(interaction,'解除');store.equip.assert_called_with(7,None)
        choices=await command._params['お守り'].autocomplete(interaction,'')
        self.assertEqual({c.value for c in choices},{'power','immortal','none'})
        store.equip.reset_mock()
        bot.battle_active={7:object()}
        await command.callback(interaction,'解除')
        store.equip.assert_not_called()
        self.assertIn('戦闘中',interaction.followup.send.call_args.args[0])
        await client.close()

    async def test_battle_equipment_is_fixed_and_drop_result_is_displayed(self):
        from gacha import Gacha
        card=next(c for c in Gacha().pools['relink']['★3'] if c.character=='ロザリー')
        store=SimpleNamespace(checkpoint=Mock(),finish=Mock(return_value=BattleReward(10,10,'immortal',True)))
        view=BattleView(SimpleNamespace(),store,{},7,1,card,0,1,equipment_id='resonance')
        interaction=SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),edit_original_response=AsyncMock())
        await view.play(interaction,'exceed')
        self.assertFalse(next(b for b in view.children if b.custom_id=='link:exceed').disabled)
        self.assertEqual(view.battle.equipment_id,'resonance')
        await view.play(interaction,'exceed')
        self.assertTrue(next(b for b in view.children if b.custom_id=='link:exceed').disabled)
        view.battle.enemy_hp=1
        await view.play(interaction,'attack')
        drop=next(f for f in view.embed().fields if f.name=='🎁 ドロップ')
        self.assertIn('不死のお守り',drop.value)
        self.assertIn('初入手',drop.value)
        self.assertIn('共鳴のお守り',view.embed().description)
        view.stop()
