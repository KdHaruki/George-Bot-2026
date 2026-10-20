"""Private milestone cards with explicit, owner-initiated channel sharing."""
from datetime import datetime

import discord

from favorite_album import JST
from progress_profiles import character_key
from relink_presentations import local_image


MILESTONES = (
    (0, 'お気に入り登録記念', 'ふたりの思い出がここから始まった！'),
    (4, 'コンプリート記念', 'いろんな姿との出会いを、ひとつの思い出に。'),
    (1, '一周年記念', '一緒に歩んだ365日。これからもよろしく！'),
    (3, 'パーフェクトリンク記念', '心がつながった、特別な日の思い出。'),
)


class AlbumView(discord.ui.View):
    def __init__(self, owner_id, card, dates, owned=(), *, opened=False, guild=False):
        super().__init__(timeout=180)
        self.owner_id, self.card, self.guild = owner_id, card, guild
        self.milestones = [row for row in MILESTONES if row[0] < len(dates) and isinstance(dates[row[0]], datetime)]
        self.dates = tuple(dates)
        self.outfits = sorted({c.label for _, c, _ in owned if character_key(c.character) == character_key(card.character)})
        self.selected = self.milestones[0] if self.milestones else None
        self.shared = False
        if not opened:
            button = discord.ui.Button(label='記念を見る', emoji='📖', disabled=not self.milestones)
            button.callback = self.open_album
            self.add_item(button)
        else:
            select = discord.ui.Select(placeholder='見たい記念を選ぶ', options=[
                discord.SelectOption(label=label, value=str(index)) for index, label, _ in self.milestones])
            select.callback = self.choose
            self.add_item(select)
            if guild:
                button = discord.ui.Button(label='みんなに見せる', emoji='📤')
                button.callback = self.share
                self.add_item(button)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message('自分の /お気に入り から開いてくれ！', ephemeral=True)
        return False

    def content(self):
        index, label, message = self.selected
        day = self.dates[index].astimezone(JST).strftime('%Y年%m月%d日')
        embed = discord.Embed(title=label, description=f'**{discord.utils.escape_markdown(self.card.character)}**\n{day}\n\n{message}', color=0xB06FE0)
        if index == 4 and self.outfits:
            embed.add_field(name='【集めたカード】', value=discord.utils.escape_markdown('\n'.join(self.outfits))[:1024], inline=False)
        path = local_image(self.card.id) if self.card.rarity == '★3' else None
        files = []
        if path:
            files.append(discord.File(path, filename=path.name))
            embed.set_image(url='attachment://' + path.name)
        return embed, files

    async def open_album(self, interaction):
        view = AlbumView(self.owner_id, self.card, self.dates, opened=True, guild=interaction.guild is not None)
        view.outfits = self.outfits
        embed, files = view.content()
        try:
            await interaction.response.send_message(embed=embed, files=files, view=view, ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())
        finally:
            for file in files:
                file.close()

    async def choose(self, interaction):
        select = next(child for child in self.children if isinstance(child, discord.ui.Select))
        self.selected = next(row for row in self.milestones if str(row[0]) == select.values[0])
        self.shared = False
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = False
        embed, files = self.content()
        try:
            await interaction.response.edit_message(embed=embed, attachments=files, view=self)
        finally:
            for file in files:
                file.close()

    async def share(self, interaction):
        if self.shared:
            await interaction.response.send_message('この記念は投稿済みだぜ！', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        self.shared = True
        embed, files = self.content()
        embed.set_author(name=interaction.user.display_name)
        try:
            await interaction.channel.send(embed=embed, files=files, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            self.shared = False
            await interaction.followup.send('投稿できなかったぜ。チャンネルの送信権限を確認してくれ！', ephemeral=True)
            return
        finally:
            for file in files:
                file.close()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.edit_original_response(view=self)
        await interaction.followup.send('記念をチャンネルに投稿したぜ！', ephemeral=True)
