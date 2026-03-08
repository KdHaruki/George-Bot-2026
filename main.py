import discord
from discord import app_commands
import random
import os
import re_progress
from keep_alive import keep_alive

########################################
# Botクラス
########################################

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

client = MyClient()

#############################################
# 初期
#############################################
client = discord.Client(intents=discord.Intents.default())

@client.event
async def on_ready():
    print('ログインしました')

########################################
# /progress プログレス検索
########################################

@client.tree.command(
    name="progress",
    description="プログレスを検索する"
)
@app_commands.describe(name="検索する名前")
async def progress(interaction: discord.Interaction, name: str):

    result = re_progress.progressSearch(name)

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

    result = re_progress.progressSearchAll(world.value)

    await interaction.response.send_message(result)

#############################################
# メイン処理
#############################################
@client.event
async def on_message(message):
    # Bot本体のメッセージには反応しない。
    if message.author.bot:
        return
    
    # メンションされていたら必ず反応
    if client.user in message.mentions:
#        await message.channel.send(message.content.split())
        command = message.content.split(1)
        if command in ['pro','progress','プロ','プログレス']:

            if len(discordMesArray) > 2:
                world = discordMesArray[2]

                if world in ['青の世界','あおのせかい','青のせかい','あおの世界']:
                    georgeMessage = "青の世界のプログレス一覧"

                elif world in ['黒の世界','くろのせかい','黒のせかい','くろの世界']:
                    georgeMessage = "黒の世界のプログレス一覧"

                elif world in ['赤の世界','あかのせかい','赤のせかい','あかの世界']:
                    georgeMessage = "赤の世界のプログレス一覧"

                elif world in ['白の世界','しろのせかい','白のせかい','しろの世界']:
                    georgeMessage = "白の世界のプログレス一覧"

                elif world in ['緑の世界','みどりのせかい','緑のせかい','みどりの世界']:
                    georgeMessage = "緑の世界のプログレス一覧"

                else:
                    georgeMessage = f"{world} を検索"

            else:
                georgeMessage = "検索ワードが足りないよ"
    # 20%でリアクション
    if random.random() < 0.2:
        emojis = ["😆", "😂", "😍", "😭", "🤔", "😎", "🥺", "👍", "🎉", "👀"]
        await message.add_reaction(random.choice(emojis))

#############################################
# サーバ立ち上げ
#############################################
TOKEN = os.getenv("DISCORD_TOKEN")
keep_alive()
client.run(TOKEN)