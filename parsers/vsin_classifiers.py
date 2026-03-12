"""
Line-type classifiers and text utilities for the VSiN splits parser.
"""

import re


def clean_line(s: str) -> str:
    return s.strip().rstrip("\t")


def is_pct(s: str) -> bool:
    return bool(re.match(r"^\d+%\s*$", s.strip()))


def parse_pct(s: str) -> int:
    return int(re.search(r"(\d+)", s).group(1))


def is_number_line(s: str) -> bool:
    """Check if a line is a numeric value (spread, total, or ML)."""
    s = s.strip()
    return bool(re.match(r"^[+-]?\d+\.?\d*$", s))


def is_team_name(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if is_pct(s) or is_number_line(s):
        return False
    if s == "-":
        return False
    lower = s.lower()
    skip_phrases = [
        "betting splits", "betting picks", "vsin", "subscribe",
        "about the", "college basketball", "nba ", "nfl ", "mlb ",
        "nhl ", "pro tools", "article calendar", "parlay calculator",
    ]
    for phrase in skip_phrases:
        if phrase in lower:
            return False
    return bool(re.match(r"^[A-Za-z]", s))


def is_date_header(s: str) -> bool:
    return bool(re.match(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*\w+\s+\d+",
        s.strip(), re.IGNORECASE
    ))


def is_column_header(s: str) -> bool:
    return "Spread" in s and "Handle" in s and "Bets" in s
