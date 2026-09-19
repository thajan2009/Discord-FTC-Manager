"""Money helpers. Amounts stored as integer minor units to avoid float errors.

Currency symbol is per-server (settings.currency, default "£") and only affects
display/parsing — stored numbers never change when the symbol changes.
"""

import re

DEFAULT_SYMBOL = "£"


def clean_symbol(value: object) -> str:
    """Sanitize an owner-entered symbol: 1–3 chars, fallback to £."""
    s = str(value or "").strip()
    if not s or len(s) > 3:
        return DEFAULT_SYMBOL
    return s


def parse_amount_to_pence(raw: str, symbol: str = DEFAULT_SYMBOL) -> int:
    """Parse '£1,200.50', '$25.50', '20' -> minor units int. Raises ValueError."""
    if raw is None:
        raise ValueError("Amount is required.")
    s = str(raw).strip()
    for sym in (symbol, "£", "$", "€", "¥", "₹"):
        s = s.replace(sym, "")
    s = s.replace(",", "").replace(" ", "")
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", s):
        raise ValueError(f"Could not parse amount '{raw}'. Use e.g. 25, 25.50, {symbol}1,200.50")
    return int(round(float(s) * 100))


def format_money(pence: int, symbol: str = DEFAULT_SYMBOL) -> str:
    sign = "-" if pence < 0 else ""
    p = abs(int(pence))
    major, rem = divmod(p, 100)
    return f"{sign}{symbol}{major:,}.{rem:02d}"


# Backwards-compatible aliases (default £ behaviour unchanged).
def parse_gbp_to_pence(raw: str) -> int:
    return parse_amount_to_pence(raw)


def format_gbp(pence: int) -> str:
    return format_money(pence)
