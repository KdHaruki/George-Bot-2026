"""Local profile quizzes with a daily reward for a correct answer."""
import asyncio
import logging
import random

import discord
from progress import progressData
from presents import ITEMS
from registered_memory import MemoryUnavailable


HINT_FIELDS = [('progressWorld', '出身世界'), ('progressLike', '好きなもの'),
               ('progressDisLike', '苦手なもの'), ('progressInscription', '座右の銘'),
               ('progressDetail1', 'プロフィール')]


def hints_for(record):
    names = [record.get('progressName', '')] + [record.get(f'progressNickname{i}', '') for i in range(1, 4)]
    hints = []
    for key, label in HINT_FIELDS:
        value = record.get(key, '').strip()
        for name in sorted(filter(None, names), key=len, reverse=True):
            value = value.replace(name, '？？？')
        if value:
            hints.append((label, value[:900]))
    return hints


class QuizView(discord.ui.View):
    def __init__(self, user_id, records=None, rng=random, reward_store=None, reward_id=None):
        super().__init__(timeout=180)
        records = list({r['progressName']: r for r in (records if records is not None else progressData)
                        if r.get('progressName') and hints_for(r)}.values())
        self.answer = rng.choice(records)
        others = rng.sample([r for r in records if r['progressName'] != self.answer['progressName']], 3)
        choices = [self.answer] + others
        rng.shuffle(choices)
        self.user_id = user_id
        self.reward_store, self.reward_id = reward_store, reward_id
        self.hints = hints_for(self.answer)
        rng.shuffle(self.hints)
        self.revealed = 1
        self.message = None
        self.lock = asyncio.Lock()
        self.finished = False
        self.attempts = 0
        for record in choices:
            button = discord.ui.Button(label=record['progressName'][:80], style=discord.ButtonStyle.secondary)
            name = record['progressName']

            async def callback(interaction, name=name, button=button):
                await self.choose(interaction, name, button)

            button.callback = callback
            self.add_item(button)

    def embed(self, status='このヒントのプログレスは誰だ？'):
        embed = discord.Embed(title='アンジュクイズ', description=status, color=0xB06FE0)
        for label, value in self.hints[:self.revealed]:
            embed.add_field(name=f'【{label}】', value=discord.utils.escape_markdown(value), inline=False)
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('自分の /クイズ で挑戦してくれ！', ephemeral=True)
            return False
        return True

    async def choose(self, interaction, name, button):
        await interaction.response.defer()
        async with self.lock:
            if self.finished or button.disabled:
                return
            self.attempts += 1
            if name == self.answer['progressName']:
                self.finished = True
                self.revealed = len(self.hints)
                for item in self.children:
                    item.disabled = True
                button.style = discord.ButtonStyle.success
                status = f'正解！ {name}だぜ！（{self.attempts}回目）'
                self.stop()
                if self.reward_store is not None:
                    try:
                        reward = await asyncio.to_thread(self.reward_store.claim_quiz, self.user_id, self.reward_id, self.attempts)
                        if reward['granted']:
                            emoji, label = ITEMS[reward['item']]
                            status += f'\n\n{emoji} **{label}** ×1を獲得！\n`/お気に入り プレゼント`で贈れるぜ！'
                        else:
                            status += '\n\n今日のクイズ報酬は受け取り済みだぜ。次は日本時間の0時から！'
                    except MemoryUnavailable:
                        logging.warning('Quiz reward save failed')
                        status += '\n\n保存先との通信で報酬の受け取りを確認できなかったぜ。所持品を確認して、まだならあとでクイズに再挑戦してくれ。'
            else:
                button.disabled = True
                button.style = discord.ButtonStyle.danger
                self.revealed = min(len(self.hints), self.revealed + 1)
                status = '惜しい！ ヒントを追加したぜ。もう一度選んでくれ！'
            await interaction.edit_original_response(embed=self.embed(status), view=self)

    async def on_timeout(self):
        async with self.lock:
            if self.finished:
                return
            self.finished = True
            for item in self.children:
                item.disabled = True
            if self.message:
                try:
                    await self.message.edit(embed=self.embed(f'時間切れ！ 正解は{self.answer["progressName"]}だぜ。'), view=self)
                except discord.HTTPException:
                    pass


def register_quiz_commands(bot):
    @bot.tree.command(name='クイズ', description='ヒント付き4択クイズ。正解で1日1回プレゼント、少ない回答でレア率アップ')
    async def quiz(interaction: discord.Interaction):
        view = QuizView(interaction.user.id, reward_store=bot.present_store, reward_id=interaction.id)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
        view.message = await interaction.original_response()
