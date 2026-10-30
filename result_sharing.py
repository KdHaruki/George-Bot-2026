"""Owner-initiated public snapshots. No rewards, DB writes or public controls."""
import asyncio
from dataclasses import dataclass, field

import discord

from operation_logging import event as log_event


@dataclass
class ShareState:
    attempted: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ShareButton(discord.ui.Button):
    def __init__(self, owner_id, payload, *, label='結果をみんなに公開', enabled=True,
                 state=None, row=None, channel_id=None):
        self.owner_id, self.payload = owner_id, payload
        self.state = state if state is not None else ShareState()
        self.channel_id = channel_id
        super().__init__(label='公開済み' if self.state.attempted else label,
                         style=discord.ButtonStyle.secondary, row=row,
                         disabled=not enabled or self.state.attempted)

    async def callback(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('この結果を開いた本人だけが公開できるぜ！', ephemeral=True)
            return
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message('公開はサーバーのチャンネルで使ってくれ！', ephemeral=True)
            return
        if self.channel_id is not None and interaction.channel.id != self.channel_id:
            await interaction.response.send_message('結果を開いたチャンネルで公開してくれ！', ephemeral=True)
            return
        await interaction.response.defer()
        async with self.state.lock:
            if self.state.attempted or self.disabled:
                return
            try:
                embeds, files = self.payload()
            except Exception as exc:
                log_event('結果の公開', '公開用データの準備に失敗', error=exc, 操作ID=interaction.id)
                await interaction.followup.send('公開用の画像や結果を準備できなかったぜ。画面を開き直して試してくれ！', ephemeral=True)
                return
            if not embeds:
                return
            # Never retry an uncertain send: it may already have reached Discord.
            self.state.attempted = True
            self.disabled = True
            self.label = '公開済み'
            name = discord.utils.escape_markdown(getattr(interaction.user, 'display_name', 'ユーザー'))
            try:
                batches, batch, length = [], [], 0
                for embed in embeds:
                    if batch and (len(batch) == 10 or length + len(embed) > 6000):
                        batches.append(batch)
                        batch, length = [], 0
                    batch.append(embed.copy())
                    length += len(embed)
                batches.append(batch)
                for index, batch in enumerate(batches):
                    await interaction.channel.send(content=f'**{name}** が結果を公開したぜ！' if index == 0 else None,
                        embeds=batch, files=files if index == 0 else [], allowed_mentions=discord.AllowedMentions.none())
                log_event('結果の公開', 'チャンネルへの投稿完了', 操作ID=interaction.id)
            except Exception as exc:
                self.label = '公開結果を確認してください'
                log_event('結果の公開', '送信結果を確認できない・再送しない', error=exc, 操作ID=interaction.id)
                await interaction.followup.send('公開を完了したか確認できなかったぜ。チャンネルを確認してくれ。重複防止のため、このボタンからは再送しないぞ。', ephemeral=True)
            finally:
                for file in files:
                    file.close()
                try:
                    await interaction.edit_original_response(view=self.view)
                except discord.HTTPException:
                    pass


class ShareView(discord.ui.View):
    def __init__(self, owner_id, payload, *, enabled=True, channel_id=None):
        super().__init__(timeout=180)
        self.message = None
        self.add_item(ShareButton(owner_id, payload, enabled=enabled, channel_id=channel_id))

    async def on_timeout(self):
        for button in self.children:
            button.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
