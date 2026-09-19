"""Fallback stub for the stdlib `audioop` module (PEP 594).

Why this file exists:
    discord.py imports `audioop` at startup for voice (audio playback) support,
    but `audioop` was REMOVED from the standard library in newer Pythons
    (3.14+). Hosts like Bot-hosting.net run new Pythons, so
    `import discord` crashes with `ModuleNotFoundError: No module named
    'audioop'` even though this bot never uses voice.

How it works:
    Python looks in the bot's own folder before the standard library, so this
    file satisfies `import audioop` on Pythons where it no longer exists.
    On older Pythons the real module is still used... actually no: this file
    always wins by path order, which is fine because nothing in this bot
    calls it — voice features are simply unavailable.

    DO NOT DELETE this file unless the host runs Python 3.12/3.13 AND you
    have verified the bot starts without it.
"""

_RUNTIME_FUNCS = ("mul", "add", "bias", "minmax", "max", "min", "rms", "avg")


def __getattr__(name: str):
    if name in _RUNTIME_FUNCS or not name.startswith("_"):
        raise ImportError(
            "audioop is unavailable on this Python version; "
            "voice/audio features are disabled (this bot doesn't use them)."
        )
    raise AttributeError(f"module 'audioop' has no attribute {name!r}")
