"""Google Sheets inventory source (read-only).

A server can link a stock sheet instead of tracking items manually. Expected
layout — header row plus data rows:
    Required: "Part Name", "Current Stock"
    Optional sorters: "Vendor", "Category" (used for sorting/filtering when present)

Matching is case-insensitive with a few common aliases. The sheet must be
shared as "Anyone with the link can view". Fetches are cached for 60s per URL
so !inv spam never hammers Google.
"""

import csv
import io
import re
import time
import urllib.request

CACHE_TTL = 60
_cache: dict[str, tuple[float, dict]] = {}

NAME_KEYS = {"part name", "partname", "part", "item", "item name"}
STOCK_KEYS = {"current stock", "stock", "qty", "quantity", "count", "on hand", "onhand"}
VENDOR_KEYS = {"vendor", "supplier", "seller", "store", "shop"}
CATEGORY_KEYS = {"category", "type", "group", "class"}


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", (header or "").strip().lower())


def extract_sheet(url: str) -> tuple[str, str] | None:
    """Return (spreadsheet_id, gid) from any Google Sheets URL, else None."""
    if not url:
        return None
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9-_]+)", url)
    if not m:
        return None
    gid = "0"
    g = re.search(r"[?&#]gid=(\d+)", url)
    if g:
        gid = g.group(1)
    return m.group(1), gid


def _parse_qty(raw: str) -> int:
    m = re.search(r"-?\d+(\.\d+)?", str(raw or "").replace(",", ""))
    if not m:
        return 0
    try:
        return int(float(m.group(0)))
    except ValueError:
        return 0


def fetch_sheet_items(url: str, force: bool = False) -> dict:
    """Fetch + parse a shared Google Sheet. Returns dict with:
    items: [{name, qty, vendor, category}], has_vendor, has_category, error.
    force=True skips the cache read (result is still stored)."""
    parsed = extract_sheet(url or "")
    if not parsed:
        return {"items": [], "has_vendor": False, "has_category": False,
                "error": "That doesn't look like a Google Sheets link."}
    sheet_id, gid = parsed
    cache_key = f"{sheet_id}/{gid}"
    if not force:
        hit = _cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]

    result: dict = {"items": [], "has_vendor": False, "has_category": False, "error": None}
    try:
        export = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        req = urllib.request.Request(export, headers={"User-Agent": "FTCManager/1.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            text = res.read().decode("utf-8-sig")
    except Exception:
        result["error"] = ("Couldn't open the sheet. Make sure link sharing is on "
                           "('Anyone with the link can view').")
        return result

    rows = [r for r in csv.reader(io.StringIO(text)) if any((c or "").strip() for c in r)]
    if not rows:
        result["error"] = "The sheet looks empty."
        return result

    headers = [_norm(h) for h in rows[0]]

    def col(keys: set) -> int | None:
        for i, h in enumerate(headers):
            if h in keys:
                return i
        return None

    name_i = col(NAME_KEYS)
    stock_i = col(STOCK_KEYS)
    vendor_i = col(VENDOR_KEYS)
    cat_i = col(CATEGORY_KEYS)
    if name_i is None or stock_i is None:
        result["error"] = ("Couldn't find the required columns. The first row needs "
                           "'Part Name' and 'Current Stock'.")
        return result

    items = []
    for row in rows[1:]:
        name = (row[name_i] if name_i < len(row) else "").strip()
        if not name:
            continue
        items.append({
            "name": name,
            "qty": _parse_qty(row[stock_i] if stock_i < len(row) else ""),
            "vendor": (row[vendor_i].strip() if vendor_i is not None and vendor_i < len(row) else ""),
            "category": (row[cat_i].strip() if cat_i is not None and cat_i < len(row) else ""),
        })
    items.sort(key=lambda x: ((x["category"] or "").lower(), (x["vendor"] or "").lower(), x["name"].lower()))
    result.update({
        "items": items,
        "has_vendor": vendor_i is not None,
        "has_category": cat_i is not None,
    })
    _cache[cache_key] = (time.monotonic(), result)
    return result


def peek_sheet(url: str) -> tuple[dict | None, float | None]:
    """Cached result with NO network. Returns (result, age_seconds),
    or (None, None) when nothing is cached yet."""
    parsed = extract_sheet(url or "")
    if not parsed:
        return None, None
    hit = _cache.get(f"{parsed[0]}/{parsed[1]}")
    if not hit:
        return None, None
    return hit[1], time.monotonic() - hit[0]
