import asyncio
import logging
from operation_logging import event as log_event

import discord

from presents import ITEMS, affection_display, affection_limit, link_label
from database import MemoryUnavailable
from title_notifications import notify_titles
from present_catalog import preferred_labels, preferred_items
from progress_profiles import profile_for, george_name


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
            button = discord.ui.Button(label=f'{label} ×{self.items[key]}', emoji=emoji,
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
        likes = preferred_labels(self.character)
        embed = discord.Embed(title=f'{self.character}にプレゼント', color=0xE2AD48,
            description=(f'{status}\n\n' if status else '') + f'好感度：{affection_display(self.points, self.perfect)}\n\n喜ばれる贈り物：{likes}')
        limit = affection_limit(self.perfect)
        if self.points >= limit:
            gift = '喜ばれる贈り物'
            embed.description += f'\n好感度{limit}では＋0。{gift}を1個贈ると次のパーフェクトリンクになり、上限が{limit + 100}になるぜ。'
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
                log_event('プレゼント', '消費せず見送り', reason='操作期限切れ、または処理済みの操作', 操作ID=interaction.id)
                return
            try:
                gain, points, perfect = await asyncio.to_thread(self.store.give, self.user_id, interaction.id, self.character, key)
            except (ValueError, MemoryUnavailable) as exc:
                log_event('プレゼント', '保存失敗・結果未確定', error=exc, 操作ID=interaction.id)
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            self.processed.add(interaction.id)
            log_event('プレゼント', '消費・好感度の保存完了', 操作ID=interaction.id, 好感度増加=gain, 好感度=points)
            self.items[key] = max(0, self.items[key] - 1)
            self.points = points
            advanced = int(perfect) > int(self.perfect)
            self.perfect = perfect
            self.build_buttons()
            status = f'{ITEMS[key][1]}を贈ったぜ！ 好感度 **＋{gain}**'
            if advanced:
                status = f'{ITEMS[key][1]}を贈って、**{link_label(perfect)}達成！**'
            # Show the saved result immediately; a failed optional comment never retries the gift.
            await interaction.edit_original_response(embed=self.embed(status), view=self)
            preferred = key in preferred_items(self.character)
            comment = (f'{george_name(self.character)}にぴったりの贈り物だな！ 喜んでくれそうだぜ！' if preferred else
                       f'{george_name(self.character)}のために選んだ贈り物だな！ オマエの気持ちがこもってるぜ！')
            chat = getattr(getattr(interaction, 'client', None), 'george_chat', None)
            if chat is None:
                log_event('AI・贈り物のお礼', '定型文を使用', reason='AIが未設定', 操作ID=interaction.id)
            if chat is not None:
                try:
                    comment = await asyncio.wait_for(chat.collection_comment(dict(
                        action='gift_thanks', character=self.character, gift=ITEMS[key][1],
                        preferred=preferred, gain=gain, perfect_link_advanced=advanced,
                        profile=profile_for(self.character))), timeout=11)
                except Exception as exc:
                    log_event('AI・贈り物のお礼', '定型文に切り替え', error=exc, 操作ID=interaction.id)
            embed = self.embed(status)
            embed.add_field(name='【ジョージの一言】', value=discord.utils.escape_markdown(comment), inline=False)
            await interaction.edit_original_response(embed=embed, view=self)
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
