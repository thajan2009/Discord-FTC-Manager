"""Shared embed branding: logo thumbnail + author header.

The logo is served from the website (web/public/logo.png), so the URL is
built from PUBLIC_WEB_URL. Falls back to the production site so it works
even if the env var is missing somewhere.
"""

import os

FALLBACK_BASE = "https://ftcbot.netlify.app"


def logo_url() -> str:
    base = (os.getenv("PUBLIC_WEB_URL") or FALLBACK_BASE).rstrip("/")
    return f"{base}/logo.png"


def brand(embed, author_name: str):
    """Attach the FTCManager author header + logo thumbnail. Never raises."""
    try:
        url = logo_url()
        embed.set_author(name=author_name, icon_url=url)
        embed.set_thumbnail(url=url)
    except Exception:
        pass
    return embed
