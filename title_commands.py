import asyncio
import logging
import discord
from discord import app_commands

from registered_memory import MemoryUnavailable
from favorite_album import JST
from title_notifications import notify_titles, title_icon
from title_core import title_condition
from datetime import datetime


class TitleView(discord.ui.View):
    PAGE_SIZE = 20

    def __init__(self, user_id, titles, roles, guild=None, equipped=None, pending=()):
        super().__init__(timeout=180)
        self.user_id, self.titles, self.roles, self.guild = user_id, titles, roles, guild
        self.equipped = equipped
        self.pending, self.mode = list(pending), 'earned'
        self.page, self.selected = 0, None
        self.lock = asyncio.Lock()
        self.expired, self.message = False, None
        self.build()

    def build(self):
        self.clear_items()
        if self.mode == 'pending':
            self.add_navigation()
            return
        rows = self.titles[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        select = discord.ui.Select(placeholder='装着する獲得済み称号を選択', row=0,
            options=[discord.SelectOption(label=row[1][:100], value=row[0], emoji=title_icon(row[0]), default=self.selected == row[0]) for row in rows]
            or [discord.SelectOption(label='まだ称号がありません', value='none')], disabled=not rows)

        async def choose(interaction):
            await interaction.response.defer()
            async with self.lock:
                if self.expired:
                    return
                self.selected = select.values[0]
                self.build()
                await interaction.edit_original_response(embed=self.embed(), view=self)

        select.callback = choose
        self.add_item(select)
        equip = discord.ui.Button(label='装着', style=discord.ButtonStyle.primary, row=1,
            disabled=not (self.selected and self.guild))
        remove = discord.ui.Button(label='解除', row=1, disabled=self.guild is None)

        async def equip_callback(interaction):
            await self.apply(interaction, self.selected)

        async def remove_callback(interaction):
            await self.apply(interaction, None)

        equip.callback, remove.callback = equip_callback, remove_callback
        self.add_item(equip)
        self.add_item(remove)
        self.add_navigation()

    def add_navigation(self):
        for label, mode in [('獲得済み', 'earned'), ('未獲得', 'pending')]:
            button = discord.ui.Button(label=label, row=3, disabled=self.mode == mode,
                style=discord.ButtonStyle.primary if self.mode == mode else discord.ButtonStyle.secondary)

            async def switch(interaction, mode=mode):
                await interaction.response.defer()
                async with self.lock:
                    if self.expired:
                        return
                    self.mode, self.page, self.selected = mode, 0, None
                    self.build()
                    await interaction.edit_original_response(embed=self.embed(), view=self)

            button.callback = switch
            self.add_item(button)
        items = self.titles if self.mode == 'earned' else self.pending
        for label, delta in [('◀ 前へ', -1), ('次へ ▶', 1)]:
            button = discord.ui.Button(label=label, row=2,
                disabled=not 0 <= self.page + delta < max(1, (len(items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE))

            async def turn(interaction, delta=delta):
                await interaction.response.defer()
                async with self.lock:
                    if self.expired:
                        return
                    current = self.titles if self.mode == 'earned' else self.pending
                    self.page = max(0, min((len(current) - 1) // self.PAGE_SIZE, self.page + delta))
                    self.selected = None
                    self.build()
                    await interaction.edit_original_response(embed=self.embed(), view=self)

            button.callback = turn
            self.add_item(button)

    def embed(self, status=None):
        items = self.titles if self.mode == 'earned' else self.pending
        rows = items[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        name = next((row[1] for row in self.titles if row[0] == self.equipped), 'なし')
        description = status or ''
        if self.guild is None:
            description += '\nDMでは一覧のみ。装着・解除はサーバーで使ってくれ！'
        equipped_icon = f'{title_icon(self.equipped)} ' if self.equipped and name != 'なし' else ''
        if self.mode == 'earned':
            description += f'\n\n【装着中】\n{equipped_icon}{discord.utils.escape_markdown(name)}\n\n'
        else:
            description += '\n\n'
        if self.mode == 'pending':
            description += '\n\n'.join(f'{title_icon(row[0])} **{discord.utils.escape_markdown(row[1])}**\n{discord.utils.escape_markdown(row[2])}' for row in rows) or '対象の称号はすべて獲得済みだぜ！'
        else:
            description += '【獲得済み】\n'
            descriptions = []
            for key, title, acquired in rows:
                day = acquired.astimezone(JST).strftime('%Y年%m月%d日') if isinstance(acquired, datetime) else '未記録'
                descriptions.append(f'{title_icon(key)} **{discord.utils.escape_markdown(title)}**\n'
                                    f'{discord.utils.escape_markdown(title_condition(key))}\n獲得日：{day}')
            description += '\n\n'.join(descriptions) or 'まだ称号はないぜ。クイズやプレゼントで集めてみよう！'
        embed = discord.Embed(title='称号', description=description.lstrip(), color=0xD5AD49)
        if len(items) > self.PAGE_SIZE:
            embed.set_footer(text=f'{self.page + 1}/{(len(items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE}ページ')
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('自分の /称号 から操作してくれ！', ephemeral=True)
            return False
        return True

    async def apply(self, interaction, key):
        await interaction.response.defer()
        async with self.lock:
            if self.expired or self.guild is None or self.mode != 'earned':
                return
            try:
                name = await self.roles.equip(self.guild, self.user_id, key)
            except (ValueError, MemoryUnavailable) as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            except discord.HTTPException:
                logging.warning('Title role update failed')
                await interaction.followup.send('称号のロール変更を確認できなかったぜ。ロール数・権限・上下関係を管理者に確認してもらってから再試行してくれ。', ephemeral=True)
                return
            self.equipped = key
            self.build()
            await interaction.edit_original_response(embed=self.embed(f'「{name}」を装着したぜ！' if name else '称号を外したぜ！'), view=self)

    async def on_timeout(self):
        async with self.lock:
            self.expired = True
            for child in self.children:
                child.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass


def register_title_commands(bot):
    @bot.tree.command(name='称号', description='獲得した称号を確認・装着・解除（装着はサーバーごとに1つ）')
    async def titles(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await asyncio.to_thread(bot.title_store.titles, interaction.user.id)
            pending = await asyncio.to_thread(bot.title_store.pending, interaction.user.id, rows)
            guild = interaction.guild
            equipped = await asyncio.to_thread(bot.title_store.equipped, guild.id, interaction.user.id) if guild else None
            view = TitleView(interaction.user.id, rows, bot.title_roles, guild, equipped, pending)
            view.message = await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True, wait=True,
                allowed_mentions=discord.AllowedMentions.none())
            await notify_titles(interaction, bot.title_store)
        except MemoryUnavailable as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
