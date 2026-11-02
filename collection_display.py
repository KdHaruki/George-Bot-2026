"""所持カードとお気に入りの表示、ページ切替、公開ボタンを組み立てる。"""

import math

import discord

from progress_profiles import character_key, normalize, profile_for, george_name
from relink_presentations import local_image
from result_sharing import ShareButton


INVENTORY_RARITY = {'UR': 'ＵＲ', 'SR': 'ＳＲ', 'HR': 'ＨＲ', 'R': 'Ｒ',
                    '★3': '★３', '★2': '★２', '★1': '★１'}


class CardListView(discord.ui.View):
    def __init__(self, owner_id, lines, title, *, can_share=False):
        super().__init__(timeout=180)
        self.owner_id, self.lines, self.title = owner_id, lines, title
        self.page = 0
        self.pages = math.ceil(len(lines) / 10)
        self.message = None
        self.previous = discord.ui.Button(label='前へ', disabled=True)
        self.next = discord.ui.Button(label='次へ', disabled=self.pages <= 1)
        self.previous.callback = self.go_previous
        self.next.callback = self.go_next
        self.add_item(self.previous)
        self.add_item(self.next)
        pages = [discord.Embed(title=title, description='\n'.join(lines[offset:offset + 10]), color=0xE2AD48)
                 for offset in range(0, len(lines), 10)]
        self.add_item(ShareButton(owner_id, lambda: ([page.copy() for page in pages], []),
                                  label='所持カードを全ページ公開', enabled=can_share))

    def embed(self):
        return discord.Embed(title=self.title, description='\n'.join(self.lines[self.page * 10:(self.page + 1) * 10]), color=0xE2AD48)

    async def move(self, interaction, step):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('一覧を開いた本人だけが操作できるぜ。', ephemeral=True)
            return
        self.page = min(self.pages - 1, max(0, self.page + step))
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page == self.pages - 1
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def go_previous(self, interaction):
        await self.move(interaction, -1)

    async def go_next(self, interaction):
        await self.move(interaction, 1)

    async def on_timeout(self):
        for button in self.children:
            button.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


def favorite_details(card):
    record = profile_for(card.character)
    detail = record.get('progressDetail1', '') if record else ''
    name = george_name(card.character)
    introduction = f'{name}の紹介だぜ！\n{detail}' if detail else f'{name}の詳しい紹介は、まだ俺にも分からねえな。'
    return introduction


def favorite_card_label(card):
    name = card.label
    if name.startswith(card.character):
        name = character_key(card.character) + name[len(card.character):]
    return f'【{card.rarity}】{name}'


def favorite_matches(rows, query):
    query = normalize(character_key(query.strip()))
    exact = [row for row in rows if normalize(character_key(row[1].character)) == query]
    return exact or [row for row in rows if query and query in normalize(character_key(row[1].character))]


def favorite_art(engine, character):
    cards = [card for card in engine.pools['relink']['★3']
             if character_key(card.character) == character_key(character) and local_image(card.id)]
    # Prefer a uniform where available, otherwise retain the catalogue's stable order.
    return next((card for card in cards if '制服' in card.label), cards[0] if cards else None)


def owned_card_lines(rows):
    rank = {'UR': 0, 'SR': 1, 'HR': 2, 'R': 3, '★3': 0, '★2': 1, '★1': 2}
    rows = sorted(rows, key=lambda row: (rank.get(row[1].rarity, 9), row[0], row[1].character, row[1].label, row[1].id))
    return [f"`【{INVENTORY_RARITY[card.rarity]}】` {discord.utils.escape_markdown(card.label)} — **{count}枚**"
            for _, card, count in rows]


