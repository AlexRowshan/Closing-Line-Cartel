"""
Regular expressions, constants, noise predicates, and line-value parsers
for the OddsTrader text format.
"""

import re

RECORD_RE = re.compile(r"^\d+-\d+$")
PCT_RE = re.compile(r"^\d+%$")

# Spread line: e.g. "+5 -110", "-4½ -115", "+14½ -110"
SPREAD_LINE_RE = re.compile(
    r"^([+-]\d+(?:½|\.\d+)?)\s+([+-]\d+)$"
)

# Totals line: e.g. "o148½ -110", "u149 -108"
TOTAL_LINE_RE = re.compile(
    r"^([ou])(\d+(?:½|\.\d+)?)\s+([+-]\d+)$"
)

# Noise lines to discard
NOISE_PATTERNS = [
    re.compile(r"^bell$", re.I),
    re.compile(r"^personalize", re.I),
    re.compile(r"^starts in", re.I),
    re.compile(r"^got it$", re.I),
    re.compile(r"^logo-", re.I),
    re.compile(r"^ncaab$", re.I),
    re.compile(r"^tv", re.I),
    re.compile(r"^\d+%$"),
    re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)\s+\d{2}/\d{2}$", re.I),
    re.compile(r"^\s*$"),
]

# Known book names on OddsTrader (used to detect end of a team block)
KNOWN_BOOKS = {
    "opener", "betonline", "betanything", "bovada", "heritage",
    "bookmaker", "justbet", "everygame", "mybookie", "betmgm",
    "draftkings", "fanduel", "caesars", "pointsbet", "bet365",
    "barstool", "espnbet", "fanatics",
}


def _is_noise(line: str) -> bool:
    for pat in NOISE_PATTERNS:
        if pat.match(line.strip()):
            return True
    return False


def _is_record(line: str) -> bool:
    return bool(RECORD_RE.match(line.strip()))


def _is_book_name(line: str) -> bool:
    return line.strip().lower() in KNOWN_BOOKS


def _is_line_value(line: str) -> bool:
    s = line.strip()
    return bool(SPREAD_LINE_RE.match(s) or TOTAL_LINE_RE.match(s))


def _normalize_line(line_str: str) -> str:
    """Convert ½ to .5 for consistency."""
    return line_str.replace("½", ".5")


def _parse_spread_line(line_str: str) -> tuple[str, str]:
    """Returns (spread_value, odds) e.g. ('+5', '-110')"""
    m = SPREAD_LINE_RE.match(line_str.strip())
    if m:
        return _normalize_line(m.group(1)), m.group(2)
    return "", ""


def _parse_total_line(line_str: str) -> tuple[str, str, str]:
    """Returns (direction, number, odds) e.g. ('over', '148.5', '-110')"""
    m = TOTAL_LINE_RE.match(line_str.strip())
    if m:
        direction = "over" if m.group(1) == "o" else "under"
        number = _normalize_line(m.group(2))
        return direction, number, m.group(3)
    return "", "", ""
