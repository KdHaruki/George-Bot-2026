import discord
import os
from keep_alive import keep_alive

client = discord.Client(intents=discord.Intents.default())

@client.event
async def on_ready():
    print('ログインしました')

@client.event
async def on_message(message):
    if message.author.bot:
        return  # Botの発言は無視
    
    if message.content == '/info':
        emoji = "👍"
        await message.add_reaction(emoji)
        await message.channel.send(message)
    
TOKEN = os.getenv("DISCORD_TOKEN")
# Web サーバの立ち上げ
keep_alive()
client.run(TOKEN)
