"""Custom commands — PREFIX ONLY (no slash equivalents, per request).

- Guild commands: !addcmd / !delcmd / !cmds (admins only to manage)
- FTC help directory: bot/data/ftchelp.py — owner-edited dict, browsed with !ftchelp
- Global commands: dict in {_type: global_commands} doc, editable via web UI / code
- Triggers fire via on_message fallback: !<trigger>
Guild trigger wins, then FTC directory, then global trigger.
"""

import discord
from discord.ext import commands

from data.ftchelp import FTCHELP
from db.mongo import get_global_commands, get_guild_doc, save_guild_doc
from utils.perms import is_admin

FTCHELP_PER_PAGE = 10


def ftchelp_embed(page: int) -> discord.Embed:
    names = sorted(FTCHELP)
    total_pages = max(1, (len(names) + FTCHELP_PER_PAGE - 1) // FTCHELP_PER_PAGE)
    page = min(max(1, page), total_pages)
    chunk = names[(page - 1) * FTCHELP_PER_PAGE:page * FTCHELP_PER_PAGE]
    e = discord.Embed(title=f"FTC help — page {page}/{total_pages}", colour=discord.Colour.blurple())
    if not chunk:
        e.description = "Nothing here yet — the owner adds entries in bot/data/ftchelp.py."
    else:
        e.description = "\n".join(f"`!{t}`" for t in chunk)
    e.set_footer(text="Type any command above to see it. !ftchelp <page> jumps pages.")
    return e, total_pages


class FtchelpView(discord.ui.View):
    def __init__(self, page: int, total_pages: int):
        super().__init__(timeout=180)
        self.page = page
        self.total_pages = total_pages
        self._prev.disabled = page <= 1
        self._next.disabled = page >= total_pages

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.grey)
    async def _prev(self, interaction: discord.Interaction, _b: discord.ui.Button):
        self.page = max(1, self.page - 1)
        await self._refresh(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.grey)
    async def _next(self, interaction: discord.Interaction, _b: discord.ui.Button):
        self.page = min(self.total_pages, self.page + 1)
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction):
        embed, total = ftchelp_embed(self.page)
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
        doc = await get_guild_doc(ctx.guild.id)
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
        doc = await get_guild_doc(ctx.guild.id)
        before = len(doc.get("commands", []))
        doc["commands"] = [c for c in doc.get("commands", []) if c.get("trigger") != trigger]
        await save_guild_doc(doc)
        await ctx.send("Deleted." if len(doc["commands"]) < before else "Not found.")

    @commands.command(name="cmds")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def cmds(self, ctx: commands.Context):
        doc = await get_guild_doc(ctx.guild.id)
        guild_cmds = [c.get("trigger") for c in doc.get("commands", [])]
        global_cmds = await get_global_commands()
        lines = []
        if guild_cmds:
            lines.append("**Server:** " + ", ".join(f"`!{t}`" for t in sorted(guild_cmds)))
        if global_cmds:
            lines.append("**Global:** " + ", ".join(f"`!{t}`" for t in sorted(global_cmds)))
        lines.append("**FTC help directory:** type `!ftchelp` to browse it.")
        await ctx.send("\n".join(lines))

    @commands.command(name="ftchelp")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def ftchelp(self, ctx: commands.Context, page: str = "1"):
        """!ftchelp [page] — browse the owner-curated FTC help directory."""
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = 1
        embed, total = ftchelp_embed(page)
        page = min(max(1, page), total)
        await ctx.send(embed=embed, view=FtchelpView(page, total))

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
