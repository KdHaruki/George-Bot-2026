import asyncio
import logging
import discord
from discord import app_commands

from command_permissions import require_administrator
from registered_memory import MemoryUnavailable


class TitleView(discord.ui.View):
    PAGE_SIZE = 20

    def __init__(self, user_id, titles, roles, guild=None, enabled=False, equipped=None):
        super().__init__(timeout=180)
        self.user_id, self.titles, self.roles, self.guild = user_id, titles, roles, guild
        self.enabled, self.equipped = enabled, equipped
        self.page, self.selected = 0, None
        self.lock = asyncio.Lock()
        self.expired, self.message = False, None
        self.build()

    def build(self):
        self.clear_items()
        rows = self.titles[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        select = discord.ui.Select(placeholder='装着する獲得済み称号を選択', row=0,
            options=[discord.SelectOption(label=row[1][:100], value=row[0], default=self.selected == row[0]) for row in rows]
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
            disabled=not (self.selected and self.guild and self.enabled))
        remove = discord.ui.Button(label='解除', row=1, disabled=self.guild is None)

        async def equip_callback(interaction):
            await self.apply(interaction, self.selected)

        async def remove_callback(interaction):
            await self.apply(interaction, None)

        equip.callback, remove.callback = equip_callback, remove_callback
        self.add_item(equip)
        self.add_item(remove)
        for label, delta in [('◀ 前へ', -1), ('次へ ▶', 1)]:
            button = discord.ui.Button(label=label, row=2,
                disabled=not 0 <= self.page + delta < max(1, (len(self.titles) + self.PAGE_SIZE - 1) // self.PAGE_SIZE))

            async def turn(interaction, delta=delta):
                await interaction.response.defer()
                async with self.lock:
                    if self.expired:
                        return
                    self.page = max(0, min((len(self.titles) - 1) // self.PAGE_SIZE, self.page + delta))
                    self.selected = None
                    self.build()
                    await interaction.edit_original_response(embed=self.embed(), view=self)

            button.callback = turn
            self.add_item(button)

    def embed(self, status=None):
        rows = self.titles[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        name = next((row[1] for row in self.titles if row[0] == self.equipped), 'なし')
        description = status or '獲得した称号は全サーバー共通、装着はサーバーごとに1つだぜ！'
        if self.guild is None:
            description += '\nDMでは一覧のみ。装着・解除はサーバーで使ってくれ！'
        elif not self.enabled:
            description += '\nこのサーバーの装着はOFF。管理者が /称号設定 でONにできるぞ。'
        description += f'\n\n【装着中】\n{discord.utils.escape_markdown(name)}\n\n【獲得済み】\n'
        description += '\n'.join(discord.utils.escape_markdown(row[1]) for row in rows) or 'まだ称号はないぜ。クイズやプレゼントで集めてみよう！'
        embed = discord.Embed(title='称号', description=description, color=0xD5AD49)
        if len(self.titles) > self.PAGE_SIZE:
            embed.set_footer(text=f'{self.page + 1}/{(len(self.titles) + self.PAGE_SIZE - 1) // self.PAGE_SIZE}ページ')
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('自分の /称号 から操作してくれ！', ephemeral=True)
            return False
        return True

    async def apply(self, interaction, key):
        await interaction.response.defer()
        async with self.lock:
            if self.expired or self.guild is None:
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
            guild = interaction.guild
            enabled = await asyncio.to_thread(bot.title_store.enabled, guild.id) if guild else False
            equipped = await asyncio.to_thread(bot.title_store.equipped, guild.id, interaction.user.id) if guild else None
            view = TitleView(interaction.user.id, rows, bot.title_roles, guild, enabled, equipped)
            view.message = await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True, wait=True,
                allowed_mentions=discord.AllowedMentions.none())
        except MemoryUnavailable as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    @bot.tree.command(name='称号設定', description='称号ロール装着のON・OFFを設定・確認（管理者用）')
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(有効='ONで装着を許可。OFFでも獲得済み称号は残り、本人による解除は可能')
    async def configure(interaction: discord.Interaction, 有効: bool = None):
        if not await require_administrator(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            if 有効 is not None:
                await bot.title_roles.configure(interaction.guild, 有効)
            enabled = await asyncio.to_thread(bot.title_store.enabled, interaction.guild_id)
            text = f'称号の装着：{"ON" if enabled else "OFF"}。獲得した称号は消えないぜ。'
            if not enabled:
                text += '\n今付いている称号ロールはそのまま。本人が /称号 から解除できるぞ。'
            await interaction.followup.send(text, ephemeral=True)
        except (ValueError, MemoryUnavailable) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
