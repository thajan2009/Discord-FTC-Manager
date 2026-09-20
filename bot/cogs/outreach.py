"""Outreach list — HYBRID (works as !outreach and /outreach).

- !outreach / !out / !outreachlist [team]  ==  /outreach [team]
- No arg -> combined (all teams). With arg -> single team.
- Buttons: + Entry / Remove. Team picker + tick before adding.
- Entries are removed by typing the exact name (no IDs).
- Permission from web toggle settings.outreach_mode: everyone|admins
"""

import discord
from discord import app_commands
from discord.ext import commands

from datetime import datetime, timezone

from db.mongo import get_fresh_guild_doc, get_guild_doc, resolve_team, save_guild_doc, suggest_team
from utils.perms import can_manage


def team_outreach(doc: dict, team_id: str | None) -> dict:
    teams = doc.setdefault("outreach", {}).setdefault("teams", {})
    key = team_id or "_server"
    return teams.setdefault(key, {"items": []})


def outreach_mode(doc: dict) -> str:
    return doc.get("settings", {}).get("outreach_mode", "everyone")


def combined_entries(doc: dict) -> list:
    valid = {t.get("id") for t in doc.get("teams", [])} | {"_server"}
    names = {t.get("id"): t.get("name", "?") for t in doc.get("teams", [])}
    out = []
    for key, bucket in doc.get("outreach", {}).get("teams", {}).items():
        if key not in valid:
            continue
        label = names.get(key, "Server")
        for item in bucket.get("items", []):
            out.append({"team": label, "name": item.get("name", "?")})
    out.sort(key=lambda x: (x["team"].lower(), x["name"].lower()))
    return out


def outreach_embed(title: str, entries: list) -> discord.Embed:
    e = discord.Embed(title=title, colour=discord.Colour.blue())
    if not entries:
        e.description = "Nothing logged yet — press + Entry."
    else:
        lines = []
        for it in entries[:30]:
            if "team" in it:
                lines.append(f"{it['name']} ({it['team']})")
            else:
                lines.append(f"{it['name']}")
        if len(entries) > 30:
            lines.append(f"+{len(entries) - 30} more — check a single team.")
        e.description = "\n".join(lines)
    e.set_footer(text="Type names exactly as shown to remove them.")
    return e


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


class AddOutreachModal(discord.ui.Modal):
    def __init__(
        self, team_id: str | None, team_label: str,
        orig_msg: discord.Message | None = None,
        scope_id: str | None = None, scope_label: str = "server",
        picker_msg: discord.Message | None = None,
    ):
        super().__init__(title=f"Log outreach — {team_label}")
        self.team_id = team_id
        self.orig_msg = orig_msg
        self.scope_id = scope_id
        self.scope_label = scope_label
        self.picker_msg = picker_msg
        self.name_input = discord.ui.TextInput(
            label="What did the team do?",
            placeholder="e.g. Demo at Springfield Primary",
            max_length=120,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_fresh_guild_doc(interaction.guild_id)
        if not can_manage(outreach_mode(doc), interaction.user):
            return await interaction.response.send_message("Only admins can manage outreach.", ephemeral=True)
        name = self.name_input.value.strip()
        if not name:
            return await interaction.response.send_message("Describe what was done.", ephemeral=True)
        bucket = team_outreach(doc, self.team_id)
        bucket.setdefault("items", []).append({
            "name": name,
            "by": interaction.user.display_name,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        from db.mongo import claim_write_slot
        if not claim_write_slot(interaction.guild_id):
            return await interaction.response.send_message(
                "Easy — a save just went through. Wait a second and try again.", ephemeral=True
            )
        await save_guild_doc(doc)
        await refresh_outreach_msg(self.orig_msg, interaction.guild, self.scope_id, self.scope_label)
        if self.picker_msg is not None:
            try:
                await self.picker_msg.delete()
            except Exception:
                pass
        await interaction.response.send_message(f"Logged `{name}`.", ephemeral=True)


class RemoveOutreachModal(discord.ui.Modal):
    def __init__(
        self, team_id: str | None, team_label: str,
        orig_msg: discord.Message | None = None,
    ):
        super().__init__(title=f"Remove outreach — {team_label}")
        self.team_id = team_id
        self.team_label = team_label
        self.orig_msg = orig_msg
        self.name_input = discord.ui.TextInput(label="Entry name (exact, as shown)", max_length=120)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        doc = await get_fresh_guild_doc(interaction.guild_id)
        if not can_manage(outreach_mode(doc), interaction.user):
            return await interaction.response.send_message("Only admins can manage outreach.", ephemeral=True)
        name = self.name_input.value.strip()
        if self.team_id is None:
            buckets = list(doc.get("outreach", {}).get("teams", {}).values())
        else:
            buckets = [team_outreach(doc, self.team_id)]
        removed = 0
        for bucket in buckets:
            kept = [it for it in bucket.get("items", []) if it.get("name", "").lower() != name.lower()]
            removed += len(bucket.get("items", [])) - len(kept)
            bucket["items"] = kept
        if not removed:
            return await interaction.response.send_message(
                f"No entry named `{name}` here. Type it exactly as shown.", ephemeral=True
            )
        from db.mongo import claim_write_slot
        if not claim_write_slot(interaction.guild_id):
            return await interaction.response.send_message(
                "Easy — a save just went through. Wait a second and try again.", ephemeral=True
            )
        await save_guild_doc(doc)
        await refresh_outreach_msg(self.orig_msg, interaction.guild, self.team_id, self.team_label)
        await interaction.response.send_message(f"Removed `{name}`.", ephemeral=True)


class OutreachTeamPickSelect(discord.ui.Select):
    """Dropdown to choose which team to log outreach for (modals can't hold one).
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


class OutreachPickView(discord.ui.View):
    """Team dropdown + tick to confirm. Tick accepts the preselected default."""

    def __init__(
        self, teams: list, current_id: str | None,
        orig_msg: discord.Message | None, scope_id: str | None, scope_label: str,
    ):
        super().__init__(timeout=120)
        self.orig_msg = orig_msg
        self.scope_id = scope_id
        self.scope_label = scope_label
        self.selected = current_id  # None = Server (combined)
        self.add_item(OutreachTeamPickSelect(teams, current_id))

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
            AddOutreachModal(
                team_id, label,
                orig_msg=self.orig_msg, scope_id=self.scope_id, scope_label=self.scope_label,
                picker_msg=interaction.message,
            )
        )


async def refresh_outreach_msg(
    msg: discord.Message | None, guild: discord.Guild, scope_id: str | None, scope_label: str
) -> None:
    """Re-render the original outreach message after a change."""
    if msg is None:
        return
    try:
        doc = await get_guild_doc(guild.id)
        if scope_id is None:
            entries = combined_entries(doc)
            title = f"Outreach — {guild.name} (all teams)"
        else:
            entries = team_outreach(doc, scope_id).get("items", [])
            title = f"Outreach — {scope_label}"
        await msg.edit(
            embed=outreach_embed(title, entries),
            view=OutreachView(scope_id, scope_label),
        )
    except Exception:
        pass  # original message deleted — ephemeral confirm still sent


class OutreachView(discord.ui.View):
    def __init__(self, team_id: str | None, team_label: str):
        super().__init__(timeout=300)
        self.team_id = team_id
        self.team_label = team_label

    @discord.ui.button(label="+ Entry", style=discord.ButtonStyle.green)
    async def add_entry(self, interaction: discord.Interaction, _b: discord.ui.Button):
        doc = await get_guild_doc(interaction.guild_id)
        if not can_manage(outreach_mode(doc), interaction.user):
            return await interaction.response.send_message(
                "Only admins can manage outreach.", ephemeral=True
            )
        view = OutreachPickView(
            doc.get("teams", []), self.team_id,
            interaction.message, self.team_id, self.team_label,
        )
        await interaction.response.send_message(
            "Log outreach for which team?", view=view, ephemeral=True
        )

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.red)
    async def remove_entry(self, interaction: discord.Interaction, _b: discord.ui.Button):
        await interaction.response.send_modal(
            RemoveOutreachModal(self.team_id, self.team_label, orig_msg=interaction.message)
        )


class Outreach(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="outreach", aliases=["out", "outreachlist"],
        description="Show the outreach list. Optional team.",
    )
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @app_commands.describe(team="Team name or alias (empty = combined)")
    @app_commands.autocomplete(team=team_autocomplete)
    @commands.guild_only()
    async def outreach(self, ctx: commands.Context, team: str | None = None):
        doc = await get_guild_doc(ctx.guild.id)
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
            entries = team_outreach(doc, team_id).get("items", [])
            embed = outreach_embed(f"Outreach — {team_name}", entries)
            view = OutreachView(team_id, team_name)
        else:
            entries = combined_entries(doc)
            embed = outreach_embed(f"Outreach — {ctx.guild.name} (all teams)", entries)
            view = OutreachView(None, "server")
        # hybrid: ctx.send works for both prefix and slash (deferred-safe)
        if not doc.get("teams"):
            await ctx.send(
                "No teams yet — admins, add up to 3 on the website, then use !outreach <team>.",
                embed=embed, view=view,
            )
        else:
            await ctx.send(embed=embed, view=view)

    @commands.command(name="outdel")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def outdel(self, ctx: commands.Context, *, name: str):
        """!outdel <exact name> — remove an outreach entry by typing it exactly."""
        doc = await get_fresh_guild_doc(ctx.guild.id)
        if not can_manage(outreach_mode(doc), ctx.author):
            return await ctx.send("Only admins can manage outreach.")
        removed = 0
        for bucket in doc.get("outreach", {}).get("teams", {}).values():
            kept = [it for it in bucket.get("items", []) if it.get("name", "").lower() != name.strip().lower()]
            removed += len(bucket.get("items", [])) - len(kept)
            bucket["items"] = kept
        if not removed:
            return await ctx.send(f"No entry named `{name}`. Type it exactly as shown in `!outreach`.")
        from db.mongo import claim_write_slot
        if not claim_write_slot(ctx.guild.id):
            return await ctx.send("Easy — a save just went through. Wait a second and try again.")
        await save_guild_doc(doc)
        await ctx.send(f"Removed `{name.strip()}`.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Outreach(bot))
