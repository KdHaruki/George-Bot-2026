"""One-slot equipment definitions, drops and private inventory command."""
import asyncio
from dataclasses import dataclass
import random
import discord
from discord import app_commands
from registered_memory import MemoryUnavailable


@dataclass(frozen=True)
class Equipment:
    name: str
    effect: str
    rare: bool = False


ITEMS = {
    'power': Equipment('力のお守り', '「攻撃」の与ダメージ＋2'),
    'guard': Equipment('守護のお守り', '被ダメージ−1（最低1）'),
    'wall': Equipment('防壁のお守り', '「防御」時の被ダメージ−2（最低1）'),
    'skill': Equipment('技のお守り', 'エクシードの与ダメージ＋3'),
    'vitality': Equipment('活力のお守り', '最大HP＋5'),
    'immortal': Equipment('不死のお守り', '1戦に1回、致命傷を受けてもHP1で耐える', True),
    'miracle': Equipment('奇跡のお守り', '生存中のターン終了時に最大HPの3％回復。戦闘終了後は発動しない', True),
    'resonance': Equipment('共鳴のお守り', 'エクシードを1戦で合計2回使える', True),
    'counter': Equipment('反撃のお守り', '強攻撃を防御すると敵の最大HPの3％を追加ダメージ（切り捨て・最低1）', True),
    'rebellion': Equipment('反逆のお守り', '行動開始時のHPが30以下なら与ダメージ＋5', True),
    'focus': Equipment('集中のお守り', '「攻撃」の基礎ダメージ抽選が17〜20になる', True),
    'bond': Equipment('絆のお守り', '勝利EXP＋10％（端数切り捨て）', True),
}


def roll_drop(rng=None):
    rng = rng or random.SystemRandom()
    ticket = rng.randrange(10000)
    if ticket >= 2000:
        return None
    rare = ticket < 300
    return rng.choice([key for key, item in ITEMS.items() if item.rare == rare])


def max_hp(item_id):
    return 105 if item_id == 'vitality' else 100


def register_equipment(bot):
    async def autocomplete(interaction, current):
        try:
            owned, _ = await asyncio.wait_for(asyncio.to_thread(bot.battle_store.inventory, interaction.user.id), timeout=2)
        except (MemoryUnavailable, asyncio.TimeoutError):
            return []
        choices = [app_commands.Choice(name=ITEMS[key].name, value=key) for key in owned
                   if key in ITEMS and current in ITEMS[key].name]
        if not current or current in '解除':
            choices.append(app_commands.Choice(name='解除', value='none'))
        return choices[:25]

    @bot.tree.command(name='装備', description='装備を確認・付け替え（戦闘中は変更不可）')
    @app_commands.describe(お守り='所持品から選ぶ。「解除」で外す。省略すると装備と所持品を確認')
    @app_commands.autocomplete(お守り=autocomplete)
    async def equipment_command(interaction: discord.Interaction, お守り: str = None):
        await interaction.response.defer(ephemeral=True)
        try:
            if お守り is not None:
                if interaction.user.id in getattr(bot, 'battle_active', {}):
                    raise ValueError('戦闘中は装備を変えられないぜ。終了してから付け替えてくれ！')
                item_id = next((key for key, item in ITEMS.items() if お守り in (key, item.name)), None)
                if お守り in ('none', '解除'):
                    item_id = None
                elif item_id is None:
                    raise ValueError('所持品の候補からお守りを選んでくれ！')
                await asyncio.to_thread(bot.battle_store.equip, interaction.user.id, item_id)
            owned, selected = await asyncio.to_thread(bot.battle_store.inventory, interaction.user.id)
            item = ITEMS.get(selected)
            description = f'**装備中：{item.name}**\n{item.effect}' if item else '装備中：なし'
            if お守り is not None:
                description = '装備を更新したぜ！\n' + description
            embed = discord.Embed(title='お守り装備', description=description, color=0xB06FE0)
            for rare, label in ((False, '通常装備'), (True, 'レア装備')):
                entries = [f'**{item.name}**\n{item.effect}' for key, item in ITEMS.items() if key in owned and item.rare == rare]
                embed.add_field(name=label, value='\n\n'.join(entries) or 'まだ持っていないぜ。', inline=False)
            embed.set_footer(text='装備枠は1個｜勝利時：レア3％・通常17％・なし80％｜重複所持なし')
            await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except (ValueError, MemoryUnavailable) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
