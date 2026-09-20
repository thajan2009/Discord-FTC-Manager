"""Mongo access with a short-lived in-memory cache. DB `wilsodc`, collection `wilsodc`.

Design (every data-loss path closed):
- Reads hit memory and refresh from Mongo at most every CACHE_TTL seconds,
  so displays are never more than a few seconds stale and message-heavy paths
  (custom-command fallback, autocomplete) stay fast.
- Writes ALWAYS go straight to Mongo (write-through). There is deliberately
  NO background writer: a periodic full-doc rewrite is exactly what used to
  silently undo website changes with a stale snapshot.
- Saves merge: bot-owned sections (finance/inventory/commands) come from the
  bot's copy; website-owned sections (teams/settings) are preserved from the
  database, so a stale copy can never wipe website changes.
- Handlers that mutate data use get_fresh_guild_doc (bypass cache).
- Per-guild asyncio locks serialize concurrent access.
- Compound (+unique) index on (_type, guild_id); inserts tolerate races.

Document shapes:
  {_type: "guild", guild_id: str, teams: [{id, name, aliases[]}],
   settings: {finance_mode, inventory_mode},  # everyone|admins
   finance: {teams: {<team_id|_server>: {debts:[], sources:[]}}},
   inventory: {teams: {<team_id|_server>: {items: [{name,qty}]}}},
   commands: [{trigger, response}]}
  {_type: "global_commands", entries: {trigger: response}}
"""

import asyncio
import difflib
import os
import time
import uuid

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

_client: AsyncIOMotorClient | None = None

_cache: dict[str, dict] = {}
_cache_at: dict[str, float] = {}
CACHE_TTL = 10.0
_locks: dict[str, asyncio.Lock] = {}

_last_write: dict[str, float] = {}
MIN_WRITE_GAP = 1.5


_globals_cache: dict = {}


def claim_write_slot(guild_id: int | str) -> bool:
    """Generous per-server save throttle: at most one DB write per guild every
    MIN_WRITE_GAP seconds. Reads are unlimited (served from memory)."""
    now = time.monotonic()
    gid = str(guild_id)
    if now - _last_write.get(gid, 0.0) < MIN_WRITE_GAP:
        return False
    _last_write[gid] = now
    return True
_globals_at: float = 0.0
GLOBALS_TTL = 300


def get_collection():
    global _client
    if _client is None:
        uri = os.getenv("MONGO_URI")
        if not uri:
            raise RuntimeError("MONGO_URI env var is missing. Set it in Bot-hosting.net Env tab.")
        _client = AsyncIOMotorClient(uri)
    # DB name wilsodc, collection wilsodc (per user request)
    return _client["wilsodc"]["wilsodc"]


async def ensure_indexes() -> None:
    try:
        col = get_collection()
        await col.create_index([("_type", 1), ("guild_id", 1)], name="type_guild", background=True)
    except Exception as exc:
        print(f"[mongo] index skipped: {exc}")
    try:
        col = get_collection()
        await col.create_index(
            [("_type", 1), ("guild_id", 1)], name="type_guild_unique", unique=True, background=True
        )
    except Exception as exc:
        # Fails only if duplicate guild docs already exist; harmless either way.
        print(f"[mongo] unique index skipped: {exc}")


def _lock_for(gid: str) -> asyncio.Lock:
    lock = _locks.get(gid)
    if lock is None:
        lock = asyncio.Lock()
        _locks[gid] = lock
    return lock


def _cache_store(gid: str, doc: dict) -> dict:
    _cache[gid] = doc
    _cache_at[gid] = time.monotonic()
    return doc


def _cache_fresh(gid: str) -> dict | None:
    doc = _cache.get(gid)
    if doc is not None and time.monotonic() - _cache_at.get(gid, 0) < CACHE_TTL:
        return doc
    return None


def _defaults(doc: dict) -> dict:
    doc.setdefault("teams", [])
    doc.setdefault("settings", {}).setdefault("finance_mode", "everyone")
    doc["settings"].setdefault("inventory_mode", "everyone")
    doc["settings"].setdefault("outreach_mode", "everyone")
    doc["settings"].setdefault("currency", "£")
    doc.setdefault("finance", {}).setdefault("teams", {})
    doc.setdefault("inventory", {}).setdefault("teams", {})
    doc.setdefault("outreach", {}).setdefault("teams", {})
    doc.setdefault("commands", [])
    return doc


def new_id() -> str:
    return uuid.uuid4().hex[:8]


async def get_guild_doc(guild_id: int | str) -> dict:
    """Memory hit when fresh (< CACHE_TTL old), else one indexed re-read."""
    gid = str(guild_id)
    doc = _cache_fresh(gid)
    if doc is not None:
        return doc
    async with _lock_for(gid):
        doc = _cache_fresh(gid)
        if doc is not None:
            return doc
        col = get_collection()
        doc = await col.find_one({"_type": "guild", "guild_id": gid})
        if doc is None:
            doc = {
                "_type": "guild",
                "guild_id": gid,
                "teams": [],
                "settings": {"finance_mode": "everyone", "inventory_mode": "everyone"},
                "finance": {"teams": {}},
                "inventory": {"teams": {}},
                "commands": [],
            }
            try:
                await col.insert_one(doc)
            except DuplicateKeyError:
                # Lost an insert race: someone else created it first.
                doc = await col.find_one({"_type": "guild", "guild_id": gid}) or doc
        return _cache_store(gid, _defaults(doc))


# Sections the bot owns. On save, these come from the bot's copy; everything
# else (teams, settings — managed on the website) is preserved from the DB so
# a stale in-memory copy can never wipe website changes.
BOT_OWNED = ("finance", "inventory", "commands")


async def save_guild_doc(doc: dict) -> None:
    """Write-through with merge: bot-owned sections win, website-owned sections
    (teams/settings) are preserved from the database. Serialized per guild."""
    gid = str(doc.get("guild_id", ""))
    async with _lock_for(gid):
        col = get_collection()
        fresh = await col.find_one({"_type": "guild", "guild_id": gid})
        if fresh is None:
            fresh = doc
        else:
            for key in BOT_OWNED:
                if key in doc:
                    fresh[key] = doc[key]
        _defaults(fresh)
        _cache_store(gid, fresh)
        await col.replace_one({"_id": fresh["_id"]}, fresh, upsert=True)


async def get_fresh_guild_doc(guild_id: int | str) -> dict:
    """Bypass the cache and re-read from Mongo. Use this in every handler that
    MUTATES data, so concurrent website edits are never overwritten."""
    gid = str(guild_id)
    async with _lock_for(gid):
        col = get_collection()
        doc = await col.find_one({"_type": "guild", "guild_id": gid})
        if doc is None:
            # Create without re-entering the lock (get_guild_doc would deadlock).
            doc = {
                "_type": "guild",
                "guild_id": gid,
                "teams": [],
                "settings": {"finance_mode": "everyone", "inventory_mode": "everyone"},
                "finance": {"teams": {}},
                "inventory": {"teams": {}},
                "commands": [],
            }
            try:
                await col.insert_one(doc)
            except DuplicateKeyError:
                doc = await col.find_one({"_type": "guild", "guild_id": gid}) or doc
        return _cache_store(gid, _defaults(doc))


async def get_global_commands() -> dict:
    global _globals_cache, _globals_at
    if _globals_cache and time.monotonic() - _globals_at < GLOBALS_TTL:
        return _globals_cache
    col = get_collection()
    doc = await col.find_one({"_type": "global_commands"})
    if doc is None:
        doc = {"_type": "global_commands", "entries": {"hello": "Hello! Use !bal to check balance."}}
        await col.insert_one(doc)
    _globals_cache = doc.get("entries", {})
    _globals_at = time.monotonic()
    return _globals_cache


def start_flush_loop() -> None:
    # Retired: every mutation already writes straight through to Mongo, so a
    # periodic full-doc rewrite is pure risk (it once undid website changes
    # with a stale snapshot). Kept as a no-op so older entrypoints still boot.
    print("[mongo] cache TTL 10s, merge-save v3 active, no background writer")


def suggest_team(doc: dict, query: str | None) -> str | None:
    """Closest team name/alias to a mistyped query, or None."""
    if not query:
        return None
    options: dict[str, str] = {}
    for t in doc.get("teams", []):
        name = t.get("name", "")
        if name:
            options[name.lower()] = name
        for a in t.get("aliases", []):
            options.setdefault(str(a).lower(), name)
    if not options:
        return None
    match = difflib.get_close_matches(query.strip().lower(), list(options), n=1, cutoff=0.6)
    return options[match[0]] if match else None


def resolve_team(doc: dict, query: str | None):
    """Return (team_id, team_name) or (None, None). '_server' = combined pseudo-team."""
    if not query:
        return None, None
    q = query.strip().lower()
    for t in doc.get("teams", []):
        names = [t.get("name", "").lower()] + [a.lower() for a in t.get("aliases", [])]
        if q in names:
            return t["id"], t.get("name", q)
    return None, None
