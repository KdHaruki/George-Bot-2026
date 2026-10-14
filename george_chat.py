"""Bounded, per-channel/per-user Gemini conversations."""

import asyncio
import os
from collections import OrderedDict
from dataclasses import dataclass, field

from google import genai
from google.genai import types


SYSTEM_INSTRUCTION = """あなたはDiscord Botのジョージです。
日本語で、親しみやすく明るい口調で話します。一人称は「俺」、語尾は自然に「だぜ」「だな」などを使います。
女の子を呼ぶときは「かわいこっちゃん」と呼びます。相手の性別がわからない場合は決めつけません。
相手の話を聞き、質問には正確でわかりやすく答えてください。回答は原則800文字以内にまとめます。
知らない設定や事実を作り上げず、わからないことはわからないと伝えてください。
Discord上の操作やプログレス検索を実行したと偽らないでください。
プログレス検索は「/progress 名前」または「@ジョージ pro 名前」で利用できます。
"""


class ChatUnavailable(Exception):
    pass


class ChatBusy(Exception):
    pass


@dataclass
class Conversation:
    history: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class GeorgeChat:
    def __init__(self):
        key = os.getenv("GEMINI_API_KEY", "").strip()
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=45000)) if key else None
        self.model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        self.sessions = OrderedDict()

    def _session(self, key):
        if key not in self.sessions:
            if len(self.sessions) >= 256:
                for old_key, session in list(self.sessions.items()):
                    if not session.lock.locked():
                        del self.sessions[old_key]
                        break
                else:
                    raise ChatBusy()
            self.sessions[key] = Conversation()
        self.sessions.move_to_end(key)
        return self.sessions[key]

    async def reply(self, key, text):
        if self.client is None:
            raise ChatUnavailable()
        session = self._session(key)
        if session.lock.locked():
            raise ChatBusy()
        async with session.lock:
            user = types.Content(role="user", parts=[types.Part(text=text)])
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=[*session.history, user],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        max_output_tokens=2048,
                    ),
                ),
                timeout=60,
            )
            answer = (response.text or "").strip()
            if not answer:
                return "うまく返事を作れなかったぜ。言い方を変えて、もう一度話しかけてくれ！"
            answer = answer[:6000]
            session.history = [*session.history, user,
                               types.Content(role="model", parts=[types.Part(text=answer)])][-20:]
            return answer

    def reset(self, key):
        session = self.sessions.get(key)
        if session and session.lock.locked():
            raise ChatBusy()
        self.sessions.pop(key, None)

    async def close(self):
        if self.client:
            await self.client.aio.aclose()
            self.client.close()
