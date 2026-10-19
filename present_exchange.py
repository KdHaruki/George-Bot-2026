"""Owner-only 3-to-1 exchange UI for normal presents."""
import asyncio
import discord

from presents import ITEMS, NORMAL_ITEMS
from registered_memory import MemoryUnavailable


class ExchangeView(discord.ui.View):
    def __init__(self, user_id, store, items):
        super().__init__(timeout=180)
        self.user_id, self.store, self.items = user_id, store, dict(items)
        self.source = self.target = None
        self.lock = asyncio.Lock()
        self.processed = set()
        self.expired = False
        self.message = None
        self.build()

    def build(self):
        self.clear_items()
        eligible = [key for key in NORMAL_ITEMS if self.items.get(key, 0) >= 3]
        if self.source not in eligible:
            self.source = None
        if self.target == self.source:
            self.target = None
        source = discord.ui.Select(placeholder='渡す通常アイテム（3個）', row=0,
            options=[discord.SelectOption(label=f'{ITEMS[k][1]} ×{self.items[k]}', emoji=ITEMS[k][0], value=k,
                default=k == self.source) for k in eligible] or [discord.SelectOption(label='3個以上のアイテムがありません', value='none')],
            disabled=not eligible)
        target = discord.ui.Select(placeholder='受け取る通常アイテム（1個）', row=1,
            options=[discord.SelectOption(label=ITEMS[k][1], emoji=ITEMS[k][0], value=k,
                default=k == self.target) for k in NORMAL_ITEMS if k != self.source], disabled=not eligible)
        confirm = discord.ui.Button(label='3個 → 1個に交換', style=discord.ButtonStyle.primary, row=2,
            disabled=not (self.source and self.target and self.source != self.target))

        async def choose_source(interaction):
            await self.choose(interaction, 'source', source.values[0])

        async def choose_target(interaction):
            await self.choose(interaction, 'target', target.values[0])

        source.callback, target.callback, confirm.callback = choose_source, choose_target, self.exchange
        self.add_item(source)
        self.add_item(target)
        self.add_item(confirm)

    def embed(self, status='同じ通常アイテム3個を、別の通常アイテム1個と交換できるぜ！'):
        lines = [f'{ITEMS[k][0]} {ITEMS[k][1]}：{self.items.get(k, 0)}個' for k in NORMAL_ITEMS]
        return discord.Embed(title='プレゼント交換', color=0xB06FE0,
            description=status + '\n\n' + '\n'.join(lines) + '\n\n虹色の花束は交換対象外だぜ。')

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('自分の /お気に入り 交換 から開いてくれ！', ephemeral=True)
            return False
        return True

    async def choose(self, interaction, field, key):
        await interaction.response.defer()
        async with self.lock:
            if self.expired:
                return
            if key not in NORMAL_ITEMS or (field == 'source' and self.items.get(key, 0) < 3):
                return
            setattr(self, field, key)
            self.build()
            await interaction.edit_original_response(embed=self.embed(), view=self)

    async def exchange(self, interaction):
        await interaction.response.defer()
        async with self.lock:
            if self.expired or interaction.id in self.processed or not self.source or not self.target:
                return
            source, target = self.source, self.target
            try:
                remaining, received = await asyncio.to_thread(self.store.exchange, self.user_id, interaction.id, source, target)
            except (ValueError, MemoryUnavailable) as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            self.processed.add(interaction.id)
            self.items[source], self.items[target] = remaining, received
            self.source = self.target = None
            self.build()
            await interaction.edit_original_response(embed=self.embed(f'{ITEMS[source][1]}3個を、{ITEMS[target][1]}1個と交換したぜ！'), view=self)

    async def on_timeout(self):
        async with self.lock:
            self.expired = True
            for child in self.children:
                child.disabled = True
            if self.message:
                try:
                    await self.message.edit(embed=self.embed('時間切れだぜ。もう一度コマンドから開いてくれ！'), view=self)
                except discord.HTTPException:
                    pass


async def open_exchange(interaction, store):
    await interaction.response.defer(ephemeral=True)
    try:
        items = await asyncio.to_thread(store.inventory, interaction.user.id)
        view = ExchangeView(interaction.user.id, store, items)
        view.message = await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True, wait=True,
            allowed_mentions=discord.AllowedMentions.none())
    except MemoryUnavailable as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
