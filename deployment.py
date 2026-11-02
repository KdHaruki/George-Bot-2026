"""デプロイ時に実行中のコマンドの終了を待ち、新規操作には更新中の案内を返す。"""

import asyncio

import discord
from discord import app_commands


class DeploymentState:
    def __init__(self):
        self.draining = False
        self.tasks = set()

    def begin_shutdown(self):
        if self.draining:
            return False
        self.draining = True
        return True

    def track_command(self):
        # interaction_checkとコマンド本体は同じタスクで実行される。
        # 完了通知だけに頼らず、例外や中断の場合にも集合から除く。
        task = asyncio.current_task()
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def wait_for_commands(self, timeout=20):
        tasks = {task for task in self.tasks if not task.done() and task is not asyncio.current_task()}
        if not tasks:
            return 0
        # 時間切れでもここでは取消しない。保存中の処理を即座に中断しないため。
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        return len(pending)


class DeploymentCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction):
        state = self.client.deployment
        if state.draining:
            if interaction.type == discord.InteractionType.autocomplete:
                await interaction.response.autocomplete([])
            else:
                await interaction.response.send_message(
                    '今は更新の切り替え中だぜ。少し待ってから、もう一度コマンドを試してくれ！',
                    ephemeral=True,
                )
            return False
        state.track_command()
        return True
