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

    print(f"[MESSAGE] {message.guild} | #{message.channel} | "
          f"{message.author} : {message.content}")

    emoji = "👍"
    #await message.add_reaction(emoji)
    
TOKEN = os.getenv("DISCORD_TOKEN")
# Web サーバの立ち上げ
keep_alive()
client.run(TOKEN)
