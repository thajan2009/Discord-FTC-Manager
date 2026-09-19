"""Entry file for Bot-hosting.net. Set Startup -> Entry File to `main.py`.

Upload the CONTENTS of bot/ (not the bot/ folder itself) so main.py is at panel root.
Env vars are set in panel Env tab, not in a .env file: DISCORD_TOKEN, MONGO_URI.
"""

import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Local dev: read repo-root .env + bot/.env at RUNTIME (Bot-hosting.net injects env directly).
_HERE = Path(__file__).resolve()
for _p in (_HERE.parent / ".env", _HERE.parent.parent / ".env"):
    if _p.is_file():
        load_dotenv(_p, override=False)
load_dotenv(override=False)

PREFIX = os.getenv("COMMAND_PREFIX", "!")
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID")  # optional: fast slash sync while testing


class FTCManager(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # needed for ! prefix + custom commands
        intents.members = True
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned_or(PREFIX), intents=intents, help_command=None)

    async def setup_hook(self):
        from db import mongo as mongo_db

        await mongo_db.ensure_indexes()
        mongo_db.start_flush_loop()
        for ext in (
            "cogs.general",
            "cogs.commands",
            "cogs.finance",
            "cogs.inventory",
        ):
            try:
                await self.load_extension(ext)
            except Exception as exc:  # keep boot resilient; error shows in panel logs
                print(f"[setup] failed to load {ext}: {exc}")

        # Slash sync: instant if TEST_GUILD_ID set, else global (can take ~1h first time)
        try:
            if TEST_GUILD_ID:
                guild = discord.Object(id=int(TEST_GUILD_ID))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"[setup] slash synced to test guild {TEST_GUILD_ID}")
            else:
                await self.tree.sync()
                print("[setup] slash synced globally")
        except Exception as exc:
            print(f"[setup] slash sync failed: {exc}")

    async def on_ready(self):
        print(f"Logged in as {self.user} | guilds={len(self.guilds)}")

    async def on_guild_join(self, guild: discord.Guild):
        # Ensure guild doc exists with 0 teams by default (web UI adds teams).
        try:
            from db.mongo import get_guild_doc

            await get_guild_doc(guild.id)
            print(f"[guild_join] initialised {guild.id}")
        except Exception as exc:
            print(f"[guild_join] mongo init failed: {exc}")
        # Welcome + setup guide so admins know what to do next.
        try:
            target = guild.system_channel
            if target is None or not target.permissions_for(guild.me).send_messages:
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        target = ch
                        break
            if target is not None and target.permissions_for(guild.me).send_messages:
                web_url = os.getenv("PUBLIC_WEB_URL", "the dashboard website")
                embed = discord.Embed(
                    title="Thanks for adding FTCManager",
                    description=(
                        "Track team money and stock straight from Discord.\n\n"
                        f"**1. Create teams** — admins open {web_url}, log in "
                        "and add up to 3 teams with short aliases.\n"
                        "**2. Check the balance** — `!bal` for the whole server, "
                        "`!bal myteam` per team (or `/balance`).\n"
                        "**3. Track stock** — `!inv` (or `/inventory`).\n"
                        "**4. Custom replies** — `!addcmd hello Hi there`."
                    ),
                    colour=discord.Colour.blurple(),
                )
                embed.set_footer(text="Type !help anytime for the full list.")
                await target.send(embed=embed)
        except Exception as exc:
            print(f"[guild_join] welcome failed: {exc}")


bot = FTCManager()


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CommandNotFound):
        return  # handled by custom-command fallback in cogs.commands
    if isinstance(error, commands.CommandOnCooldown):
        return await ctx.send(f"Slow down a little — try again in {error.retry_after:.0f}s.")
    await ctx.send(f"Error: {error}")


@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: Exception):
    if isinstance(error, commands.CommandOnCooldown):
        msg = f"Slow down a little — try again in {error.retry_after:.0f}s."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN missing. Set it in Bot-hosting.net Env tab.")
    bot.run(token)
