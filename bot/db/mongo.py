"""Mongo access with in-memory cache. Uses single DB `wilsodc`, collection `wilsodc`.

Speed design:
- Guild docs live in a process-wide dict after first read. Every command and
  autocomplete hits memory, not the network.
- Writes go through immediately to Mongo (the backup) AND update the cache,
  so a restart never loses data.
- A background task re-saves all cached docs every 60s as a second safety net.
- Per-guild asyncio locks prevent concurrent writes racing each other.
- Compound index on (_type, guild_id) keeps the first read fast.

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

_client: AsyncIOMotorClient | None = None

_cache: dict[str, dict] = {}
_locks: dict[str, asyncio.Lock] = {}
_flush_started = False
FLUSH_INTERVAL = 60

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


def _defaults(doc: dict) -> dict:
    doc.setdefault("teams", [])
    doc.setdefault("settings", {}).setdefault("finance_mode", "everyone")
    doc["settings"].setdefault("inventory_mode", "everyone")
    doc["settings"].setdefault("currency", "£")
    doc.setdefault("finance", {}).setdefault("teams", {})
    doc.setdefault("inventory", {}).setdefault("teams", {})
    doc.setdefault("commands", [])
    return doc


def new_id() -> str:
    return uuid.uuid4().hex[:8]


async def get_guild_doc(guild_id: int | str) -> dict:
    """Fast path: memory hit. Slow path (once per guild per restart): one indexed read."""
    gid = str(guild_id)
    doc = _cache.get(gid)
    if doc is not None:
        return doc
    async with _lock_for(gid):
        doc = _cache.get(gid)
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
            await col.insert_one(doc)
        _cache[gid] = _defaults(doc)
        return _cache[gid]


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
        _cache[gid] = fresh
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
            await col.insert_one(doc)
        _cache[gid] = _defaults(doc)
        return _cache[gid]


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


async def _flush_loop() -> None:
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        try:
            # Route through save_guild_doc so the merge runs: website-owned
            # teams/settings are preserved even if this cache copy is stale.
            for doc in list(_cache.values()):
                try:
                    await save_guild_doc(doc)
                except Exception as exc:
                    print(f"[mongo] backup flush failed: {exc}")
        except Exception as exc:
            print(f"[mongo] backup flush failed: {exc}")


def start_flush_loop() -> None:
    global _flush_started
    if _flush_started:
        return
    _flush_started = True
    asyncio.get_running_loop().create_task(_flush_loop())
    print(f"[mongo] cache on, merge-save v2 active, DB backup flush every {FLUSH_INTERVAL}s")


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
