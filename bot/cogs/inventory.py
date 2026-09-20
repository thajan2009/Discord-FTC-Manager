"""Inventory system — HYBRID (works as !inv and /inventory).

- !inv / !inventory [team]  ==  /inventory [team]
- No arg -> global combined (all teams). With arg -> single team.
- Buttons: +Item / Set Qty / Remove. Modals ask for the item NAME exactly as
  shown — no IDs anywhere.
- Permission from web toggle settings.inventory_mode: everyone|admins
"""

import discord
from discord import app_commands
from discord.ext import commands

import asyncio
from datetime import datetime, timezone

from db.mongo import claim_write_slot, get_fresh_guild_doc, get_guild_doc, resolve_team, save_guild_doc, suggest_team
from utils.perms import can_manage
from utils.branding import brand
from utils.sheets import CACHE_TTL as SHEET_TTL
from utils.sheets import fetch_sheet_items, peek_sheet


def inventory_source(doc: dict) -> str:
    s = doc.get("settings", {})
    if s.get("inventory_source") == "sheet" and (s.get("sheet_url") or "").strip():
        return "sheet"
    return "manual"


READONLY_MSG = ("Inventory is linked to a spreadsheet and read-only. "
                "Unlink it on the website to edit here.")


def team_stock(doc: dict, team_id: str | None) -> dict:
    teams = doc.setdefault("inventory", {}).setdefault("teams", {})
    key = team_id or "_server"
    return teams.setdefault(key, {"items": []})


def combined_stock(doc: dict) -> list:
    valid = {t.get("id") for t in doc.get("teams", [])} | {"_server"}
    merged: dict[str, dict] = {}
    for key, bucket in doc.get("inventory", {}).get("teams", {}).items():
        if key not in valid:
            continue
        for item in bucket.get("items", []):
            name = item.get("name", "?")
            key = name.lower()
            if key not in merged:
                merged[key] = {"name": name, "qty": 0}
            merged[key]["qty"] += int(item.get("qty", 0))
    return sorted(merged.values(), key=lambda x: x["name"].lower())


def find_item(items: list, name: str) -> dict | None:
    """Find by exact name, case-insensitive."""
    want = name.strip().lower()
    for it in items:
        if it.get("name", "").lower() == want:
            return it
    return None


PAGE_SIZE = 10
BASE_SORTS = [
    ("name", "Name (A-Z)"),
    ("qty_desc", "Stock (high first)"),
    ("qty_asc", "Stock (low first)"),
]
BASE_PRIORITY = ["name", "qty_desc", "qty_asc"]
MAX_SELECT_OPTIONS = 25


def tag_options(items: list) -> list:
    """One dropdown entry per vendor/category value in the data, so you can
    sort by tags like goBILDA or Structure Parts."""
    vendors = sorted({i["vendor"] for i in items if i["vendor"]}, key=str.lower)
    cats = sorted({i["category"] for i in items if i["category"]}, key=str.lower)
    opts = [(f"vendor:{v}", f"Vendor: {v}"[:100]) for v in vendors]
    opts += [(f"category:{c}", f"Category: {c}"[:100]) for c in cats]
    return opts


def normalize_items(items: list) -> list:
    norm = []
    for it in items:
        try:
            qty = int(it.get("qty", 0))
        except (TypeError, ValueError):
            qty = 0
        norm.append({
            "name": str(it.get("name", "?")),
            "qty": qty,
            "vendor": str(it.get("vendor", "") or ""),
            "category": str(it.get("category", "") or ""),
        })
    return norm


class InvSortSelect(discord.ui.Select):
    """Multi-select: base sorts plus one entry per vendor/category tag."""

    def __init__(self, options: list, current: list):
        super().__init__(
            placeholder="Sort by… (pick several)",
            options=[
                discord.SelectOption(label=label, value=key, default=(key in current))
                for key, label in options
            ],
            min_values=1,
            max_values=len(options),
        )

    async def callback(self, interaction: discord.Interaction):
        order = [k for k, _ in self.view.all_options]
        self.view.sort = [k for k in order if k in self.values] or ["name"]
        self.view.page = 0
        await interaction.response.edit_message(embed=self.view.render(), view=self.view)


class InvBrowseView(discord.ui.View):
    """Paged inventory with multi-select sorting, plus management buttons
    (omitted in read-only sheet mode)."""

    def __init__(self, items: list, team_id: str | None, team_label: str, title: str, readonly: bool = False):
        super().__init__(timeout=300)
        self.all_items = normalize_items(items)
        self.team_id = team_id
        self.team_label = team_label
        self.title = title
        self.readonly = readonly
        self.sort = ["name"]
        self.page = 0
        self.all_options = (BASE_SORTS + tag_options(self.all_items))[:MAX_SELECT_OPTIONS]
        self.opt_labels = dict(self.all_options)
        # NOTE: must use the unbound View.add_item — self.add_item is the
        # "+ Item" Button attribute shadowing it (decorator quirk).
        discord.ui.View.add_item(self, InvSortSelect(self.all_options, self.sort))
        if readonly:
            # Hide management buttons outright (same shadowing reason).
            for btn in (self.add_item, self.set_qty, self.remove_item):
                discord.ui.View.remove_item(self, btn)

    def _tags_of(self, item: dict) -> set:
        tags = set()
        if item["vendor"]:
            tags.add(f"vendor:{item['vendor']}")
        if item["category"]:
            tags.add(f"category:{item['category']}")
        return tags

    def ordered(self) -> list:
        items = list(self.all_items)
        tags = [k for k in self.sort if k.startswith(("vendor:", "category:"))]
        base = [k for k in BASE_PRIORITY if k in self.sort] or ["name"]

        def apply(seq: list) -> list:
            for key in reversed(base):
                if key == "name":
                    seq.sort(key=lambda x: x["name"].lower())
                elif key == "qty_desc":
                    seq.sort(key=lambda x: -x["qty"])
                elif key == "qty_asc":
                    seq.sort(key=lambda x: x["qty"])
            return seq

        if not tags:
            return apply(items)
        picked = set(tags)
        return apply([i for i in items if self._tags_of(i) & picked]) + \
            apply([i for i in items if not self._tags_of(i) & picked])

    def render(self) -> discord.Embed:
        items = self.ordered()
        total = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = min(max(0, self.page), total - 1)
        chunk = items[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        e = discord.Embed(title=self.title, colour=discord.Colour.teal())
        if not chunk:
            e.description = "Nothing here yet — press + Item." if not self.readonly else "The linked sheet has no items."
        else:
            lines = []
            for it in chunk:
                name = f"**~~{it['name']}~~**" if it["qty"] <= 0 else f"**{it['name']}**"
                lines.append(f"{name} - {it['qty']}")
                bits = [b for b in (it["vendor"], it["category"]) if b]
                if bits:
                    lines.append(" · ".join(bits))
            e.description = "\n".join(lines)
        brand(e, "FTCManager Inventory")
        sort_names = ", ".join(self.opt_labels.get(k, k) for k in self.sort)
        if self.readonly:
            e.set_footer(text=f"Page {self.page + 1}/{total} · Sorted: {sort_names} · Read-only — managed in the linked Google Sheet.")
        else:
            e.set_footer(text=f"Page {self.page + 1}/{total} · Sorted: {sort_names} · Type names exactly to change/remove.")
        self._prev.disabled = self.page <= 0
        self._next.disabled = self.page >= total - 1
        return e

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.grey, row=1)
    async def _prev(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.page -= 1
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.grey, row=1)
    async def _next(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.page += 1
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="+ Item", style=discord.ButtonStyle.green, row=1)
    async def add_item(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if self.readonly:
            return await interaction.response.send_message(READONLY_MSG, ephemeral=True)
        doc = await get_guild_doc(interaction.guild_id)
        mode = doc.get("settings", {}).get("inventory_mode", "everyone")
        if not can_manage(mode, interaction.user):
            return await interaction.response.send_message(
                "Only admins can manage inventory.", ephemeral=True
            )
        if inventory_source(doc) == "sheet":
            return await interaction.response.send_message(READONLY_MSG, ephemeral=True)
        view = ItemPickView(
            doc.get("teams", []), self.team_id,
            interaction.message, self.team_id, self.team_label,
        )
        await interaction.response.send_message(
            "Add item to which team?", view=view, ephemeral=True
        )

    @discord.ui.button(label="Set Qty", style=discord.ButtonStyle.blurple, row=2)
    async def set_qty(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if self.readonly:
            return await interaction.response.send_message(READONLY_MSG, ephemeral=True)
        await interaction.response.send_modal(
            SetQtyModal(self.team_id, self.team_label, orig_msg=interaction.message)
        )

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.red, row=2)
    async def remove_item(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if self.readonly:
            return await interaction.response.send_message(READONLY_MSG, ephemeral=True)
        await interaction.response.send_modal(
            RemoveItemModal(self.team_id, self.team_label, orig_msg=interaction.message)
        )


async def team_autocomplete(interaction: discord.Interaction, current: str):
    try:
        doc = await get_guild_doc(interaction.guild_id)
        return [
            app_commands.Choice(name=t.get("name", "?"), value=t.get("name", "?"))
            for t in doc.get("teams", [])
            if current.lower() in t.get("name", "").lower()
        ][:25]
    except Exception:
        return []


class AddItemModal(discord.ui.Modal):
    def __init__(
        self, team_id: str | None, team_label: str,
        orig_msg: discord.Message | None = None,
        scope_id: str | None = None, scope_label: str = "server",
        picker_msg: discord.Message | None = None,
    ):
        super().__init__(title=f"Add item — {team_label}")
        self.team_id = team_id
        self.orig_msg = orig_msg
        self.scope_id = scope_id
        self.scope_label = scope_label
        self.picker_msg = picker_msg
        self.name_input = discord.ui.TextInput(label="Item name", max_length=60)
        self.qty_input = discord.ui.TextInput(label="Quantity", placeholder="e.g. 5", max_length=10)
        self.add_item(self.name_input)
        self.add_item(self.qty_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_fresh_guild_doc(interaction.guild_id)
        mode = doc.get("settings", {}).get("inventory_mode", "everyone")
        if not can_manage(mode, interaction.user):
            return await interaction.response.send_message("Only admins can manage inventory.", ephemeral=True)
        try:
            qty = int(str(self.qty_input.value).strip())
        except ValueError:
            return await interaction.response.send_message("Quantity must be a whole number.", ephemeral=True)
        name = self.name_input.value.strip()
        stock = team_stock(doc, self.team_id)
        existing = find_item(stock.get("items", []), name)
        if inventory_source(doc) == "sheet":
            return await interaction.response.send_message(READONLY_MSG, ephemeral=True)
        now = datetime.now(timezone.utc).isoformat()
        if existing is not None:
            existing["qty"] = int(existing.get("qty", 0)) + qty
            existing["by"] = interaction.user.display_name
            existing["at"] = now
            msg = f"Added {qty} to `{existing['name']}` (now x {existing['qty']})."
        else:
            stock.setdefault("items", []).append({
                "name": name, "qty": qty,
                "by": interaction.user.display_name, "at": now,
            })
            msg = f"Added `{name}` x {qty}."
        if not claim_write_slot(interaction.guild_id):
            return await interaction.response.send_message(
                "Easy — a save just went through. Wait a second and try again.", ephemeral=True
            )
        await save_guild_doc(doc)
        await refresh_inventory_msg(self.orig_msg, interaction.guild, self.scope_id, self.scope_label)
        if self.picker_msg is not None:
            try:
                await self.picker_msg.delete()
            except Exception:
                pass
        await interaction.response.send_message(msg, ephemeral=True)


class SetQtyModal(discord.ui.Modal):
    def __init__(
        self, team_id: str | None, team_label: str,
        orig_msg: discord.Message | None = None,
    ):
        super().__init__(title=f"Set quantity — {team_label}")
        self.team_id = team_id
        self.team_label = team_label
        self.orig_msg = orig_msg
        self.name_input = discord.ui.TextInput(label="Item name (exact, as shown)", max_length=60)
        self.qty_input = discord.ui.TextInput(label="New quantity", max_length=10)
        self.add_item(self.name_input)
        self.add_item(self.qty_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_fresh_guild_doc(interaction.guild_id)
        mode = doc.get("settings", {}).get("inventory_mode", "everyone")
        if not can_manage(mode, interaction.user):
            return await interaction.response.send_message("Only admins can manage inventory.", ephemeral=True)
        try:
            qty = int(str(self.qty_input.value).strip())
        except ValueError:
            return await interaction.response.send_message("Quantity must be a whole number.", ephemeral=True)
        stock = team_stock(doc, self.team_id)
        item = find_item(stock.get("items", []), self.name_input.value)
        if inventory_source(doc) == "sheet":
            return await interaction.response.send_message(READONLY_MSG, ephemeral=True)
        if item is None:
            return await interaction.response.send_message(
                f"No item named `{self.name_input.value.strip()}` here. Type it exactly as shown in `!inv`.",
                ephemeral=True,
            )
        item["qty"] = qty
        if not claim_write_slot(interaction.guild_id):
            return await interaction.response.send_message(
                "Easy — a save just went through. Wait a second and try again.", ephemeral=True
            )
        await save_guild_doc(doc)
        await refresh_inventory_msg(self.orig_msg, interaction.guild, self.team_id, self.team_label)
        await interaction.response.send_message(f"Set `{item['name']}` x {qty}.", ephemeral=True)


class RemoveItemModal(discord.ui.Modal):
    def __init__(
        self, team_id: str | None, team_label: str,
        orig_msg: discord.Message | None = None,
    ):
        super().__init__(title=f"Remove item — {team_label}")
        self.team_id = team_id
        self.team_label = team_label
        self.orig_msg = orig_msg
        self.name_input = discord.ui.TextInput(label="Item name (exact, as shown)", max_length=60)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_fresh_guild_doc(interaction.guild_id)
        mode = doc.get("settings", {}).get("inventory_mode", "everyone")
        if not can_manage(mode, interaction.user):
            return await interaction.response.send_message("Only admins can manage inventory.", ephemeral=True)
        name = self.name_input.value.strip()
        if inventory_source(doc) == "sheet":
            return await interaction.response.send_message(READONLY_MSG, ephemeral=True)
        if self.team_id is None:
            buckets = list(doc.get("inventory", {}).get("teams", {}).values())
        else:
            buckets = [team_stock(doc, self.team_id)]
        removed = 0
        for bucket in buckets:
            kept = [it for it in bucket.get("items", []) if it.get("name", "").lower() != name.lower()]
            removed += len(bucket.get("items", [])) - len(kept)
            bucket["items"] = kept
        if not removed:
            return await interaction.response.send_message(
                f"No item named `{name}` here. Type it exactly as shown in `!inv`.", ephemeral=True
            )
        if not claim_write_slot(interaction.guild_id):
            return await interaction.response.send_message(
                "Easy — a save just went through. Wait a second and try again.", ephemeral=True
            )
        await save_guild_doc(doc)
        await refresh_inventory_msg(self.orig_msg, interaction.guild, self.team_id, self.team_label)
        await interaction.response.send_message(f"Removed `{name}`.", ephemeral=True)


class ItemTeamPickSelect(discord.ui.Select):
    """Dropdown to choose which team an item is added to (modals can't hold one).
    Picking only stages the choice — the tick button below confirms it."""

    def __init__(self, teams: list, current_id: str | None):
        options = [
            discord.SelectOption(
                label="Server (combined)", value="_server", default=current_id is None
            )
        ]
        for t in teams[:24]:
            options.append(
                discord.SelectOption(
                    label=str(t.get("name", "?"))[:100],
                    value=t["id"],
                    default=(t["id"] == current_id),
                )
            )
        super().__init__(placeholder="Choose a team… (or just press ✅)", options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        self.view.selected = None if value == "_server" else value
        await interaction.response.defer_update()


class ItemPickView(discord.ui.View):
    """Team dropdown + tick to confirm. Tick accepts the preselected default,
    so on the combined view you just press ✅ for Server."""

    def __init__(
        self, teams: list, current_id: str | None,
        orig_msg: discord.Message | None, scope_id: str | None, scope_label: str,
    ):
        super().__init__(timeout=120)
        self.orig_msg = orig_msg
        self.scope_id = scope_id
        self.scope_label = scope_label
        self.selected = current_id  # None = Server (combined)
        self.add_item(ItemTeamPickSelect(teams, current_id))

    @discord.ui.button(label="✅", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        doc = await get_guild_doc(interaction.guild_id)
        if self.selected is None:
            team_id, label = None, "server"
        else:
            team_id = self.selected
            label = next(
                (t.get("name", "?") for t in doc.get("teams", []) if t.get("id") == self.selected),
                "?",
            )
        await interaction.response.send_modal(
            AddItemModal(
                team_id, label,
                orig_msg=self.orig_msg, scope_id=self.scope_id, scope_label=self.scope_label,
                picker_msg=interaction.message,
            )
        )


async def refresh_inventory_msg(
    msg: discord.Message | None, guild: discord.Guild, scope_id: str | None, scope_label: str
) -> None:
    """Re-render the original inventory message after a change."""
    if msg is None:
        return
    try:
        doc = await get_guild_doc(guild.id)
        if scope_id is None:
            items = combined_stock(doc)
            title = f"Inventory — {guild.name} (combined)"
        else:
            items = team_stock(doc, scope_id).get("items", [])
            title = f"Inventory — {scope_label}"
        view = InvBrowseView(items, scope_id, scope_label, title)
        await msg.edit(embed=view.render(), view=view)
    except Exception:
        pass  # original message deleted — ephemeral confirm still sent


async def _sent_message(ctx: commands.Context, sent: object) -> discord.Message | None:
    """Best-effort Message object for a just-sent reply (prefix and slash)."""
    if isinstance(sent, discord.Message):
        return sent
    inter = getattr(ctx, "interaction", None)
    if inter is not None:
        try:
            return await inter.original_response()
        except Exception:
            return None
    return None


async def _fill_sheet_view(
    url: str, title: str, message: discord.Message, view: "InvBrowseView | None"
) -> None:
    """Background refresh: fetch the newest sheet, then update the message."""
    try:
        data = await asyncio.to_thread(fetch_sheet_items, url, True)
    except Exception:
        return
    try:
        if data.get("error"):
            err = discord.Embed(title=title, colour=discord.Colour.teal())
            err.description = data["error"]
            err.set_footer(text="Read-only — managed in the linked Google Sheet.")
            await message.edit(embed=err, view=None)
            return
        if view is None:
            view = InvBrowseView(data["items"], None, "server", title, readonly=True)
        else:
            view.all_items = normalize_items(data["items"])
            view.page = 0
        await message.edit(embed=view.render(), view=view)
    except Exception:
        pass


class Inventory(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="inventory", aliases=["inv"], description="Show inventory. Optional team.")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @app_commands.describe(team="Team name or alias (empty = combined)")
    @app_commands.autocomplete(team=team_autocomplete)
    @commands.guild_only()
    async def inventory(self, ctx: commands.Context, team: str | None = None):
        doc = await get_guild_doc(ctx.guild.id)
        if inventory_source(doc) == "sheet":
            # Instant feel: answer from the last collected version right away,
            # then fetch the newest sheet in the background and update.
            url = (doc.get("settings", {}).get("sheet_url") or "").strip()
            title = f"Inventory — {ctx.guild.name} (Google Sheet)"
            cached, age = peek_sheet(url)
            if cached is None:
                loading = discord.Embed(title=title, colour=discord.Colour.teal())
                loading.description = "Fetching the sheet…"
                msg = await _sent_message(ctx, await ctx.send(embed=loading))
                if msg is not None:
                    asyncio.create_task(_fill_sheet_view(url, title, msg, None))
                return
            view = InvBrowseView(cached["items"], None, "server", title, readonly=True)
            msg = await _sent_message(ctx, await ctx.send(embed=view.render(), view=view))
            if age is not None and age > SHEET_TTL and msg is not None:
                asyncio.create_task(_fill_sheet_view(url, title, msg, view))
            return
        if team:
            team_id, team_name = resolve_team(doc, team)
            if not team_id:
                names = ", ".join(t.get("name", "?") for t in doc.get("teams", [])) or "no teams yet"
                msg = f"Team '{team}' not found. Available: {names}"
                hint = suggest_team(doc, team)
                if hint:
                    msg += f" Did you mean '{hint}'?"
                if ctx.interaction:
                    return await ctx.interaction.response.send_message(msg, ephemeral=True)
                return await ctx.send(msg)
            view = InvBrowseView(
                team_stock(doc, team_id).get("items", []),
                team_id, team_name, f"Inventory — {team_name}",
            )
        else:
            view = InvBrowseView(
                combined_stock(doc), None, "server",
                f"Inventory — {ctx.guild.name} (combined)",
            )
        # hybrid: ctx.send works for both prefix and slash (deferred-safe)
        if not doc.get("teams"):
            await ctx.send(
                "No teams yet — admins, add up to 3 on the website, then use !inv <team>.",
                embed=view.render(), view=view,
            )
        else:
            await ctx.send(embed=view.render(), view=view)

    @commands.command(name="invdel")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def invdel(self, ctx: commands.Context, *, name: str):
        """!invdel <exact name> — remove an item by typing its name exactly."""
        doc = await get_fresh_guild_doc(ctx.guild.id)
        if inventory_source(doc) == "sheet":
            return await ctx.send(READONLY_MSG)
        mode = doc.get("settings", {}).get("inventory_mode", "everyone")
        if not can_manage(mode, ctx.author):
            return await ctx.send("Only admins can manage inventory.")
        removed = 0
        for bucket in doc.get("inventory", {}).get("teams", {}).values():
            kept = [it for it in bucket.get("items", []) if it.get("name", "").lower() != name.strip().lower()]
            removed += len(bucket.get("items", [])) - len(kept)
            bucket["items"] = kept
        if not removed:
            return await ctx.send(f"No item named `{name}`. Type it exactly as shown in `!inv`.")
        await save_guild_doc(doc)
        await ctx.send(f"Removed `{name.strip()}`.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Inventory(bot))
