"""Minimal async Groq chat client (OpenAI-compatible, aiohttp, no new deps).

Set GROQ_TOKEN in .env. Model defaults below; override with
GROQ_ROUTER_MODEL / GROQ_ANSWER_MODEL if needed.
"""

import json
import os

import aiohttp

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ROUTER_MODEL = os.getenv("GROQ_ROUTER_MODEL", "openai/gpt-oss-20b")
ANSWER_MODEL = os.getenv("GROQ_ANSWER_MODEL", "openai/gpt-oss-20b")  # fast, cheap; swap to gpt-oss-120b for depth
FALLBACK_MODEL = os.getenv(f"GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b")  # tried if primary errors/rates out
TIMEOUT = aiohttp.ClientTimeout(total=60)


async def chat(messages: list[dict], *, model: str, temperature: float = 0.0, max_tokens: int = 800, reasoning_effort: str | None = "low") -> str:
    token = os.getenv("GROQ_TOKEN")
    if not token:
        raise RuntimeError("GROQ_TOKEN not set")
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    attempts = []
    for m in (model, FALLBACK_MODEL, "openai/gpt-oss-20b"):
        if m and m not in attempts:
            attempts.append(m)
    async with aiohttp.ClientSession(timeout=TIMEOUT) as sess:
        last_err = None
        for attempt_model in attempts:
            payload = {"model": attempt_model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort
            async with sess.post(
                GROQ_URL,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            ) as resp:
                body = await resp.text()
                if resp.status == 200:
                    return json.loads(body)["choices"][0]["message"]["content"]
                last_err = f"Groq HTTP {resp.status}: {body[:200]}"
                if resp.status == 429:
                    continue  # rate-limited: try the next, more generous sibling
                if resp.status == 404 and attempt_model != FALLBACK_MODEL:
                    continue
                # other 4xx: don't hammer siblings on a bad request
                if attempt_model != "openai/gpt-oss-20b":
                    continue
                raise RuntimeError(last_err)
        raise RuntimeError(last_err or "Groq request failed")