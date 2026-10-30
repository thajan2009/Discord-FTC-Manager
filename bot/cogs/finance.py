"""Finance system — HYBRID (works as !bal and /balance).

- !bal / !balance / !finance [team]  ==  /balance [team]
- No arg  -> server combined (sum of all teams)
- With arg -> single team resolved by name/alias (web UI defines up to 3 teams)
- Embed: initial £0.00, Debts list + total, Sources/Sponsors list + total,
  Store credits (shown in brackets, never subtracted from net), Net
- Buttons: +Debt / +Source / +Store Credit / Remove open Modals (names typed exactly, no IDs)
- Permission from web toggle settings.finance_mode: everyone|admins
"""

import discord
from discord import app_commands
from discord.ext import commands

from datetime import datetime, timezone

from db.mongo import claim_write_slot, get_fresh_guild_doc, get_guild_doc, resolve_team, save_guild_doc, suggest_team
from utils.money import clean_symbol, format_money, parse_amount_to_pence
from utils.branding import brand
from utils.perms import can_manage


def guild_currency(doc: dict) -> str:
    return clean_symbol(doc.get("settings", {}).get("currency", "£"))


# ---------- helpers ----------

KIND_LABEL = {"debt": "Debt", "source": "Source", "credit": "Store Credit"}
KIND_WORD = {"debt": "debt", "source": "source", "credit": "store credit"}


def team_bucket(doc: dict, team_id: str | None) -> dict:
    teams = doc.setdefault("finance", {}).setdefault("teams", {})
    key = team_id or "_server"
    bucket = teams.setdefault(key, {"debts": [], "sources": [], "credits": []})
    bucket.setdefault("debts", [])
    bucket.setdefault("sources", [])
    bucket.setdefault("credits", [])
    return bucket


def live_team_keys(doc: dict) -> set:
    """Bucket keys that still belong to a team (plus _server). Stale keys from
    teams deleted before cascade-delete are ignored in combined views."""
    return {t.get("id") for t in doc.get("teams", [])} | {"_server"}


def combined_bucket(doc: dict) -> dict:
    valid = live_team_keys(doc)
    teams = doc.get("finance", {}).get("teams", {})
    debts, sources, credits = [], [], []
    for key, bucket in teams.items():
        if key not in valid:
            continue
        debts.extend(bucket.get("debts", []))
        sources.extend(bucket.get("sources", []))
        credits.extend(bucket.get("credits", []))
    return {"debts": debts, "sources": sources, "credits": credits}


def finance_embed(title: str, bucket: dict, symbol: str = "£") -> discord.Embed:
    debts = bucket.get("debts", [])
    sources = bucket.get("sources", [])
    credits = bucket.get("credits", [])
    debt_total = sum(int(d.get("amount_p", 0)) for d in debts)
    src_total = sum(int(s.get("amount_p", 0)) for s in sources)
    credit_total = sum(int(c.get("amount_p", 0)) for c in credits)
    net = src_total - debt_total  # store credit is a bonus, never counted in net
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
    if credits:
        lines = [f"{c['name']} — {format_money(c['amount_p'], symbol)}" for c in credits[:25]]
        if len(credits) > 25:
            lines.append(f"+{len(credits) - 25} more — check a single team.")
        e.add_field(name=f"Store credits — {format_money(credit_total, symbol)}", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Store credits", value="None yet — press + Store Credit.", inline=False)
    net_line = f"**{format_money(net, symbol)}**"
    if credit_total:
        net_line += f" *(+{format_money(credit_total, symbol)} store credit)*"
    e.add_field(name="Net cashflow", value=net_line, inline=False)
    e.set_footer(text="Type names exactly to remove (!findel <exact name>). Use buttons to add.")
    brand(e, "FTCManager Finance")
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
    def __init__(
        self, kind: str, team_id: str | None, team_label: str,
        orig_msg: discord.Message | None = None,
        scope_id: str | None = None, scope_label: str = "server",
        picker_msg: discord.Message | None = None,
    ):
        super().__init__(title=f"Add {KIND_LABEL.get(kind, 'Source')} — {team_label}"[:45])
        self.kind = kind
        self.team_id = team_id
        self.orig_msg = orig_msg
        self.scope_id = scope_id
        self.scope_label = scope_label
        self.picker_msg = picker_msg
        self.name_input = discord.ui.TextInput(label="Name", placeholder="e.g. Venue hire / WilSonic Boom sponsor", max_length=80)
        self.amount_input = discord.ui.TextInput(label="Amount", placeholder="e.g. 25, 25.50, 1,200.50", max_length=20)
        self.add_item(self.name_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_fresh_guild_doc(interaction.guild_id)
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
        target = bucket[f"{self.kind}s"]
        target.append({
            "name": self.name_input.value.strip(),
            "amount_p": pence,
            "by": interaction.user.display_name,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        await save_guild_doc(doc)
        await refresh_balance_msg(self.orig_msg, interaction.guild, self.scope_id, self.scope_label)
        if self.picker_msg is not None:
            try:
                await self.picker_msg.delete()
            except Exception:
                pass
        await interaction.response.send_message(
            f"Added {KIND_WORD.get(self.kind, 'entry')} `{self.name_input.value.strip()}` — {format_money(pence, symbol)}.",
            ephemeral=True,
        )


class TeamPickSelect(discord.ui.Select):
    """Dropdown to choose which team an entry is added to (modals can't hold one).
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


class TeamPickView(discord.ui.View):
    """Team dropdown + tick to confirm. Tick accepts the preselected default,
    so on the combined view you just press ✅ for Server."""

    def __init__(
        self,
        teams: list,
        current_id: str | None,
        kind: str,
        orig_msg: discord.Message | None,
        scope_id: str | None,
        scope_label: str,
    ):
        super().__init__(timeout=120)
        self.kind = kind
        self.orig_msg = orig_msg
        self.scope_id = scope_id
        self.scope_label = scope_label
        self.selected = current_id  # None = Server (combined)
        self.add_item(TeamPickSelect(teams, current_id))

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
            AddEntryModal(
                self.kind, team_id, label,
                orig_msg=self.orig_msg, scope_id=self.scope_id, scope_label=self.scope_label,
                picker_msg=interaction.message,
            )
        )


async def pick_team_then_modal(
    interaction: discord.Interaction, current_id: str | None, kind: str,
    orig_msg: discord.Message | None, scope_id: str | None, scope_label: str,
) -> None:
    doc = await get_guild_doc(interaction.guild_id)
    mode = doc.get("settings", {}).get("finance_mode", "everyone")
    if not can_manage(mode, interaction.user):
        return await interaction.response.send_message(
            "Only admins can manage finance.", ephemeral=True
        )
    view = TeamPickView(doc.get("teams", []), current_id, kind, orig_msg, scope_id, scope_label)
    await interaction.response.send_message(
        f"Add {KIND_WORD.get(kind, 'entry')} to which team?",
        view=view,
        ephemeral=True,
    )


async def refresh_balance_msg(
    msg: discord.Message | None, guild: discord.Guild, scope_id: str | None, scope_label: str
) -> None:
    """Re-render the original balance message after a change."""
    if msg is None:
        return
    try:
        doc = await get_guild_doc(guild.id)
        symbol = guild_currency(doc)
        if scope_id is None:
            bucket = combined_bucket(doc)
            title = f"Balance — {guild.name} (all teams)"
        else:
            bucket = team_bucket(doc, scope_id)
            title = f"Balance — {scope_label}"
        await msg.edit(
            embed=finance_embed(title, bucket, symbol),
            view=FinanceView(scope_id, scope_label),
        )
    except Exception:
        pass  # original message deleted — ephemeral confirm still sent


class FinanceView(discord.ui.View):
    def __init__(self, team_id: str | None, team_label: str):
        super().__init__(timeout=300)
        self.team_id = team_id
        self.team_label = team_label

    @discord.ui.button(label="+ Debt", style=discord.ButtonStyle.red)
    async def add_debt(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await pick_team_then_modal(
            interaction, self.team_id, "debt",
            interaction.message, self.team_id, self.team_label,
        )

    @discord.ui.button(label="+ Source / Sponsor", style=discord.ButtonStyle.green)
    async def add_source(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await pick_team_then_modal(
            interaction, self.team_id, "source",
            interaction.message, self.team_id, self.team_label,
        )

    @discord.ui.button(label="+ Store Credit", style=discord.ButtonStyle.blurple)
    async def add_credit(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await pick_team_then_modal(
            interaction, self.team_id, "credit",
            interaction.message, self.team_id, self.team_label,
        )

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.grey)
    async def remove_entry(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(
            RemoveEntryModal(self.team_id, self.team_label, orig_msg=interaction.message)
        )


class RemoveEntryModal(discord.ui.Modal):
    def __init__(
        self, team_id: str | None, team_label: str,
        orig_msg: discord.Message | None = None,
    ):
        super().__init__(title=f"Remove entry — {team_label}")
        self.team_id = team_id
        self.team_label = team_label
        self.orig_msg = orig_msg
        self.name_input = discord.ui.TextInput(
            label="Entry name (exact, as shown)",
            placeholder="e.g. Venue hire",
            max_length=80,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_fresh_guild_doc(interaction.guild_id)
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
            for lst in ("debts", "sources", "credits"):
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
        await refresh_balance_msg(self.orig_msg, interaction.guild, self.team_id, self.team_label)
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

    @commands.hybrid_command(name="balance", aliases=["finance"], description="Show balance. Optional team.")
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
        doc = await get_fresh_guild_doc(ctx.guild.id)
        mode = doc.get("settings", {}).get("finance_mode", "everyone")
        if not can_manage(mode, ctx.author):
            return await ctx.send("Only admins can manage finance.")
        removed = 0
        for bucket in doc.get("finance", {}).get("teams", {}).values():
            for lst in ("debts", "sources", "credits"):
                kept = [e for e in bucket.get(lst, []) if e.get("name", "").lower() != name.strip().lower()]
                removed += len(bucket.get(lst, [])) - len(kept)
                bucket[lst] = kept
        if not removed:
            return await ctx.send(f"No entry named `{name}`. Type it exactly as shown in `!bal`.")
        await save_guild_doc(doc)
        await ctx.send(f"Removed `{name.strip()}` ({removed} entr{'y' if removed == 1 else 'ies'}).")


async def setup(bot: commands.Bot):
    await bot.add_cog(Finance(bot))
