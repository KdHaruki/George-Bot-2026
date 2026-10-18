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
from relink_presentations import PRESENTATIONS
from equipment import ITEMS, roll_drop, max_hp

JST = timezone(timedelta(hours=9))
DAILY_LIMIT = 3
PLAYER_MAX_HP = 100
HEAL_SECONDS = 180
ENEMY_NAMES = {1: '訓練用ゴーレム', 5: '訓練用ゴーレム', 10: '訓練用ゴーレム',
               15: 'ファントム', 20: 'フルフェイス', 30: 'ウロボロス', 50: 'リグレス'}
ENEMY_HP = {1: 153, 5: 191, 10: 219, 15: 270, 20: 288, 30: 335, 50: 418}
ENEMY_EXP = {1: 10, 5: 20, 10: 30, 15: 40, 20: 50, 30: 75, 50: 130}
ENEMY_VARIATION = 15


def migrate_bond_experience(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS george_link_migrations (name TEXT PRIMARY KEY)')
    key = 'bond-experience-v1'
    query = 'SELECT 1 FROM george_link_migrations WHERE name=%s'
    if connection.execute(query, (key,)).fetchone():
        return
    connection.execute("SELECT pg_advisory_xact_lock(hashtext('george-link-experience-v1'))")
    if connection.execute(query, (key,)).fetchone():
        return
    connection.execute('UPDATE george_link_bonds SET points=points*10')
    connection.execute('INSERT INTO george_link_migrations(name) VALUES (%s)', (key,))


def migrate_equipment_schema(connection):
    key = 'equipment-v1'
    query = 'SELECT 1 FROM george_link_migrations WHERE name=%s'
    if connection.execute(query, (key,)).fetchone():
        return
    connection.execute("SELECT pg_advisory_xact_lock(hashtext('george-link-equipment-v1'))")
    if connection.execute(query, (key,)).fetchone():
        return
    connection.execute('''ALTER TABLE george_link_battles
        ADD COLUMN IF NOT EXISTS equipment_id TEXT,
        ADD COLUMN IF NOT EXISTS awarded_exp BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS dropped_item TEXT,
        ADD COLUMN IF NOT EXISTS drop_new BOOLEAN NOT NULL DEFAULT FALSE''')
    connection.execute('INSERT INTO george_link_migrations(name) VALUES (%s)', (key,))


def level_progress(points):
    level, remaining = 1, max(0, points)
    while level < 100:
        needed = 50 + 10 * ((level - 1) // 5)
        if remaining < needed:
            return level, needed - remaining
        remaining -= needed
        level += 1
    return 100, 0


def recovered_hp(hp, heal_at, now, maximum=PLAYER_MAX_HP):
    elapsed = max(0, int((now - heal_at).total_seconds()))
    ticks = elapsed // HEAL_SECONDS
    hp = min(maximum, max(0, hp) + ticks)
    # Preserve incomplete recovery ticks unless HP has reached its cap.
    return hp, now if hp == maximum else heal_at + timedelta(seconds=ticks * HEAL_SECONDS)


@dataclass(frozen=True)
class BattleReward:
    points: int
    experience: int = 0
    item_id: str | None = None
    new_item: bool = False


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
    hp: int = PLAYER_MAX_HP
    enemy_hp: int | None = None
    turn: int = 0
    exceed_used: bool = False
    last: str = 'プログレスとリンク完了！ 行動を選んでくれ。'
    enemy_level: int = 1
    enemy_hp_percent: int = 100
    enemy_attack_percent: int = 100
    enemy_defense_percent: int = 100
    equipment_id: str | None = None
    exceed_uses: int = 0
    immortal_used: bool = False

    @classmethod
    def spawn(cls, character, points=0, hp=PLAYER_MAX_HP, enemy_level=1, rng=None, equipment_id=None):
        rng = rng or random.SystemRandom()
        rolls = [rng.randint(100 - ENEMY_VARIATION, 100 + ENEMY_VARIATION) for _ in range(3)]
        return cls(character, points, hp=hp, enemy_level=enemy_level,
                   enemy_hp_percent=rolls[0], enemy_attack_percent=rolls[1], enemy_defense_percent=rolls[2], equipment_id=equipment_id)

    def __post_init__(self):
        if self.enemy_level not in ENEMY_HP:
            raise ValueError('候補から戦う敵を選んでくれ！')
        if self.enemy_hp is None:
            self.enemy_hp = self.enemy_max_hp

    @property
    def enemy_max_hp(self):
        return max(1, (ENEMY_HP[self.enemy_level] * self.enemy_hp_percent + 50) // 100)

    @property
    def level(self):
        return level_progress(self.points)[0]

    @property
    def max_hp(self):
        return max_hp(self.equipment_id)

    @property
    def can_exceed(self):
        return self.exceed_uses < (2 if self.equipment_id == 'resonance' else 1)

    @property
    def result(self):
        return 'won' if self.enemy_hp <= 0 else 'lost' if self.hp <= 0 else 'active'

    def act(self, action, rng=None):
        if self.result != 'active':
            return False
        rng = rng or random.SystemRandom()
        if action not in ('attack', 'defend', 'exceed') or (action == 'exceed' and not self.can_exceed):
            return False
        bonus = self.level - 1
        if action == 'exceed':
            self.exceed_used = True
            self.exceed_uses += 1
            damage, received = rng.randint(25, 32) + bonus, rng.randint(8, 13)
            label = 'エクシード発動！'
        elif action == 'defend':
            damage, received = rng.randint(6, 10) + bonus, rng.randint(3, 6)
            label = '守りを固めて反撃！'
        else:
            damage, received = rng.randint(17 if self.equipment_id == 'focus' else 14, 20) + bonus, rng.randint(8, 13)
            label = '連携攻撃！'
        received += self.enemy_level // 10
        self.turn += 1
        if self.turn % 3 == 0 and action != 'defend':
            received = rng.randint(20, 27) + 2 * (self.enemy_level // 10)
        damage = max(1, (damage * 100 + self.enemy_defense_percent // 2) // self.enemy_defense_percent)
        received = max(1, (received * self.enemy_attack_percent + 50) // 100)
        effects = []
        if self.equipment_id == 'power' and action == 'attack':
            damage += 2
        elif self.equipment_id == 'skill' and action == 'exceed':
            damage += 3
        elif self.equipment_id == 'rebellion' and self.hp <= 30:
            damage += 5
        elif self.equipment_id == 'counter' and action == 'defend' and self.turn % 3 == 0:
            extra = max(1, self.enemy_max_hp * 3 // 100)
            damage += extra
            effects.append(f'反撃のお守り：追加{extra}ダメージ！')
        if self.equipment_id == 'guard':
            received = max(1, received - 1)
        elif self.equipment_id == 'wall' and action == 'defend':
            received = max(1, received - 2)
        self.enemy_hp = max(0, self.enemy_hp - damage)
        received = received if self.enemy_hp else 0
        self.hp = max(0, self.hp - received)
        if self.hp == 0 and self.equipment_id == 'immortal' and not self.immortal_used:
            self.hp = 1
            self.immortal_used = True
            effects.append('不死のお守り：HP1で耐えた！')
        if self.hp > 0 and self.enemy_hp > 0 and self.equipment_id == 'miracle':
            heal = min(self.max_hp - self.hp, self.max_hp * 3 // 100)
            self.hp += heal
            if heal:
                effects.append(f'奇跡のお守り：HP{heal}回復！')
        self.last = f'{label} {damage}ダメージ！\n' + (f'相手の反撃で{received}ダメージ。' if received else '相手を撃破！')
        if effects:
            self.last += '\n' + '\n'.join(effects)
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
                connection.execute('''CREATE TABLE IF NOT EXISTS george_link_vitality (
                    user_id BIGINT NOT NULL, character TEXT NOT NULL, hp INTEGER NOT NULL DEFAULT 100,
                    heal_at TIMESTAMPTZ NOT NULL DEFAULT now(), battle_id BIGINT,
                    active_until TIMESTAMPTZ, last_turn INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id,character))''')
                connection.execute('''CREATE TABLE IF NOT EXISTS george_link_items (
                    user_id BIGINT NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY(user_id,item_id))''')
                connection.execute('''CREATE TABLE IF NOT EXISTS george_link_equipment (
                    user_id BIGINT PRIMARY KEY, item_id TEXT NOT NULL,
                    FOREIGN KEY(user_id,item_id) REFERENCES george_link_items(user_id,item_id))''')
                migrate_bond_experience(connection)
                migrate_equipment_schema(connection)
                yield connection
        except (MemoryUnavailable, ValueError):
            raise
        except Exception:
            raise MemoryUnavailable('バトルの保存先を利用できなかったぜ。') from None

    def start(self, battle_id, user_id, character, day):
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            now = datetime.now(timezone.utc)
            connection.execute('''INSERT INTO george_link_vitality(user_id,character) VALUES (%s,%s)
                ON CONFLICT(user_id,character) DO NOTHING''', (user_id, character))
            hp, heal_at, previous_battle, active_until = connection.execute('''SELECT hp,heal_at,battle_id,active_until
                FROM george_link_vitality WHERE user_id=%s AND character=%s FOR UPDATE''', (user_id, character)).fetchone()
            equipped = connection.execute('SELECT item_id FROM george_link_equipment WHERE user_id=%s', (user_id,)).fetchone()
            item_id = equipped[0] if equipped else None
            if previous_battle and active_until and active_until > now:
                raise ValueError('前のバトルが進行中だぜ。中断した場合は5分ほど待ってくれ。')
            if previous_battle:
                connection.execute("UPDATE george_link_battles SET result='abandoned' WHERE battle_id=%s AND result='active'", (previous_battle,))
            hp, heal_at = recovered_hp(hp, max(heal_at, active_until) if previous_battle and active_until else heal_at, now, max_hp(item_id))
            if hp == 0:
                seconds = max(1, HEAL_SECONDS - max(0, int((now - heal_at).total_seconds())))
                raise ValueError(f'HPが0だぜ。あと約{seconds}秒でHPが1回復するから、休んでから挑戦してくれ。')
            previous = connection.execute('SELECT battle_id FROM george_link_battles WHERE battle_id=%s', (battle_id,)).fetchone()
            if previous:
                raise ValueError('このバトルは受付済みだぜ。')
            row = connection.execute('''INSERT INTO george_link_daily VALUES (%s,%s,1)
                ON CONFLICT(user_id,day) DO UPDATE SET attempts=george_link_daily.attempts+1
                WHERE george_link_daily.attempts < %s RETURNING attempts''', (user_id, day, DAILY_LIMIT)).fetchone()
            if not row:
                raise ValueError('今日のバトルは3回終了だぜ！ 日本時間の午前0時に回数が戻るぞ。')
            connection.execute('INSERT INTO george_link_battles(battle_id,user_id,character,equipment_id) VALUES (%s,%s,%s,%s)', (battle_id, user_id, character, item_id))
            connection.execute('''UPDATE george_link_vitality SET hp=%s,heal_at=%s,battle_id=%s,
                active_until=%s,last_turn=0 WHERE user_id=%s AND character=%s''',
                               (hp, now, battle_id, now + timedelta(minutes=5), user_id, character))
            points = connection.execute('SELECT points FROM george_link_bonds WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
            connection.execute("DELETE FROM george_link_daily WHERE day < %s::date - 30", (day,))
            connection.execute("DELETE FROM george_link_battles WHERE created_at < now() - interval '30 days'")
            return (points[0] if points else 0), row[0], hp, item_id

    def checkpoint(self, battle_id, user_id, character, hp, turn):
        with self.connect() as connection:
            now = datetime.now(timezone.utc)
            row = connection.execute('''UPDATE george_link_vitality SET hp=%s,heal_at=%s,active_until=%s,last_turn=%s
                WHERE user_id=%s AND character=%s AND battle_id=%s AND last_turn<=%s RETURNING hp''',
                                     (hp, now, now + timedelta(minutes=5), turn, user_id, character, battle_id, turn)).fetchone()
            if not row:
                raise MemoryUnavailable('このバトルのHPを保存できなかったぜ。')

    def finish(self, battle_id, user_id, character, result, hp, enemy_level=1):
        if result not in ('won', 'lost', 'abandoned'):
            raise ValueError('Invalid battle result')
        if enemy_level not in ENEMY_EXP:
            raise ValueError('Invalid enemy level')
        with self.connect() as connection:
            # Only the first transition can award points, even after a network retry.
            row = connection.execute('''UPDATE george_link_battles SET result=%s
                WHERE battle_id=%s AND user_id=%s AND character=%s AND result='active' RETURNING equipment_id''',
                                     (result, battle_id, user_id, character)).fetchone()
            experience, dropped, new_item = 0, None, False
            if row and result == 'won':
                experience = ENEMY_EXP[enemy_level]
                if row[0] == 'bond':
                    experience = experience * 110 // 100
                connection.execute('''INSERT INTO george_link_bonds VALUES (%s,%s,%s)
                    ON CONFLICT(user_id,character) DO UPDATE SET points=george_link_bonds.points+EXCLUDED.points''',
                                   (user_id, character, experience))
                dropped = roll_drop()
                if dropped:
                    new_item = connection.execute('''INSERT INTO george_link_items(user_id,item_id) VALUES (%s,%s)
                        ON CONFLICT(user_id,item_id) DO NOTHING RETURNING item_id''', (user_id, dropped)).fetchone() is not None
            if row:
                connection.execute('''UPDATE george_link_battles SET awarded_exp=%s,dropped_item=%s,drop_new=%s
                    WHERE battle_id=%s''', (experience, dropped, new_item, battle_id))
                connection.execute('''UPDATE george_link_vitality SET hp=%s,heal_at=now(),battle_id=NULL,active_until=NULL
                    WHERE user_id=%s AND character=%s AND battle_id=%s''', (hp, user_id, character, battle_id))
            else:
                receipt = connection.execute('''SELECT awarded_exp,dropped_item,drop_new FROM george_link_battles
                    WHERE battle_id=%s AND user_id=%s AND character=%s''', (battle_id, user_id, character)).fetchone()
                if receipt is None:
                    raise MemoryUnavailable('このバトルの保存結果を確認できなかったぜ。')
                experience, dropped, new_item = receipt
            points = connection.execute('SELECT points FROM george_link_bonds WHERE user_id=%s AND character=%s', (user_id, character)).fetchone()
            return BattleReward(points[0] if points else 0, experience, dropped, new_item)

    def inventory(self, user_id):
        with self.connect() as connection:
            owned = connection.execute('SELECT item_id FROM george_link_items WHERE user_id=%s ORDER BY item_id', (user_id,)).fetchall()
            equipped = connection.execute('SELECT item_id FROM george_link_equipment WHERE user_id=%s', (user_id,)).fetchone()
            return [row[0] for row in owned], equipped[0] if equipped else None

    def equip(self, user_id, item_id):
        if item_id is not None and item_id not in ITEMS:
            raise ValueError('所持品からお守りを選んでくれ！')
        with self.connect() as connection:
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            active = connection.execute('''SELECT 1 FROM george_link_vitality
                WHERE user_id=%s AND battle_id IS NOT NULL AND active_until>now() LIMIT 1''', (user_id,)).fetchone()
            if active:
                raise ValueError('戦闘中は装備を変えられないぜ。終了してから付け替えてくれ！')
            if item_id and not connection.execute('SELECT 1 FROM george_link_items WHERE user_id=%s AND item_id=%s', (user_id, item_id)).fetchone():
                raise ValueError('そのお守りはまだ持っていないぜ。')
            previous = connection.execute('SELECT item_id FROM george_link_equipment WHERE user_id=%s', (user_id,)).fetchone()
            old_max = max_hp(previous[0] if previous else None)
            now = datetime.now(timezone.utc)
            rows = connection.execute('''SELECT character,hp,heal_at,battle_id,active_until FROM george_link_vitality
                WHERE user_id=%s FOR UPDATE''', (user_id,)).fetchall()
            for character, hp, anchor, battle_id, expires in rows:
                hp, anchor = recovered_hp(hp, max(anchor, expires) if battle_id and expires else anchor, now, old_max)
                hp = min(hp, max_hp(item_id))
                if battle_id:
                    connection.execute("UPDATE george_link_battles SET result='abandoned' WHERE battle_id=%s AND result='active'", (battle_id,))
                connection.execute('''UPDATE george_link_vitality SET hp=%s,heal_at=%s,battle_id=NULL,active_until=NULL
                    WHERE user_id=%s AND character=%s''',
                                   (hp, anchor, user_id, character))
            if item_id is None:
                connection.execute('DELETE FROM george_link_equipment WHERE user_id=%s', (user_id,))
            else:
                connection.execute('''INSERT INTO george_link_equipment VALUES (%s,%s)
                    ON CONFLICT(user_id) DO UPDATE SET item_id=EXCLUDED.item_id''', (user_id, item_id))


class BattleView(discord.ui.View):
    def __init__(self, bot, store, active, user_id, battle_id, card, points, attempt, hp=PLAYER_MAX_HP, enemy_level=1, equipment_id=None):
        super().__init__(timeout=300)
        self.bot, self.store, self.active = bot, store, active
        self.user_id, self.battle_id, self.card = user_id, battle_id, card
        self.battle = Battle.spawn(character_identity(card), points, hp=hp, enemy_level=enemy_level, equipment_id=equipment_id)
        self.reward = None
        self.pending_checkpoint = False
        self.attempt, self.lock, self.message = attempt, asyncio.Lock(), None
        self.saved, self.character_line = False, ''
        self.hint_turn = -1
        self.expired = False
        self.action_buttons()

    def action_buttons(self):
        self.clear_items()
        for action, label, style in [('attack', '攻撃', discord.ButtonStyle.primary),
                                     ('defend', '防御', discord.ButtonStyle.secondary),
                                     ('exceed', 'エクシード', discord.ButtonStyle.danger)]:
            button = discord.ui.Button(label=label, style=style, custom_id='link:' + action)
            async def callback(interaction, selected=action):
                await self.play(interaction, selected)
            button.callback = callback
            self.add_item(button)
            button.disabled = self.battle.result != 'active' or (action == 'exceed' and not self.battle.can_exceed)

    async def save_error(self, interaction):
        self.clear_items()
        retry = discord.ui.Button(label='保存を再試行', style=discord.ButtonStyle.secondary)
        async def callback(interaction):
            await self.play(interaction, 'retry')
        retry.callback = callback
        self.add_item(retry)
        await interaction.edit_original_response(embed=self.embed(), view=self)
        await interaction.followup.send('HP・結果を保存できなかったぜ。保存の再試行ボタンを押してくれ。', ephemeral=True)

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
        if self.expired and state.result == 'active':
            title = 'エクシーズバトル｜時間切れ'
        embed = discord.Embed(title=title, description=f'**{discord.utils.escape_markdown(state.character)}とリンク**\n絆Lv.{state.level}｜絆経験値 {state.points}EXP\n本日 {self.attempt}/{DAILY_LIMIT}回目', color=0xB06FE0)
        needed = level_progress(state.points)[1]
        if needed:
            embed.description += f'\n次の絆レベルまであと{needed}EXP'
        item = ITEMS.get(state.equipment_id)
        embed.description += '\n装備：' + (item.name if item else 'なし')
        embed.add_field(name=state.character, value=f'HP {state.hp}/{state.max_hp}', inline=True)
        enemy = f'HP {state.enemy_hp}/{state.enemy_max_hp}\n勝利で{ENEMY_EXP[state.enemy_level]}EXP'
        enemy += f'\n個体差：HP {state.enemy_hp_percent}％・攻撃 {state.enemy_attack_percent}％・防御 {state.enemy_defense_percent}％'
        embed.add_field(name=f'{ENEMY_NAMES[state.enemy_level]} Lv.{state.enemy_level}', value=enemy, inline=True)
        embed.add_field(name=f'ターン {state.turn}', value=state.last, inline=False)
        line = self.character_line
        if state.result == 'active' and not self.expired and self.hint_turn != state.turn:
            line = '大きな攻撃が来る！ 守りを固めて！' if (state.turn + 1) % 3 == 0 else '相手の動きを見て、息を合わせていこう！'
        if line:
            warning = state.result == 'active' and (state.turn + 1) % 3 == 0
            name = f'⚠️ {state.character}の警告' if warning else f'{state.character}からの一言'
            embed.add_field(name=name, value=discord.utils.escape_markdown(line), inline=False)
        if self.reward and self.reward.item_id in ITEMS:
            dropped = ITEMS[self.reward.item_id]
            status = '初入手！' if self.reward.new_item else '所持済み'
            embed.add_field(name='🎁 ドロップ', value=f'{dropped.name}｜{status}\n{dropped.effect}', inline=False)
        embed.set_footer(text=f'HPは持ち越し・戦闘外で3分ごとに1回復｜エクシード残り{(2 if state.equipment_id == "resonance" else 1) - state.exceed_uses}回')
        return embed

    async def turn_hint(self):
        state = self.battle
        if state.result != 'active' or self.expired or self.hint_turn == state.turn:
            return
        self.hint_turn = state.turn
        strong = (state.turn + 1) % 3 == 0
        fallback = '大きな攻撃が来る！ 守りを固めて！' if strong else '相手の動きを見て、息を合わせていこう！'
        self.character_line = fallback
        chat = getattr(self.bot, 'george_chat', None)
        if chat is None:
            return
        profile = next((record for record in progressData if record['progressName'] == state.character), favorite_details(self.card)[0])
        facts = dict(action='battle_hint', character=state.character, profile=profile,
                     voice_sample=PRESENTATIONS.get(self.card.id, {}).get('quote', ''),
                     enemy=ENEMY_NAMES[state.enemy_level], turn=state.turn, next_strong_attack=strong,
                     hp=state.hp, exceed_remaining=(2 if state.equipment_id == 'resonance' else 1) - state.exceed_uses)
        async def generate():
            slots = getattr(self.bot, 'battle_hint_slots', None)
            if slots is None:
                return await chat.collection_comment(facts)
            async with slots:
                return await chat.collection_comment(facts)
        try:
            line = await asyncio.wait_for(generate(), timeout=10)
            if strong:
                if not any(word in line for word in ('大き', '強攻撃', '強烈', '強い攻撃')) or not any(word in line for word in ('防御', '守', '備え', '防い')):
                    return
            if not strong and any(word in line for word in ('強攻撃', '大きな攻撃', '大きい攻撃')):
                return
            self.character_line = line
        except Exception as exc:
            logging.warning('Battle hint fallback: type=%s', type(exc).__name__)

    async def remarks(self):
        self.character_line = ''
        chat = getattr(self.bot, 'george_chat', None)
        if chat is None:
            return
        state = self.battle
        profile = next((record for record in progressData if record['progressName'] == state.character), favorite_details(self.card)[0])
        facts = dict(action='battle_character_result', character=state.character, profile=profile,
                     voice_sample=PRESENTATIONS.get(self.card.id, {}).get('quote', ''),
                     result='勝利' if state.result == 'won' else '敗北',
                     enemy_name=ENEMY_NAMES[state.enemy_level], enemy_level=state.enemy_level,
                     hp=state.hp, experience=self.reward.experience if self.reward else 0)
        try:
            self.character_line = await asyncio.wait_for(chat.collection_comment(facts), timeout=12)
        except Exception as exc:
            logging.warning('Battle character line skipped: type=%s', type(exc).__name__)

    async def play(self, interaction, action):
        await interaction.response.defer()
        async with self.lock:
            if self.saved:
                return
            if action == 'retry':
                if self.battle.result == 'active' and not self.pending_checkpoint:
                    return
            elif self.pending_checkpoint:
                return
            elif not self.battle.act(action):
                return
            if self.battle.result == 'active':
                try:
                    await asyncio.to_thread(self.store.checkpoint, self.battle_id, self.user_id, self.battle.character, self.battle.hp, self.battle.turn)
                    self.pending_checkpoint = False
                    self.action_buttons()
                except MemoryUnavailable:
                    self.pending_checkpoint = True
                    await self.save_error(interaction)
                    return
            for button in self.children:
                button.disabled = self.battle.result != 'active' or (button.custom_id == 'link:exceed' and not self.battle.can_exceed)
            if self.battle.result != 'active':
                self.release()
                try:
                    self.reward = await asyncio.to_thread(self.store.finish, self.battle_id, self.user_id, self.battle.character, self.battle.result, self.battle.hp, self.battle.enemy_level)
                    self.battle.points = self.reward.points
                    self.saved = True
                    self.battle.last += f'\n絆経験値＋{self.reward.experience}EXP！' if self.battle.result == 'won' else '\n経験値の獲得なし。'
                    self.clear_items()
                except MemoryUnavailable:
                    await self.save_error(interaction)
                    return
                await self.remarks()
            else:
                await self.turn_hint()
            await interaction.edit_original_response(embed=self.embed(), view=self)
            if self.saved:
                self.stop()

    async def on_timeout(self):
        async with self.lock:
            self.expired = True
            self.release()
            for button in self.children:
                button.disabled = True
            if self.battle.result == 'active':
                self.character_line = ''
                self.battle.last = '時間切れでリンク解除。経験値の獲得はないぜ。'
                try:
                    await asyncio.to_thread(self.store.finish, self.battle_id, self.user_id, self.battle.character, 'abandoned', self.battle.hp)
                except MemoryUnavailable:
                    self.battle.last += '\nHP保存に失敗したため、最後に保存できた状態が使用されるぜ。'
                    logging.warning('Battle timeout HP save failed')
            if self.message:
                try:
                    await self.message.edit(embed=self.embed(), view=self)
                except discord.HTTPException:
                    pass


def register_link_battle(bot, store=None):
    store = store if store is not None else BattleStore()
    bot.battle_store = store
    active = {}
    bot.battle_active = active
    bot.battle_hint_slots = asyncio.Semaphore(2)

    @bot.tree.command(name='エクシーズバトル', description='プログレスとリンクして模擬戦に挑む（1日3回）')
    @app_commands.describe(敵='戦う相手を選択')
    @app_commands.choices(敵=[app_commands.Choice(name=f'{ENEMY_NAMES[level]}Lv{level}', value=level) for level in ENEMY_HP])
    async def battle_command(interaction: discord.Interaction, 敵: int = 1):
        await interaction.response.defer(ephemeral=True)
        if 敵 not in ENEMY_HP:
            await interaction.followup.send('候補から戦う敵を選んでくれ！', ephemeral=True)
            return
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
            points, attempt, hp, item_id = await asyncio.to_thread(store.start, interaction.id, interaction.user.id, character_identity(card), datetime.now(JST).date())
            view = BattleView(bot, store, active, interaction.user.id, interaction.id, card, points, attempt, hp, 敵, item_id)
            active[interaction.user.id] = view
            try:
                await view.turn_hint()
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
