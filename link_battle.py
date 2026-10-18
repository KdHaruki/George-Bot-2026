"""Private, turn-based training battles with an owner's favorite Progress."""
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import logging
import random

import discord
from discord import app_commands

from registered_memory import MemoryStore, MemoryUnavailable
from progress import progressData
from gacha_commands import favorite_details
from gacha import Gacha
from relink_presentations import PRESENTATIONS

JST = timezone(timedelta(hours=9))
DAILY_LIMIT = 3


def character_identity(card):
    aliases = {'ユフィ': 'コードΩ00ユーフィリア', '葵': '御影葵', '空': '久遠空', '遥': '東条遥'}
    if card.character in aliases:
        return aliases[card.character]
    matches = [p['progressName'] for p in progressData if card.character == p['progressName']]
    if not matches:
        matches = [p['progressName'] for p in progressData if len(card.character) >= 2 and card.character in p['progressName']]
    return matches[0] if len(matches) == 1 else card.character


@dataclass
class Battle:
    character: str
    points: int = 0
    hp: int = 65
    enemy_hp: int = 90
    turn: int = 0
    exceed_used: bool = False
    last: str = 'お気に入りとリンク完了！ 行動を選んでくれ。'

    @property
    def level(self):
        return 1 + min(self.points // 5, 5)

    @property
    def result(self):
        return 'won' if self.enemy_hp <= 0 else 'lost' if self.hp <= 0 else 'active'

    def act(self, action, rng=None):
        if self.result != 'active':
            return False
        rng = rng or random.SystemRandom()
        if action not in ('attack', 'defend', 'exceed') or (action == 'exceed' and self.exceed_used):
            return False
        bonus = self.level - 1
        if action == 'exceed':
            self.exceed_used = True
            damage, received = rng.randint(25, 32) + bonus, rng.randint(8, 13)
            label = 'エクシード発動！'
        elif action == 'defend':
            damage, received = rng.randint(6, 10) + bonus, rng.randint(3, 6)
            label = '守りを固めて反撃！'
        else:
            damage, received = rng.randint(14, 20) + bonus, rng.randint(8, 13)
            label = '連携攻撃！'
        self.turn += 1
        if self.turn % 3 == 0 and action != 'defend':
            received = rng.randint(20, 27)
        self.enemy_hp = max(0, self.enemy_hp - damage)
        received = received if self.enemy_hp else 0
        self.hp = max(0, self.hp - received)
        self.last = f'{label} {damage}ダメージ！\n' + (f'相手の反撃で{received}ダメージ。' if received else '相手を撃破！')
        return True


class BattleStore(MemoryStore):
    @contextmanager
    def connect(self):
        if not self.url:
            raise MemoryUnavailable('エクシーズバトルにはDATABASE_URLの設定が必要だぜ。')
        try:
            import psycopg
            with psycopg.connect(self.url, connect_timeout=10) as connection:
                connection.execute("SET LOCAL statement_timeout = '10s'")
                connection.execute('''CREATE TABLE IF NOT EXISTS george_link_bonds (
                    user_id BIGINT NOT NULL, character TEXT NOT NULL, points BIGINT NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id,character))''')
                connection.execute('''CREATE TABLE IF NOT EXISTS george_link_daily (
                    user_id BIGINT NOT NULL, day DATE NOT NULL, attempts INTEGER NOT NULL,
                    PRIMARY KEY(user_id,day))''')
                connection.execute('''CREATE TABLE IF NOT EXISTS george_link_battles (
                    battle_id BIGINT PRIMARY KEY, user_id BIGINT NOT NULL, character TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
                yield connection
        except (MemoryUnavailable, ValueError):
            raise
        except Exception:
            raise MemoryUnavailable('バトルの保存先を利用できなかったぜ。') from None

    def start(self, battle_id, user_id, character, day):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            previous = connection.execute('SELECT battle_id FROM george_link_battles WHERE battle_id=%s', (battle_id,)).fetchone()
            if previous:
                raise ValueError('このバトルは受付済みだぜ。')
            row = connection.execute('''INSERT INTO george_link_daily VALUES (%s,%s,1)
                ON CONFLICT(user_id,day) DO UPDATE SET attempts=george_link_daily.attempts+1
                WHERE george_link_daily.attempts < %s RETURNING attempts''', (user_id, day, DAILY_LIMIT)).fetchone()
            if not row:
                raise ValueError('今日のバトルは3回終了だぜ！ 日本時間の午前0時に回数が戻るぞ。')
            connection.execute('INSERT INTO george_link_battles(battle_id,user_id,character) VALUES (%s,%s,%s)', (battle_id, user_id, character))
            points = connection.execute('SELECT points FROM george_link_bonds WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
            connection.execute("DELETE FROM george_link_daily WHERE day < %s::date - 30", (day,))
            connection.execute("DELETE FROM george_link_battles WHERE created_at < now() - interval '30 days'")
            return (points[0] if points else 0), row[0]

    def finish(self, battle_id, user_id, character, result):
        if result not in ('won', 'lost'):
            raise ValueError('Invalid battle result')
        with self.connect() as connection:
            # Only the first transition can award points, even after a network retry.
            row = connection.execute('''UPDATE george_link_battles SET result=%s
                WHERE battle_id=%s AND user_id=%s AND character=%s AND result='active' RETURNING battle_id''',
                                     (result, battle_id, user_id, character)).fetchone()
            if row and result == 'won':
                connection.execute('''INSERT INTO george_link_bonds VALUES (%s,%s,1)
                    ON CONFLICT(user_id,character) DO UPDATE SET points=george_link_bonds.points+1''', (user_id, character))
            points = connection.execute('SELECT points FROM george_link_bonds WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
            return points[0] if points else 0


class BattleView(discord.ui.View):
    def __init__(self, bot, store, active, user_id, battle_id, card, points, attempt):
        super().__init__(timeout=300)
        self.bot, self.store, self.active = bot, store, active
        self.user_id, self.battle_id, self.card = user_id, battle_id, card
        self.battle = Battle(character_identity(card), points)
        self.attempt, self.lock, self.message = attempt, asyncio.Lock(), None
        self.saved, self.george_line, self.character_line = False, '', ''
        for action, label, style in [('attack', '攻撃', discord.ButtonStyle.primary),
                                     ('defend', '防御', discord.ButtonStyle.secondary),
                                     ('exceed', 'エクシード', discord.ButtonStyle.danger)]:
            button = discord.ui.Button(label=label, style=style, custom_id='link:' + action)
            async def callback(interaction, selected=action):
                await self.play(interaction, selected)
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message('このバトルは始めた本人だけが操作できるぜ。', ephemeral=True)
        return False

    def release(self):
        if self.active.get(self.user_id) is self:
            self.active.pop(self.user_id, None)

    def embed(self):
        state = self.battle
        title = 'エクシーズバトル' if state.result == 'active' else 'エクシーズバトル｜勝利！' if state.result == 'won' else 'エクシーズバトル｜敗北'
        embed = discord.Embed(title=title, description=f'**{discord.utils.escape_markdown(state.character)}とリンク**\n絆Lv.{state.level}｜絆ポイント {state.points}\n本日 {self.attempt}/{DAILY_LIMIT}回目', color=0xB06FE0)
        embed.add_field(name='リンク側', value=f'HP {state.hp}/65', inline=True)
        enemy = f'HP {state.enemy_hp}/90'
        if state.result == 'active':
            enemy += '\n次は強攻撃！ 防御で軽減できるぜ。' if (state.turn + 1) % 3 == 0 else '\n次は通常攻撃'
        embed.add_field(name='模擬戦用ゴーレム', value=enemy, inline=True)
        embed.add_field(name=f'ターン {state.turn}', value=state.last, inline=False)
        if self.george_line:
            embed.add_field(name='ジョージの一言', value=discord.utils.escape_markdown(self.george_line), inline=False)
        if self.character_line:
            embed.add_field(name=f'{state.character}からの一言', value=discord.utils.escape_markdown(self.character_line), inline=False)
        embed.set_footer(text='Botオリジナルの模擬戦｜エクシードは1戦1回｜5分操作がないと終了')
        return embed

    async def remarks(self):
        won = self.battle.result == 'won'
        self.george_line = 'いい連携だったぜ！ お疲れさん！' if won else '今回は相手が一枚上だったな。次に向けてひと息つこうぜ！'
        chat = getattr(self.bot, 'george_chat', None)
        introduction = favorite_details(self.card)[0]
        candidates = Gacha().pools['relink']['★3']
        art = self.card if self.card.id in PRESENTATIONS else next(
            (card for card in candidates if character_identity(card) == self.battle.character and card.id in PRESENTATIONS), None)
        self.character_line = PRESENTATIONS[art.id]['quote'] if art else ''
        if chat is None:
            return
        try:
            self.george_line = await asyncio.wait_for(chat.collection_comment(dict(action='battle_result', character=self.battle.character,
                                                                                  result='勝利' if won else '敗北', profile=introduction)), timeout=12)
        except Exception as exc:
            logging.warning('Battle comment fallback: type=%s', type(exc).__name__)
        if not self.character_line:
            try:
                self.character_line = await asyncio.wait_for(chat.collection_comment(dict(action='character_line', character=self.battle.character,
                                                                                          profile=introduction, result='模擬戦の勝利' if won else '模擬戦の敗北')), timeout=12)
            except Exception as exc:
                logging.warning('Battle character line skipped: type=%s', type(exc).__name__)

    async def play(self, interaction, action):
        await interaction.response.defer()
        async with self.lock:
            if action == 'retry':
                if self.saved or self.battle.result == 'active':
                    return
            elif not self.battle.act(action):
                return
            for button in self.children:
                button.disabled = self.battle.result != 'active' or (button.custom_id == 'link:exceed' and self.battle.exceed_used)
            if self.battle.result != 'active':
                self.release()
                try:
                    self.battle.points = await asyncio.to_thread(self.store.finish, self.battle_id, self.user_id, self.battle.character, self.battle.result)
                    self.saved = True
                    self.battle.last += '\n絆ポイント＋1！' if self.battle.result == 'won' else '\n絆ポイントの変動なし。'
                    self.clear_items()
                except MemoryUnavailable:
                    self.clear_items()
                    retry = discord.ui.Button(label='結果の保存を再試行', style=discord.ButtonStyle.secondary)
                    async def callback(interaction):
                        await self.play(interaction, 'retry')
                    retry.callback = callback
                    self.add_item(retry)
                    await interaction.edit_original_response(embed=self.embed(), view=self)
                    await interaction.followup.send('結果を保存できなかったぜ。再試行ボタンを押してくれ。', ephemeral=True)
                    return
                if not self.george_line:
                    await self.remarks()
            await interaction.edit_original_response(embed=self.embed(), view=self)
            if self.saved:
                self.stop()

    async def on_timeout(self):
        async with self.lock:
            self.release()
            for button in self.children:
                button.disabled = True
            if self.battle.result == 'active':
                self.battle.last = '時間切れでリンク解除。絆ポイントは変わらないぜ。'
            if self.message:
                try:
                    await self.message.edit(embed=self.embed(), view=self)
                except discord.HTTPException:
                    pass


def register_link_battle(bot, store=None):
    store = store if store is not None else BattleStore()
    active = {}

    @bot.tree.command(name='エクシーズバトル', description='お気に入りとリンクして模擬戦に挑む（1日3回）')
    async def battle_command(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id in active:
            await interaction.followup.send('今のバトルが終わってから挑戦してくれ！', ephemeral=True)
            return
        active[interaction.user.id] = None
        try:
            favorite = await asyncio.to_thread(bot.collection_store.favorite, interaction.user.id)
            if favorite is None:
                await interaction.followup.send('先に `/お気に入り` でプログレスを登録してくれ！', ephemeral=True)
                return
            _, card, _ = favorite
            points, attempt = await asyncio.to_thread(store.start, interaction.id, interaction.user.id, character_identity(card), datetime.now(JST).date())
            view = BattleView(bot, store, active, interaction.user.id, interaction.id, card, points, attempt)
            active[interaction.user.id] = view
            try:
                view.message = await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True, wait=True,
                                                               allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                view.release()
                view.stop()
                raise
        except (MemoryUnavailable, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        finally:
            if active.get(interaction.user.id) is None:
                active.pop(interaction.user.id, None)
