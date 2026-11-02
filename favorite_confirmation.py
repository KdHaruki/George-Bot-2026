"""お気に入りの解除を本人に確認し、確認後にだけ登録を解除する。"""

import asyncio

import discord

from database import MemoryUnavailable


class FavoriteRemovalView(discord.ui.View):
    def __init__(self, owner_id, store, character):
        super().__init__(timeout=180)
        self.owner_id, self.store, self.character = owner_id, store, character
        self.message = None
        self.finished = False
        self.lock = asyncio.Lock()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('この確認画面を開いた本人だけが操作できるぜ！', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='解除する', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        await self.finish(interaction, remove=True)

    @discord.ui.button(label='登録を続ける', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await self.finish(interaction, remove=False)

    async def finish(self, interaction, *, remove):
        await interaction.response.defer()
        async with self.lock:
            if self.finished:
                return
            if remove:
                try:
                    await asyncio.to_thread(self.store.remove_favorite, self.owner_id, self.character)
                except (ValueError, MemoryUnavailable) as exc:
                    await interaction.followup.send(str(exc), ephemeral=True)
                    return
            self.finished = True
            for child in self.children:
                child.disabled = True
            self.stop()
            text = ('お気に入りを解除したぜ。所持カード・好感度・アルバムはそのままだぞ！'
                    if remove else '解除せずに閉じたぜ。お気に入りの登録は変更していないぞ！')
            await interaction.edit_original_response(content=text, view=self, allowed_mentions=discord.AllowedMentions.none())

    async def on_timeout(self):
        async with self.lock:
            self.finished = True
            for child in self.children:
                child.disabled = True
            if self.message:
                try:
                    await self.message.edit(content='確認の時間が切れたぜ。お気に入りは解除していないぞ！', view=self)
                except discord.HTTPException:
                    pass
