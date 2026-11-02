"""所持する贈り物をボタンで表示し、選んだ贈り物をお気に入りへ渡す。"""

import asyncio
import time
from operation_logging import event as log_event

import discord

from presents import ITEMS, affection_display, affection_limit, link_label, GiftConfirmationRequired
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
        self.deadline = time.monotonic() + 180
        self.confirmation = None
        self.build_buttons()

    def build_buttons(self):
        self.timeout = max(0.01, self.deadline - time.monotonic())
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
            embed.description += '\n好感度は上限の100だぜ。贈る前に確認するぞ。贈り物は1個消費するが、好感度は上がらないぜ。'
            if not self.perfect:
                embed.description += '\n喜ばれる贈り物を贈ると、パーフェクトリンクを達成できるぜ！'
        if not self.keys:
            embed.add_field(name='手持ちのプレゼントはないぜ！', value='/おみくじ や /クイズ で1日1個もらえるぞ。', inline=False)
        elif show_instruction:
            embed.description += '\n\nボタンを押すと1個贈るぜ！'
        embed.set_footer(text='操作期限：画面を開いてから3分。期限後は /お気に入り プレゼント で開き直せるぜ。')
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('自分の /お気に入り プレゼント から開いてくれ！', ephemeral=True)
            return False
        if self.expired or time.monotonic() >= self.deadline:
            self.expired = True
            await interaction.response.send_message('時間切れだぜ。もう一度コマンドから開いてくれ！', ephemeral=True)
            return False
        return True

    async def give(self, interaction, key, *, confirmation=None):
        await interaction.response.defer()
        async with self.lock:
            if self.expired or time.monotonic() >= self.deadline or interaction.id in self.processed or (confirmation is not None and (
                    confirmation.finished or confirmation is not self.confirmation)):
                log_event('プレゼント', '消費せず見送り', reason='操作期限切れ、または処理済みの操作', 操作ID=interaction.id)
                return
            if self.points >= 100 and confirmation is None:
                await self.ask_confirmation(interaction, key)
                return
            try:
                options = {'confirmed': True} if confirmation is not None else {}
                gain, points, perfect = await asyncio.to_thread(self.store.give, self.user_id, interaction.id, self.character, key, **options)
            except GiftConfirmationRequired as exc:
                self.points, self.perfect = 100, exc.perfect
                await self.ask_confirmation(interaction, key)
                return
            except (ValueError, MemoryUnavailable) as exc:
                log_event('プレゼント', '保存失敗・結果未確定', error=exc, 操作ID=interaction.id)
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            self.processed.add(interaction.id)
            if confirmation is not None:
                confirmation.finished = True
                confirmation.stop()
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
            self.timeout = max(0.01, self.deadline - time.monotonic())
            await interaction.edit_original_response(embed=embed, view=self)
            await notify_titles(interaction, self.store)

    async def ask_confirmation(self, interaction, key):
        if self.confirmation is not None:
            self.confirmation.finished = True
            self.confirmation.stop()
        prompt = GiftConfirmationView(self, key)
        self.confirmation = prompt
        prompt.message = self.message
        await interaction.edit_original_response(embed=prompt.embed(), view=prompt)

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


class GiftConfirmationView(discord.ui.View):
    def __init__(self, parent, key):
        super().__init__(timeout=max(0.01, parent.deadline - time.monotonic()))
        self.parent, self.key = parent, key
        self.finished = False
        self.message = None

    def embed(self):
        embed = discord.Embed(title='プレゼントの確認', color=0xE2AD48,
            description=f'**{discord.utils.escape_markdown(self.parent.character)}**に'
                        f'**{ITEMS[self.key][1]} ×1**を贈るぜ。\n\n'
                        'これ以上は好感度が上がらないが、本当にあげるのか？\n'
                        '「贈る」を押すと1個消費するぜ。')
        if not self.parent.perfect and self.key in preferred_items(self.parent.character):
            embed.description += '\n喜ばれる贈り物なので、パーフェクトリンクを達成できるぜ！'
        embed.set_footer(text='キャンセル・期限切れでは消費しません。元のプレゼント画面の操作期限は延長されません。')
        return embed

    async def interaction_check(self, interaction):
        return await self.parent.interaction_check(interaction)

    @discord.ui.button(label='贈る', style=discord.ButtonStyle.primary)
    async def confirm(self, interaction, button):
        await self.parent.give(interaction, self.key, confirmation=self)

    @discord.ui.button(label='キャンセル', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.defer()
        async with self.parent.lock:
            if self.finished or self.parent.expired or time.monotonic() >= self.parent.deadline or self is not self.parent.confirmation:
                return
            self.finished = True
            self.stop()
            self.parent.build_buttons()
            await interaction.edit_original_response(embed=self.parent.embed('プレゼントは消費していないぜ。'), view=self.parent)

    async def on_timeout(self):
        async with self.parent.lock:
            if self.finished or self is not self.parent.confirmation:
                return
            self.finished = True
            self.parent.expired = True
            for button in self.parent.children:
                button.disabled = True
            if self.message:
                try:
                    await self.message.edit(embed=self.parent.embed('時間切れだぜ。プレゼントは消費していないぞ。もう一度コマンドから開いてくれ！'), view=self.parent)
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
