"""FTC answer pipeline for !ftcask — Groq only.

Routes each question (heuristic first, then the tiny Groq router model):
- manual: Groq answering authoritative rules questions (game manual focused).
- wilso:  Groq; code/design -> qwen3.8-27b, general -> openai/gpt-oss-20b.
- both:   Groq (openai/gpt-oss-120b) producing one fused rules+engineering answer.

The old FTC AI manual chatbot is archived in bot/data/ftc/ftc_ai_archived.py.
"""

import re
import time

from data.ftc.knowledge import category, page_text, search
from data.wilso_prompt import SYSTEM_PROMPT, build_user_message
from utils.groq import ROUTER_MODEL, chat

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


def _sources_block(hits: list[dict]) -> str:
    links = [h for h in hits if str(h.get("url", "")).startswith("http")]
    if not links:
        return ""
    lines = "\n".join(f"- [{h['name']}]({h['url']})" for h in links[:4])
    return f"\n\n**Sources:**\n{lines}"


async def _resources_with_excerpts(hits: list[dict]) -> str:
    lines = "\n".join(f"- {h['name']}: {h['summary']} ({h['url'] or h['source']})" for h in hits)
    out = f"\n\nRelevant resources:\n{lines}" if lines else ""
    excerpts = []
    for h in hits[:2]:
        body = await page_text(h.get("url", ""), max_len=2600)
        if body:
            excerpts.append(f"### {h['name']} ({h['url']})\n{body}")
    if excerpts:
        out += "\n\nRelevant source excerpts (use only from here, do not fabricate):\n" + "\n\n".join(excerpts)
    return out


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
ANSWER_BIG = "openai/gpt-oss-120b"  # strongest general reasoner on the free tier
ANSWER_SMALL = "openai/gpt-oss-20b"  # fast, cheap default


async def _rules_answer(question: str) -> str:
    hits = search(question, k=4)
    extra = await _resources_with_excerpts(hits)
    system = (
        SYSTEM_PROMPT
        + "\n\nThis is an OFFICIAL RULES question. Be authoritative and cite the current Game Manual where confident. "
        "If no exact rule applies or you are unsure, say so and point the user to the Game Manual / Team Updates."
        + extra
    )
    text = await chat(
        [{"role": "system", "content": system}, {"role": "user", "content": build_user_message(question)}],
        model=ANSWER_BIG,
        temperature=0.2,
        max_tokens=900,
        reasoning_effort="low",
    )
    if not re.search(r"\*\*\s?Sources", text) and hits:
        text += _sources_block(hits)
    return text


async def _wilso_answer(question: str) -> str:
    hits = search(question, k=4)
    excerpts = []
    for h in hits[:2]:  # ground the answer in the actual source pages
        body = await page_text(h.get("url", ""), max_len=2600)
        if body:
            excerpts.append(f"### {h['name']} ({h['url']})\n{body}")
    extra = ""
    if hits:
        lines = "\n".join(f"- {h['name']}: {h['summary']} ({h['url'] or h['source']})" for h in hits)
        extra = f"\n\nRelevant resources:\n{lines}"
    if excerpts:
        extra += "\n\nRelevant source excerpts (use only from here, do not fabricate):\n" + "\n\n".join(excerpts)
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
            model=ANSWER_SMALL,
            temperature=0.3,
            max_tokens=900,
            reasoning_effort="low",
        )
    if not re.search(r"\*\*\s?Sources", text) and hits:  # guarantee a real link footer
        text += _sources_block(hits)
    return text


_FUSED_SYS = (
    SYSTEM_PROMPT
    + "\n\nProduce ONE combined answer for a question that blends rules and engineering: "
    "FIRST LINE is the exact direct answer, then rule citations and concise engineering context/next steps. "
    "Format specifically for Discord per the contract. Never contradict the Game Manual. Keep under 200 words."
)


async def _fused(question: str) -> str:
    hits = search(question, k=4)
    extra = await _resources_with_excerpts(hits)
    text = await chat(
        [
            {"role": "system", "content": _FUSED_SYS + extra},
            {"role": "user", "content": f"Question: {question}\n\nAnswer with the FTC rules and engineering context."},
        ],
        model=ANSWER_BIG,
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

    manual_q = category(q) == "manual"
    if manual_q:
        route = "manual"  # rules/game-manual questions always use the rules answer
    else:
        route = _route_heuristic(q) or await _route_model(q)
        if route == "manual":
            route = "wilso"  # technical question misclassified as rules -> prefer gm0 path
    try:
        if route == "manual":
            text = await _rules_answer(q)
        elif route == "wilso":
            text = await _wilso_answer(q)
        else:
            text = await _fused(q)
    except Exception:
        # Degrade gracefully to the other Groq mode once.
        try:
            text = await (_rules_answer(q) if route == "manual" else _wilso_answer(q))
            route = "wilso" if route == "manual" else "manual"
        except Exception as exc:
            raise RuntimeError(f"Groq backend failed: {exc}") from exc

    _put(cache_key, text)
    return {"route": route, "text": text}
