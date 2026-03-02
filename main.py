import discord
import os
from keep_alive import keep_alive

client = discord.Client(intents=discord.Intents.default())

##################################################
# Bot起動時
##################################################
@client.event
async def on_ready():
    print('ログインしました')

##################################################
# メイン処理（メッセージ受信）
##################################################
@client.event
async def on_message(message):
    # メッセージ送信者がBotだった場合は無視する
    if message.author.bot:
        return
    # 「/neko」と発言したら「にゃーん」が返る処理
    if message.content == '/neko':
        await message.channel.send('にゃーん')

##################################################
# サーバ立ち上げ
##################################################
TOKEN = os.getenv("DISCORD_TOKEN")
keep_alive()
client.run(TOKEN)
