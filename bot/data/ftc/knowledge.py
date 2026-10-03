"""Local FTC knowledge retrieval over the collections/ markdown files.

Each entry block looks like:
    ## Title
    - url: https://...
    - tags: a, b, c
    - summary: one line

retrieval: simple token overlap scoring — fast, no dependencies.
"""

import re
from pathlib import Path

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


def search(query: str, k: int = 3) -> list[dict]:
    terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    scored = []
    for e in _ALL:
        hay = f"{e['name']} {e['tags']} {e['summary']}".lower()
        score = sum(1 for t in terms if t in hay)
        if score:
            scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:k]]
