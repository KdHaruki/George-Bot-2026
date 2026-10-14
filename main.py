import discord
from discord import app_commands
import random
import os
import logging
import re
from george_chat import GeorgeChat, ChatBusy, ChatUnavailable, describe_chat_error
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
        self.george_chat = GeorgeChat()

    async def setup_hook(self):
        await self.tree.sync()

    async def close(self):
        try:
            await self.george_chat.close()
        finally:
            await super().close()

client = MyClient()

########################################
# 起動確認
########################################

@client.event
async def on_ready():
    print("ログインしました")

########################################
# progress オートコンプリート
########################################

async def progress_autocomplete(interaction: discord.Interaction, current: str):

    current = current.lower()

    starts = []
    contains = []

    for p in progress_module.progressData:

        name = p["progressName"]
        name_lower = name.lower()

        if current == "":
            starts.append(name)

        elif name_lower.startswith(current):
            starts.append(name)

        elif current in name_lower:
            contains.append(name)

    results = starts + contains

    return [
        app_commands.Choice(name=r, value=r)
        for r in results[:25]
    ]
########################################
# /progress プログレス検索
########################################

@client.tree.command(
    name="progress",
    description="プログレス検索"
)
@app_commands.describe(name="名前または世界")
@app_commands.autocomplete(name=progress_autocomplete)

async def progress(interaction: discord.Interaction, name: str):

    name = name.strip()

    world_map = {
        "青":0,"青の":0,"青世界":0,"青の世界":0,
        "黒":1,"黒の":1,"黒世界":1,"黒の世界":1,
        "赤":2,"赤の":2,"赤世界":2,"赤の世界":2,
        "白":3,"白の":3,"白世界":3,"白の世界":3,
        "緑":4,"緑の":4,"緑世界":4,"緑の世界":4,
        "全":5,"全ての":5,"全世界":5,"全ての世界":5
    }

    if name in world_map:
        result = progress_module.progressSearchAll(world_map[name])
    else:
        result = progress_module.progressSearch(name)

    await interaction.response.send_message(result)

########################################
# メッセージイベント
########################################

@client.event
async def on_message(message):

    if message.author.bot:
        return

    # メンションされた場合
    if client.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        parts = message.content.split()
        if len(parts) >= 3 and parts[1].lower() in ["pro", "progress", "プロ", "プログレス"]:
            keyword = parts[2]
            world_map = {
                "青":0,"青の":0,"青世界":0,"青の世界":0,
                "黒":1,"黒の":1,"黒世界":1,"黒の世界":1,
                "赤":2,"赤の":2,"赤世界":2,"赤の世界":2,
                "白":3,"白の":3,"白世界":3,"白の世界":3,
                "緑":4,"緑の":4,"緑世界":4,"緑の世界":4,
                "全":5,"全ての":5,"全世界":5,"全ての世界":5
            }

            if keyword in world_map:
                result = progress_module.progressSearchAll(world_map[keyword])
            else:
                result = progress_module.progressSearch(keyword)
            await message.channel.send(result)
        else:
            text = re.sub(rf"<@!?{client.user.id}>", "", message.content).strip()
            key = (message.channel.id, message.author.id)
            try:
                if text.lower() in ("reset", "リセット"):
                    client.george_chat.reset(key)
                    answer = "この場所でのキミとの会話をリセットしたぜ！"
                elif not text:
                    answer = "何を話そうか？ メンションに続けて話しかけてくれ！ 検索は /progress、会話のリセットは「リセット」だぜ。"
                else:
                    async with message.channel.typing():
                        answer = await client.george_chat.reply(key, text)
            except ChatUnavailable:
                answer = "会話機能はまだ準備中だぜ。管理者にGEMINI_API_KEYの設定をお願いしてくれ！"
            except ChatBusy:
                answer = "今、返事を考えてるぜ！ 少し待ってから話しかけてくれ。"
            except Exception as exc:
                # Do not log API keys, message contents, or provider error bodies.
                diagnostic, answer = describe_chat_error(exc)
                logging.warning("Gemini request failed: %s", diagnostic)
            for offset in range(0, len(answer), 1900):
                await message.channel.send(answer[offset:offset + 1900], allowed_mentions=discord.AllowedMentions.none())

    # 20%でリアクション
    if random.random() < 0.2:
        emojis = ["😆","😂","😍","😭","🤔","😎","🥺","👍","🎉","👀"]
        await message.add_reaction(random.choice(emojis))

########################################
# サーバ起動
########################################

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKENを環境変数に設定してください")
    keep_alive()
    client.run(TOKEN)

__all__ = ["progressData","progressSearch","progressSearchAll"]
