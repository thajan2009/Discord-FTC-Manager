"""Local FTC knowledge retrieval over the collections/ markdown files.

Each entry block looks like:
    ## Title
    - url: https://...
    - tags: a, b, c
    - summary: one line

retrieval: simple token overlap scoring — fast, no dependencies.
"""

import html as _html
import re
from pathlib import Path

import aiohttp

_ROOT = Path(__file__).resolve().parent / "collections"


def _entries(path: Path) -> list[dict]:
    out = []
    for block in re.split(r"\n(?=## )", path.read_text(encoding="utf-8")):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        name = lines[0].lstrip("#").strip()
        if name.startswith("Official rules") or name.startswith("Programming") or name.startswith("Hardware") or name.startswith("Team resources") or name.startswith("Community") or name.startswith("Official FTC docs"):
            continue  # file header, not an entry
        url, tags, summary = "", "", ""
        for l in lines[1:]:
            if l.startswith("- url:"):
                url = l[6:].strip()
            elif l.startswith("- tags:"):
                tags = l[7:].strip()
            elif l.startswith("- summary:"):
                summary = l[10:].strip()
        if name:
            out.append({"name": name, "url": url, "tags": tags, "summary": summary, "source": path.name})
    return out


_ALL: list[dict] = []
for _p in sorted(_ROOT.glob("*.md")):
    _ALL.extend(_entries(_p))


_MANUAL_TOKENS = re.compile(r"\b(rule|rules|legal|legality|violation|penalty|inspection|inspect|scoring|score|scores|manual|qa|q&a|foul|card|disqualif|disabled|team update|constraint|timeout|tie|biobuzz|pollen|nectar|hive|flower|cell|garden|loading|zone|garden|match|period)\b", re.I)
_CODE_TOKENS = re.compile(r"\b(programming|java|kotlin|opmode|pedro|pedropath|ivy|nextftc|android|sdk|javadoc|encoder|telemetry|loop|fsm|state machine|control loop|pid|path|follower|odometry|localization|vision|camera|apriltag|opencv|autonomous|auto|teleop|code|coding)\b", re.I)
_MANUAL_SOURCES = {"biobuzz.md", "game_manual.md", "official_rules.md", "official_q_and_a.md"}
_CODE_SOURCES = {"programming.md"}
_GM0 = "gm0.md"


def _category(query: str) -> str:
    q = query.lower()
    if _MANUAL_TOKENS.search(q) and not _CODE_TOKENS.search(q):
        return "manual"
    if _CODE_TOKENS.search(q) and not _MANUAL_TOKENS.search(q):
        return "code"
    if _MANUAL_TOKENS.search(q):  # biobuzz/manual clearly stated
        if any(t in q for t in ("biobuzz", "pollen", "nectar", "hive", "violation", "penalty", "inspection", "score", "manual", "rule")):
            return "manual"
        return "code" if _CODE_TOKENS.search(q) else "general"
    return "general"


def category(query: str) -> str:
    """Public: 'manual' | 'code' | 'general' for a query."""
    return _category(query)


def _query_boost(entry: dict, category: str) -> int:
    src = entry.get("source", "")
    if category == "manual":
        if src in _MANUAL_SOURCES:
            return 3
        if src == _GM0:
            return 1
        return 0
    if category == "code":
        if src in _CODE_SOURCES:
            return 3
        if src == _GM0:
            return 2
        return 0
    # general: gm0 first overall
    if src == _GM0:
        return 2
    return 0


_cache_txt: dict[str, str] = {}


def _html_to_text(raw: str) -> str:
    # Prefer the main article body when present (avoids chrome/nav text up front).
    for tag in ("article", "main"):
        m = re.search(r"<" + tag + r"[\s\S]*?</" + tag + ">", raw, flags=re.I)
        if m:
            raw = m.group(0)
            break
    s = re.sub(r"<(script|style|nav|header|footer|aside)[\s\S]*?</\1>", " ", raw, flags=re.I)
    s = re.sub(r"</(p|li|h[1-6]|div|tr|ul|ol)>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


async def page_text(url: str, max_len: int = 2200) -> str:
    """Fetch a gm0/docs page and return its cleaned text (cached). '' on failure."""
    if not url.startswith("http"):
        return ""
    if url in _cache_txt:
        return _cache_txt[url]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
            async with s.get(url, headers={"User-Agent": "FTCManagerBot"}) as r:
                if r.status != 200:
                    _cache_txt[url] = ""
                    return ""
                raw = await r.text()
        txt = _html_to_text(raw)[:max_len]
        _cache_txt[url] = txt
        return txt
    except Exception:
        _cache_txt[url] = ""
        return ""


_STOP = set("a an the i me my we you he she it do does did is are was were can could should will how what when where why be been by for to of in on at and or but if as with from that this as get gets use using us used which who whom from into about would types type advantage advantage disadvantage disadvantage disadvantages advantages disadvantage type types differing different specify specifies specific".split())


def search(query: str, k: int = 4) -> list[dict]:
    terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2 and t not in _STOP}
    category = _category(query)
    scored = []
    for e in _ALL:
        hay = f"{e['name']} {e['tags']} {e['summary']}".lower()
        kw = 0
        for t in terms:
            if t in hay or (t.endswith("s") and t[:-1] in hay) or (f"{t}s" in hay):
                kw += 1
        if not kw:
            continue  # gm0/default boost must never surface irrelevant entries
        scored.append((kw + _query_boost(e, category), e))
    scored.sort(key=lambda x: x[0], reverse=True)
    # diversify: cap per-source, prefer distinct collections, keep it efficient
    out: list[dict] = []
    per_source: dict[str, int] = {}
    for _, e in scored:
        if len(out) >= k:
            break
        if per_source.get(e["source"], 0) >= 3:
            continue
        out.append(e)
        per_source[e["source"]] = per_source.get(e["source"], 0) + 1
    return out
