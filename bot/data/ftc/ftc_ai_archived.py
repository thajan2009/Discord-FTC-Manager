"""ARCHIVED — legacy FTC AI (https://ftc-cmchatbot.firstinspires.org/) backend.

Kept for reference only. The bot no longer routes any question here — !ftcask
now answers entirely via Groq (see pipeline.py). Do NOT remove: you can swap
back by restoring pipeline.answer() to call `ask_ftc_ai` and `fuse_with_groq`.
"""

from __future__ import annotations

import uuid

import aiohttp

CHAT_URL = "https://ftc-chatbot-api.pdx-prod.ftclive.org/api/v1/chat/"
_TIMEOUT = aiohttp.ClientTimeout(total=60)


async def ask_ftc_ai(question: str) -> str:
    payload = {
        "user_message": question,
        "conversation_history": [],
        "session_id": str(uuid.uuid4()),
        "user_message_uuid": None,
    }
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as sess:
        async with sess.post(CHAT_URL, json=payload, headers={"Content-Type": "application/json"}) as resp:
            if resp.status != 200:
                raise RuntimeError(f"FTC AI HTTP {resp.status}")
            data = await resp.json(content_type=None)
            return (data.get("bot_response") or "").strip()
