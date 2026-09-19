"""Permission helpers: web UI toggles everyone vs admins."""

import discord


def is_admin(member: discord.Member) -> bool:
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    return bool(perms.administrator or perms.manage_guild)


def can_manage(mode: str, member: discord.Member) -> bool:
    """mode is 'everyone' or 'admins' (from web settings)."""
    if mode == "everyone":
        return True
    return is_admin(member)
