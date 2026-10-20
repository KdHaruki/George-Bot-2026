import asyncio
import logging

import discord

from presents import ITEMS, affection_display, affection_limit, link_label
from registered_memory import MemoryUnavailable
from title_notifications import notify_titles
from present_catalog import CATEGORIES, ITEM_CATEGORY, preferred_categories


class PresentView(discord.ui.View):
    def __init__(self, user_id, store, character, items, points, perfect=False):
        super().__init__(timeout=180)
        self.user_id, self.store, self.character = user_id, store, character
        self.items, self.points = dict(items), points
        self.perfect = perfect
        self.page = 0
        self.keys = [key for key in ITEMS if items.get(key, 0) > 0]
        self.lock = asyncio.Lock()
        self.processed = set()
        self.message = None
        self.expired = False
        self.build_buttons()

    def build_buttons(self):
        self.clear_items()
        for index, key in enumerate(self.keys[self.page * 6:self.page * 6 + 6]):
            emoji, label = ITEMS[key]
            category = CATEGORIES[ITEM_CATEGORY[key]][0] if key in ITEM_CATEGORY else 'レア'
            button = discord.ui.Button(label=f'{category}：{label} ×{self.items[key]}', emoji=emoji,
                                       row=index // 2, disabled=self.items[key] <= 0)

            async def callback(interaction, key=key):
                await self.give(interaction, key)

            button.callback = callback
            self.add_item(button)
        if len(self.keys) > 6:
            for label, delta in [('◀ 前へ', -1), ('次へ ▶', 1)]:
                button = discord.ui.Button(label=label, row=3,
                    disabled=not 0 <= self.page + delta < (len(self.keys) + 5) // 6)

                async def turn(interaction, delta=delta):
                    await interaction.response.defer()
                    async with self.lock:
                        if self.expired:
                            return
                        self.page = max(0, min((len(self.keys) - 1) // 6, self.page + delta))
                        self.build_buttons()
                        await interaction.edit_original_response(embed=self.embed(), view=self)

                button.callback = turn
                self.add_item(button)

    def embed(self, status=None):
        show_instruction = status is None
        if status is None:
            status = ''
        likes = '、'.join(CATEGORIES[key][0] for key in preferred_categories(self.character)) or '設定なし'
        embed = discord.Embed(title=f'{self.character}にプレゼント', color=0xE2AD48,
            description=(f'{status}\n\n' if status else '') + f'好感度：{affection_display(self.points, self.perfect)}\n\n喜ばれる贈り物：{likes}')
        limit = affection_limit(self.perfect)
        if self.points >= limit:
            embed.description += f'\n好感度{limit}では＋0。喜ばれる贈り物を1個贈ると次のパーフェクトリンクになり、上限が{limit + 100}になるぜ。'
        if not self.keys:
            embed.add_field(name='手持ちのプレゼントはないぜ！', value='/おみくじ や /クイズ で1日1個もらえるぞ。', inline=False)
        elif show_instruction:
            embed.description += '\n\nボタンを押すと1個贈るぜ！'
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('自分の /お気に入り プレゼント から開いてくれ！', ephemeral=True)
            return False
        return True

    async def give(self, interaction, key):
        await interaction.response.defer()
        async with self.lock:
            if self.expired or interaction.id in self.processed:
                return
            try:
                gain, points, perfect = await asyncio.to_thread(self.store.give, self.user_id, interaction.id, self.character, key)
            except (ValueError, MemoryUnavailable) as exc:
                logging.warning('Present skipped: type=%s', type(exc).__name__)
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            self.processed.add(interaction.id)
            self.items[key] = max(0, self.items[key] - 1)
            self.points = points
            advanced = int(perfect) > int(self.perfect)
            self.perfect = perfect
            self.build_buttons()
            status = f'{ITEMS[key][1]}を贈ったぜ！ 好感度 **＋{gain}**'
            if advanced:
                status = f'{ITEMS[key][1]}を贈って、**{link_label(perfect)}達成！**'
            await interaction.edit_original_response(embed=self.embed(status), view=self)
            await notify_titles(interaction, self.store)

    async def on_timeout(self):
        async with self.lock:
            self.expired = True
            for button in self.children:
                button.disabled = True
            if self.message:
                try:
                    await self.message.edit(embed=self.embed('時間切れだぜ。もう一度コマンドから開いてくれ！'), view=self)
                except discord.HTTPException:
                    pass


async def open_presents(interaction, store):
    await interaction.response.defer(ephemeral=True)
    try:
        character, items, points, perfect = await asyncio.to_thread(store.snapshot, interaction.user.id)
        view = PresentView(interaction.user.id, store, character, items, points, perfect)
        view.message = await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True,
            wait=True, allowed_mentions=discord.AllowedMentions.none())
        await notify_titles(interaction, store)
    except (ValueError, MemoryUnavailable) as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
