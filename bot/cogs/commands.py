"""Custom commands — PREFIX ONLY (no slash equivalents, per request).

- Guild commands: !addcmd / !delcmd / !cmds / !ftctoggle (admins only to manage)
- FTC help directory: bot/data/ftchelp.py plus guild commands flagged
  "Add to !ftchelp" — browsed with !ftchelp
- Global commands: dict in {_type: global_commands} doc, editable via web UI / code
- Triggers fire via on_message fallback: !<trigger>
Guild trigger wins, then FTC directory, then global trigger.
"""

import discord
from discord.ext import commands

from data.ftchelp import FTCHELP
from db.mongo import get_fresh_guild_doc, get_global_commands, get_guild_doc, save_guild_doc
from utils.perms import is_admin

FTCHELP_PER_PAGE = 10


def ftchelp_names(doc: dict | None) -> tuple[list, int]:
    """Merged sorted triggers: owner directory + flagged guild commands.
    Returns (names, server_count)."""
    names = set(FTCHELP)
    server_count = 0
    if doc:
        for c in doc.get("commands", []):
            if c.get("in_ftchelp") and c.get("trigger"):
                if c["trigger"] not in names:
                    server_count += 1
                names.add(c["trigger"])
    return sorted(names), server_count


def ftchelp_embed(page: int, names: list, server_count: int = 0) -> discord.Embed:
    total_pages = max(1, (len(names) + FTCHELP_PER_PAGE - 1) // FTCHELP_PER_PAGE)
    page = min(max(1, page), total_pages)
    chunk = names[(page - 1) * FTCHELP_PER_PAGE:page * FTCHELP_PER_PAGE]
    e = discord.Embed(title=f"FTC help — page {page}/{total_pages}", colour=discord.Colour.blurple())
    if not chunk:
        e.description = "Nothing here yet — the owner adds entries in bot/data/ftchelp.py."
    else:
        e.description = "\n".join(f"`!{t}`" for t in chunk)
    footer = "Type any command above to see it. !ftchelp <page> jumps pages."
    if server_count:
        footer += f" Includes {server_count} from this server."
    e.set_footer(text=footer)
    return e, total_pages


class FtchelpView(discord.ui.View):
    def __init__(self, page: int, names: list, server_count: int = 0):
        super().__init__(timeout=180)
        self.page = page
        self.names = names
        self.server_count = server_count
        self.total_pages = max(1, (len(names) + FTCHELP_PER_PAGE - 1) // FTCHELP_PER_PAGE)
        self._prev.disabled = page <= 1
        self._next.disabled = page >= self.total_pages

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.grey)
    async def _prev(self, interaction: discord.Interaction, _b: discord.ui.Button):
        self.page = max(1, self.page - 1)
        await self._refresh(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.grey)
    async def _next(self, interaction: discord.Interaction, _b: discord.ui.Button):
        self.page = min(self.total_pages, self.page + 1)
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction):
        embed, total = ftchelp_embed(self.page, self.names, self.server_count)
        self._prev.disabled = self.page <= 1
        self._next.disabled = self.page >= total
        await interaction.response.edit_message(embed=embed, view=self)


class CustomCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="addcmd")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def addcmd(self, ctx: commands.Context, trigger: str, *, response: str):
        """!addcmd <trigger> <response> — admins only."""
        if not is_admin(ctx.author):
            return await ctx.send("Only server admins can add commands.")
        trigger = trigger.lower().lstrip("!")
        if not trigger or " " in trigger:
            return await ctx.send("Trigger must be one word, e.g. `!addcmd hello Hi there!`")
        doc = await get_fresh_guild_doc(ctx.guild.id)
        cmds = doc.get("commands", [])
        cmds = [c for c in cmds if c.get("trigger") != trigger]
        cmds.append({"trigger": trigger, "response": response})
        doc["commands"] = cmds
        await save_guild_doc(doc)
        await ctx.send(f"Added `!{trigger}`.")

    @commands.command(name="delcmd")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def delcmd(self, ctx: commands.Context, trigger: str):
        if not is_admin(ctx.author):
            return await ctx.send("Only server admins can delete commands.")
        trigger = trigger.lower().lstrip("!")
        doc = await get_fresh_guild_doc(ctx.guild.id)
        before = len(doc.get("commands", []))
        doc["commands"] = [c for c in doc.get("commands", []) if c.get("trigger") != trigger]
        await save_guild_doc(doc)
        await ctx.send("Deleted." if len(doc["commands"]) < before else "Not found.")

    @commands.command(name="cmds")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def cmds(self, ctx: commands.Context):
        doc = await get_guild_doc(ctx.guild.id)
        guild_cmds = doc.get("commands", [])
        global_cmds = await get_global_commands()
        lines = []
        if guild_cmds:
            lines.append("**Server:** " + ", ".join(
                f"`!{c.get('trigger')}`" + (" ★" if c.get("in_ftchelp") else "")
                for c in sorted(guild_cmds, key=lambda c: c.get("trigger", ""))
            ))
        if global_cmds:
            lines.append("**Global:** " + ", ".join(f"`!{t}`" for t in sorted(global_cmds)))
        lines.append("**FTC help directory:** type `!ftchelp` to browse it. (★ = also listed there)")
        await ctx.send("\n".join(lines))

    @commands.command(name="ftctoggle")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def ftctoggle(self, ctx: commands.Context, trigger: str):
        """!ftctoggle <command> — toggle whether a server command appears in !ftchelp."""
        if not is_admin(ctx.author):
            return await ctx.send("Only server admins can change this.")
        trigger = trigger.lower().lstrip("!")
        doc = await get_fresh_guild_doc(ctx.guild.id)
        for c in doc.get("commands", []):
            if c.get("trigger") == trigger:
                c["in_ftchelp"] = not c.get("in_ftchelp", False)
                await save_guild_doc(doc)
                state = "now listed in `!ftchelp`" if c["in_ftchelp"] else "no longer listed in `!ftchelp`"
                return await ctx.send(f"`!{trigger}` is {state}.")
        await ctx.send(f"No server command `!{trigger}`. (Owner directory entries can't be toggled.)")

    @commands.command(name="ftchelp")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def ftchelp(self, ctx: commands.Context, page: str = "1"):
        """!ftchelp [page] — browse the FTC help directory + flagged server commands."""
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = 1
        doc = await get_guild_doc(ctx.guild.id)
        names, server_count = ftchelp_names(doc)
        total = max(1, (len(names) + FTCHELP_PER_PAGE - 1) // FTCHELP_PER_PAGE)
        page = min(max(1, page), total)
        embed, total = ftchelp_embed(page, names, server_count)
        await ctx.send(embed=embed, view=FtchelpView(page, names, server_count))

    @commands.Cog.listener("on_message")
    async def custom_fallback(self, event_msg: discord.Message):
        # Ignore bots/DMs/non-commands; let real commands run first.
        if event_msg.author.bot or not event_msg.guild:
            return
        prefix = "!"
        content = event_msg.content or ""
        if not content.startswith(prefix):
            return
        ctx = await self.bot.get_context(event_msg)
        if ctx.command is not None:  # a real command (bal, inv, addcmd...) handles it
            return
        trigger = content[len(prefix):].split()[0].lower()
        if not trigger:
            return
        doc = await get_guild_doc(event_msg.guild.id)
        for c in doc.get("commands", []):
            if c.get("trigger") == trigger:
                await event_msg.channel.send(c.get("response", ""))
                return
        if trigger in FTCHELP:
            await event_msg.channel.send(FTCHELP[trigger])
            return
        global_cmds = await get_global_commands()
        if trigger in global_cmds:
            await event_msg.channel.send(global_cmds[trigger])


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomCommands(bot))
