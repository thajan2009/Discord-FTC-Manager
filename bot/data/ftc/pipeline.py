"""FTC answer pipeline for !ftcask.

Routes each question with a tiny Groq model (heuristic first, then llama-3.1-8b),
then answers with the right backend:
- manual: FTC AI chatbot (official Game Manual)
- wilso:  Groq (llama-3.3-70b) + Wilso system prompt + local snippets
- both:   FTC AI answer, then Groq enriches it with Wilso context
Falls back gracefully so the command still works if one backend is down.
"""

import json
import re
import time
import uuid

import aiohttp

from data.ftc.knowledge import search
from data.wilso_prompt import SYSTEM_PROMPT, build_user_message
from utils.groq import ROUTER_MODEL, chat

CHAT_URL = "https://ftc-chatbot-api.pdx-prod.ftclive.org/api/v1/chat/"
TIMEOUT = aiohttp.ClientTimeout(total=60)

_MANUAL = re.compile(r"\b(rule|legal|violation|penalty|inspection|inspect|scoring|score|manual|qa|q&a|foul|card|disqualif|disabled|team update|legality|constraint|timeout|tie)\b", re.I)
_WILSO = re.compile(r"\b(intake|outtake|arm|slide|turret|lift|drivetrain|mecanum|onshape|cad|gearbox|belt|chain|bearing|programming|java|kotlin|opmode|auto|autonomous|teleop|pedro|pedropath|ivy|nextftc|camera|apriltag|odometry|localization|sponsorship|outreach|finance|portfolio|design|mechanism|path|follower|pid|vision|opencv|hardware|wiring|sensor|motor|servo|control hub)\b", re.I)

_cache: dict[str, tuple[float, str]] = {}
CACHE_TTL = 600  # 10 min


def _cached(key: str):
    hit = _cache.get(key)
    return hit[1] if hit and (time.time() - hit[0]) < CACHE_TTL else None


def _put(key: str, value: str):
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = (time.time(), value)


async def _ask_ftc_ai(question: str) -> str:
    payload = {
        "user_message": question,
        "conversation_history": [],
        "session_id": str(uuid.uuid4()),
        "user_message_uuid": None,
    }
    async with aiohttp.ClientSession(timeout=TIMEOUT) as sess:
        async with sess.post(CHAT_URL, json=payload, headers={"Content-Type": "application/json"}) as resp:
            if resp.status != 200:
                raise RuntimeError(f"FTC AI HTTP {resp.status}")
            data = await resp.json(content_type=None)
            return (data.get("bot_response") or "").strip()


def _sources_block(hits: list[dict]) -> str:
    links = [h for h in hits if str(h.get("url", "")).startswith("http")]
    if not links:
        return ""
    lines = "\n".join(f"- [{h['name']}]({h['url']})" for h in links[:4])
    return f"\n\n**Sources:**\n{lines}"


def _route_heuristic(q: str) -> str | None:
    m = len(_MANUAL.findall(q))
    w = len(_WILSO.findall(q))
    if m and not w:
        return "manual"
    if w and not m:
        return "wilso"
    return None  # ambiguous -> let the small model decide


_ROUTER_SYS = (
    "You are a fast router. Reply with exactly one word: 'manual', 'wilso', or 'both'.\n"
    "manual = official game rules, scoring, robot constraints, legality, inspections, penalties, Q&A.\n"
    "wilso = robot design, CAD, mechanisms, hardware, programming, path planning, strategy, outreach, finance, Onshape.\n"
    "both = the question genuinely needs an official rule plus engineering context."
)


async def _route_model(q: str) -> str:
    try:
        out = await chat(
            [{"role": "system", "content": _ROUTER_SYS}, {"role": "user", "content": q}],
            model=ROUTER_MODEL,
            temperature=0.0,
            max_tokens=8,
            reasoning_effort="none",
        )
        out = out.strip().lower()
        for label in ("manual", "wilso", "both"):
            if label in out:
                return label
        return "both"
    except Exception:
        return "both"


_CODE = re.compile(r"\b(pedro|pedropath|ivy|nextftc|java|kotlin|opmode|autonomous|auto|code|coding|teleop|path|follower|pid|apriltag|opencv|vision|odometry|localization|telemetry|android)\b", re.I)
ANSWER_QWEN = "qwen/qwen3.8-27b"  # best coding/agentic model on the free tier


async def _wilso_answer(question: str) -> str:
    hits = search(question, k=3)
    extra = ""
    if hits:
        lines = "\n".join(f"- {h['name']}: {h['summary']} ({h['url'] or h['source']})" for h in hits)
        extra = f"\n\nRelevant Wilso resources (mention only if helpful):\n{lines}"
    if _CODE.search(question):  # programming/path-planning -> strongest coding model
        text = await chat(
            [{"role": "system", "content": SYSTEM_PROMPT + extra}, {"role": "user", "content": build_user_message(question)}],
            model=ANSWER_QWEN,
            temperature=0.6,
            max_tokens=900,
            reasoning_effort="none",  # instruct mode: no hidden thinking cost
        )
    else:  # general design/mechanism -> fast small model
        text = await chat(
            [{"role": "system", "content": SYSTEM_PROMPT + extra}, {"role": "user", "content": build_user_message(question)}],
            model="openai/gpt-oss-20b",
            temperature=0.3,
            max_tokens=900,
            reasoning_effort="low",
        )
    if not re.search(r"\*\*\s?Sources", text) and hits:  # guarantee a real link footer
        text += _sources_block(hits)
    return text


_FUSION_SYS = (
    SYSTEM_PROMPT
    + "\n\nYou are given the official FTC manual answer (authoritative). "
    "Produce ONE combined answer: the FIRST LINE is the exact direct answer to the question, "
    "then one blank line, then concise Wilso/engineering context and practical next steps. "
    "Format specifically for Discord (as per the contract). Never contradict the manual. Keep under 200 words."
)


async def _fused(question: str) -> str:
    manual = await _ask_ftc_ai(question)
    hits = search(question, k=3)
    extra = ""
    if hits:
        res = "\n".join(f"- {h['name']}: {h['summary']} ({h['url'] or h['source']})" for h in hits)
        extra = f"\n\nRelevant Wilso resources (link any you actually use):\n{res}"
    text = await chat(
        [
            {"role": "system", "content": _FUSION_SYS + extra},
            {"role": "user", "content": f"Question: {question}\n\nOfficial manual answer:\n{manual}"},
        ],
        model="openai/gpt-oss-120b",  # fusion needs the strongest reasoner
        temperature=0.3,
        max_tokens=700,
        reasoning_effort="low",
    )
    if not re.search(r"\*\*\s?Sources", text) and hits:
        text += _sources_block(hits)
    return text


async def answer(question: str) -> dict:
    """Return {'route': str, 'text': str} for !ftcask."""
    q = question.strip()[:500]
    cache_key = q.lower()
    hit = _cached(cache_key)
    if hit:
        return {"route": "cached", "text": hit}

    route = _route_heuristic(q) or await _route_model(q)
    try:
        if route == "manual":
            text = await _ask_ftc_ai(q)
        elif route == "wilso":
            text = await _wilso_answer(q)
        else:
            text = await _fused(q)
    except Exception:
        # Degrade gracefully: if the chosen backend fails, try the other side once.
        try:
            text = await (_wilso_answer(q) if route == "manual" else _ask_ftc_ai(q))
            route = "wilso" if route == "manual" else "manual"
        except Exception as exc:
            raise RuntimeError(f"Both backends failed: {exc}") from exc

    _put(cache_key, text)
    return {"route": route, "text": text}
