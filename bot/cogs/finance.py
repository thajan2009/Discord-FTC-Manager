"""Finance system — HYBRID (works as !bal and /balance).

- !bal / !balance / !finance [team]  ==  /balance [team]
- No arg  -> server combined (sum of all teams)
- With arg -> single team resolved by name/alias (web UI defines up to 3 teams)
- Embed: initial £0.00, Debts list + total, Sources/Sponsors list + total, Net
- Buttons: +Debt / +Source / Remove open Modals (names typed exactly, no IDs)
- Permission from web toggle settings.finance_mode: everyone|admins
"""

import discord
from discord import app_commands
from discord.ext import commands

from datetime import datetime, timezone

from db.mongo import claim_write_slot, get_guild_doc, resolve_team, save_guild_doc, suggest_team
from utils.money import clean_symbol, format_money, parse_amount_to_pence
from utils.perms import can_manage


def guild_currency(doc: dict) -> str:
    return clean_symbol(doc.get("settings", {}).get("currency", "£"))


# ---------- helpers ----------

def team_bucket(doc: dict, team_id: str | None) -> dict:
    teams = doc.setdefault("finance", {}).setdefault("teams", {})
    key = team_id or "_server"
    bucket = teams.setdefault(key, {"debts": [], "sources": []})
    bucket.setdefault("debts", [])
    bucket.setdefault("sources", [])
    return bucket


def live_team_keys(doc: dict) -> set:
    """Bucket keys that still belong to a team (plus _server). Stale keys from
    teams deleted before cascade-delete are ignored in combined views."""
    return {t.get("id") for t in doc.get("teams", [])} | {"_server"}


def combined_bucket(doc: dict) -> dict:
    valid = live_team_keys(doc)
    teams = doc.get("finance", {}).get("teams", {})
    debts, sources = [], []
    for key, bucket in teams.items():
        if key not in valid:
            continue
        debts.extend(bucket.get("debts", []))
        sources.extend(bucket.get("sources", []))
    return {"debts": debts, "sources": sources}


def finance_embed(title: str, bucket: dict, symbol: str = "£") -> discord.Embed:
    debts = bucket.get("debts", [])
    sources = bucket.get("sources", [])
    debt_total = sum(int(d.get("amount_p", 0)) for d in debts)
    src_total = sum(int(s.get("amount_p", 0)) for s in sources)
    net = src_total - debt_total
    e = discord.Embed(title=title, colour=discord.Colour.gold())
    e.add_field(name="Starting balance", value=format_money(0, symbol), inline=False)
    if debts:
        lines = [f"{d['name']} — {format_money(d['amount_p'], symbol)}" for d in debts[:25]]
        if len(debts) > 25:
            lines.append(f"+{len(debts) - 25} more — check a single team.")
        e.add_field(name=f"Debts — {format_money(debt_total, symbol)}", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Debts", value="None yet — press + Debt.", inline=False)
    if sources:
        lines = [f"{s['name']} — {format_money(s['amount_p'], symbol)}" for s in sources[:25]]
        if len(sources) > 25:
            lines.append(f"+{len(sources) - 25} more — check a single team.")
        e.add_field(name=f"Sources / Sponsors — {format_money(src_total, symbol)}", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Sources / Sponsors", value="None yet — press + Source.", inline=False)
    e.add_field(name="Net cashflow", value=f"**{format_money(net, symbol)}**", inline=False)
    e.set_footer(text="Type names exactly to remove (!findel <exact name>). Use buttons to add.")
    return e


async def team_autocomplete(interaction: discord.Interaction, current: str):
    try:
        doc = await get_guild_doc(interaction.guild_id)
        opts = []
        for t in doc.get("teams", []):
            label = t.get("name", "?")
            if current.lower() in label.lower():
                opts.append(app_commands.Choice(name=label, value=label))
        return opts[:25]
    except Exception:
        return []


# ---------- modals / views ----------

class AddEntryModal(discord.ui.Modal):
    def __init__(self, kind: str, team_id: str | None, team_label: str):
        super().__init__(title=f"Add {'Debt' if kind == 'debt' else 'Source'} — {team_label}")
        self.kind = kind
        self.team_id = team_id
        self.name_input = discord.ui.TextInput(label="Name", placeholder="e.g. Venue hire / WilSonic Boom sponsor", max_length=80)
        self.amount_input = discord.ui.TextInput(label="Amount", placeholder="e.g. 25, 25.50, 1,200.50", max_length=20)
        self.add_item(self.name_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_guild_doc(interaction.guild_id)
        mode = doc.get("settings", {}).get("finance_mode", "everyone")
        if not can_manage(mode, interaction.user):
            return await interaction.response.send_message("Only admins can manage finance.", ephemeral=True)
        symbol = guild_currency(doc)
        try:
            pence = parse_amount_to_pence(self.amount_input.value, symbol)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        if not claim_write_slot(interaction.guild_id):
            return await interaction.response.send_message(
                "Easy — a save just went through. Wait a second and try again.", ephemeral=True
            )
        bucket = team_bucket(doc, self.team_id)
        target = bucket["debts"] if self.kind == "debt" else bucket["sources"]
        target.append({
            "name": self.name_input.value.strip(),
            "amount_p": pence,
            "by": interaction.user.display_name,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        await save_guild_doc(doc)
        await interaction.response.send_message(
            f"Added {'debt' if self.kind == 'debt' else 'source'} `{self.name_input.value.strip()}` — {format_money(pence, symbol)}.",
            ephemeral=True,
        )


class TeamPickSelect(discord.ui.Select):
    """Dropdown to choose which team an entry is added to (modals can't hold one)."""

    def __init__(self, teams: list, current_id: str | None, kind: str):
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
        super().__init__(placeholder="Choose a team first…", options=options)
        self.kind = kind

    async def callback(self, interaction: discord.Interaction):
        doc = await get_guild_doc(interaction.guild_id)
        value = self.values[0]
        if value == "_server":
            team_id, label = None, "server"
        else:
            team_id = value
            label = next((t.get("name", "?") for t in doc.get("teams", []) if t.get("id") == value), "?")
        await interaction.response.send_modal(AddEntryModal(self.kind, team_id, label))


async def pick_team_then_modal(
    interaction: discord.Interaction, current_id: str | None, kind: str
) -> None:
    doc = await get_guild_doc(interaction.guild_id)
    mode = doc.get("settings", {}).get("finance_mode", "everyone")
    if not can_manage(mode, interaction.user):
        return await interaction.response.send_message(
            "Only admins can manage finance.", ephemeral=True
        )
    view = discord.ui.View(timeout=120)
    view.add_item(TeamPickSelect(doc.get("teams", []), current_id, kind))
    await interaction.response.send_message(
        f"Add {'debt' if kind == 'debt' else 'source'} to which team?",
        view=view,
        ephemeral=True,
    )


class FinanceView(discord.ui.View):
    def __init__(self, team_id: str | None, team_label: str):
        super().__init__(timeout=300)
        self.team_id = team_id
        self.team_label = team_label

    @discord.ui.button(label="+ Debt", style=discord.ButtonStyle.red)
    async def add_debt(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await pick_team_then_modal(interaction, self.team_id, "debt")

    @discord.ui.button(label="+ Source / Sponsor", style=discord.ButtonStyle.green)
    async def add_source(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await pick_team_then_modal(interaction, self.team_id, "source")

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.grey)
    async def remove_entry(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(RemoveEntryModal(self.team_id, self.team_label))


class RemoveEntryModal(discord.ui.Modal):
    def __init__(self, team_id: str | None, team_label: str):
        super().__init__(title=f"Remove entry — {team_label}")
        self.team_id = team_id
        self.name_input = discord.ui.TextInput(
            label="Entry name (exact, as shown)",
            placeholder="e.g. Venue hire",
            max_length=80,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_guild_doc(interaction.guild_id)
        mode = doc.get("settings", {}).get("finance_mode", "everyone")
        if not can_manage(mode, interaction.user):
            return await interaction.response.send_message("Only admins can manage finance.", ephemeral=True)
        name = self.name_input.value.strip()
        if self.team_id is None:
            buckets = list(doc.get("finance", {}).get("teams", {}).values())
        else:
            buckets = [team_bucket(doc, self.team_id)]
        removed = 0
        for bucket in buckets:
            for lst in ("debts", "sources"):
                kept = [e for e in bucket.get(lst, []) if e.get("name", "").lower() != name.lower()]
                removed += len(bucket.get(lst, [])) - len(kept)
                bucket[lst] = kept
        if not removed:
            return await interaction.response.send_message(
                f"No entry named `{name}` here. Type it exactly as shown in `!bal`.", ephemeral=True
            )
        if not claim_write_slot(interaction.guild_id):
            return await interaction.response.send_message(
                "Easy — a save just went through. Wait a second and try again.", ephemeral=True
            )
        await save_guild_doc(doc)
        await interaction.response.send_message(f"Removed `{name}` ({removed} entr{'y' if removed == 1 else 'ies'}).", ephemeral=True)


# ---------- cog ----------

class Finance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send_balance(self, ctx_or_interaction, guild: discord.Guild, author, team_arg: str | None):
        doc = await get_guild_doc(guild.id)
        symbol = guild_currency(doc)
        if team_arg:
            team_id, team_name = resolve_team(doc, team_arg)
            if not team_id:
                names = ", ".join(t.get("name", "?") for t in doc.get("teams", [])) or "no teams yet (add on website)"
                msg = f"Team '{team_arg}' not found. Available: {names}"
                hint = suggest_team(doc, team_arg)
                if hint:
                    msg += f"\nDid you mean '{hint}'?"
                if isinstance(ctx_or_interaction, commands.Context):
                    return await ctx_or_interaction.send(msg)
                return await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            bucket = team_bucket(doc, team_id)
            embed = finance_embed(f"Balance — {team_name}", bucket, symbol)
            view = FinanceView(team_id, team_name)
        else:
            bucket = combined_bucket(doc)
            embed = finance_embed(f"Balance — {guild.name} (all teams)", bucket, symbol)
            view = FinanceView(None, "server")
        hint = None
        if not doc.get("teams"):
            hint = "No teams yet — admins, add up to 3 on the website, then use !bal <team>."
        if isinstance(ctx_or_interaction, commands.Context):
            await ctx_or_interaction.send(content=hint, embed=embed, view=view)
        else:
            if hint:
                await ctx_or_interaction.response.send_message(content=hint, embed=embed, view=view)
            else:
                await ctx_or_interaction.response.send_message(embed=embed, view=view)

    @commands.hybrid_command(name="balance", aliases=["bal", "finance"], description="Show balance. Optional team.")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @app_commands.describe(team="Team name or alias (empty = whole server)")
    @app_commands.autocomplete(team=team_autocomplete)
    @commands.guild_only()
    async def balance(self, ctx: commands.Context, team: str | None = None):
        await self._send_balance(ctx, ctx.guild, ctx.author, team)

    @commands.command(name="findel")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def findel(self, ctx: commands.Context, *, name: str):
        """!findel <exact name> — remove a debt/source by typing its name exactly."""
        doc = await get_guild_doc(ctx.guild.id)
        mode = doc.get("settings", {}).get("finance_mode", "everyone")
        if not can_manage(mode, ctx.author):
            return await ctx.send("Only admins can manage finance.")
        removed = 0
        for bucket in doc.get("finance", {}).get("teams", {}).values():
            for lst in ("debts", "sources"):
                kept = [e for e in bucket.get(lst, []) if e.get("name", "").lower() != name.strip().lower()]
                removed += len(bucket.get(lst, [])) - len(kept)
                bucket[lst] = kept
        if not removed:
            return await ctx.send(f"No entry named `{name}`. Type it exactly as shown in `!bal`.")
        await save_guild_doc(doc)
        await ctx.send(f"Removed `{name.strip()}` ({removed} entr{'y' if removed == 1 else 'ies'}).")


async def setup(bot: commands.Bot):
    await bot.add_cog(Finance(bot))
