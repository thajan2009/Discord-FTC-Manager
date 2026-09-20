"""Prefix + slash utilities. Hybrid = works as !ping and /ping."""

import os

import discord
from discord.ext import commands

from utils.branding import brand


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="ping", description="Check bot latency.")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    async def ping(self, ctx: commands.Context):
        ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! {ms}ms")

    @commands.hybrid_command(name="manage", description="Get the website link to manage this server.")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    @commands.guild_only()
    async def manage(self, ctx: commands.Context):
        base = os.getenv("PUBLIC_WEB_URL", "").rstrip("/")
        if not base:
            return await ctx.send("The dashboard link isn't configured yet — ask an admin to set PUBLIC_WEB_URL.")
        await ctx.send(f"Manage this server here: {base}/guild/{ctx.guild.id}")

    @commands.hybrid_command(name="status", description="Bot health: latency, servers, cache.")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    async def status(self, ctx: commands.Context):
        from db import mongo as mongo_db

        ms = round(self.bot.latency * 1000)
        embed = discord.Embed(title="Bot status", colour=discord.Colour.green())
        embed.add_field(name="Latency", value=f"{ms}ms")
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)))
        embed.add_field(name="Cached servers", value=str(len(mongo_db._cache)))
        brand(embed, "FTCManager")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="help", description="Show help.")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    async def help_cmd(self, ctx: commands.Context):
        embed = discord.Embed(title="FTCManager Help", colour=discord.Colour.blurple())
        embed.add_field(
            name="Finance (prefix + slash)",
            value="`!bal [team]` / `/balance [team]`\n`!balance`, `!finance` are aliases.",
            inline=False,
        )
        embed.add_field(
            name="Inventory (prefix + slash)",
            value="`!inv [team]` / `/inventory [team]`",
            inline=False,
        )
        embed.add_field(
            name="Outreach list (prefix + slash)",
            value="`!outreach [team]` / `/outreach [team]` — log what each team has done.",
            inline=False,
        )
        embed.add_field(
            name="Custom commands (prefix only)",
            value="`!addcmd <name> <response>`\n`!delcmd <name>`\n`!cmds`",
            inline=False,
        )
        embed.add_field(
            name="FTC help directory (prefix only)",
            value="`!ftchelp [page]` — browse owner-curated answers like `!axon`.",
            inline=False,
        )
        embed.add_field(
            name="Manage online",
            value="`!manage` / `/manage` — link to this server's dashboard page.",
            inline=False,
        )
        embed.add_field(
            name="Teams",
            value="Admins add up to 3 teams on the website (name + aliases). Then `!bal myteam`.",
            inline=False,
        )
        embed.set_footer(text="Fair use: 30 commands per minute per server keeps things smooth for everyone.")
        brand(embed, "FTCManager")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
