import discord
import random
import os
from keep_alive import keep_alive

#############################################
# 初期
#############################################
client = discord.Client(intents=discord.Intents.default())

@client.event
async def on_ready():
    print('ログインしました')

#############################################
# メイン処理
#############################################
@client.event
async def on_message(message):
    # Bot本体のメッセージには反応しない。
    if message.author.bot:
        return
    
    # 20%の確率で絵文字を付与する。
    if random.random() < 0.2:
        emojis = ["😆", "😂", "😍", "😭", "😡", "🤔", "😎", "🥺", "👍", "🎉", "👀"]
        emoji = random.choice(emojis)
        await message.add_reaction(emoji)

#############################################
# サーバ立ち上げ
#############################################
TOKEN = os.getenv("DISCORD_TOKEN")
keep_alive()
client.run(TOKEN)