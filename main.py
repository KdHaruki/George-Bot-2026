import discord
from discord import app_commands
import random
import os
import progress as progress_module
from keep_alive import keep_alive

########################################
# Botクラス
########################################

class MyClient(discord.Client):

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

client = MyClient()

########################################
# 起動確認
########################################

@client.event
async def on_ready():
    print("ログインしました")

########################################
# /progress プログレス検索
########################################

@client.tree.command(
    name="progress",
    description="プログレス検索"
)
@app_commands.describe(name="検索する名前")

async def progress(interaction: discord.Interaction, name: str):

    result = progress_module.progressSearch(name)

    await interaction.response.send_message(result)

########################################
# /world 世界一覧
########################################

@client.tree.command(
    name="world",
    description="世界別プログレス一覧"
)

@app_commands.describe(world="世界を選択")

@app_commands.choices(world=[
    app_commands.Choice(name="青の世界", value=0),
    app_commands.Choice(name="黒の世界", value=1),
    app_commands.Choice(name="赤の世界", value=2),
    app_commands.Choice(name="白の世界", value=3),
    app_commands.Choice(name="緑の世界", value=4),
    app_commands.Choice(name="全ての世界", value=5),
])

async def world(interaction: discord.Interaction, world: app_commands.Choice[int]):

    result = progress_module.progressSearchAll(world.value)

    await interaction.response.send_message(result)

########################################
# メッセージイベント
########################################

@client.event
async def on_message(message):

    if message.author.bot:
        return

    # メンションされたら返信
    if client.user in message.mentions:
        await message.channel.send("なに？")

    # 20%でリアクション
    if random.random() < 0.2:
        emojis = ["😆","😂","😍","😭","🤔","😎","🥺","👍","🎉","👀"]
        await message.add_reaction(random.choice(emojis))

########################################
# サーバ起動
########################################

TOKEN = os.getenv("DISCORD_TOKEN")

keep_alive()

client.run(TOKEN)