"""
Team name normalization, abbreviation expansion, fuzzy matching,
and alert de-duplication key utilities.
"""

import re

from sport_config import CBB_TEAM_ABBREV

# Active abbreviation map — set at the start of run_pipeline() via set_team_abbrev().
# Single-threaded (one analysis at a time via _analysis_running lock in app.py).
_TEAM_ABBREV: dict = CBB_TEAM_ABBREV


def set_team_abbrev(abbrev_map: dict) -> None:
    global _TEAM_ABBREV
    _TEAM_ABBREV = abbrev_map


def _clean_team_name(name: str) -> str:
    """
    Strip non-breaking spaces, AP poll rankings like (4) or #12,
    and extra whitespace from team names sourced from VSIN's page.
    """
    n = name.replace("\xa0", " ")
    n = re.sub(r"\s*\(?\#?\d+\)?\s*$", "", n)
    n = re.sub(r"^\s*\(?\#?\d+\)?\s*", "", n)
    return " ".join(n.split())


def _normalize_team(name: str) -> str:
    """Lowercase + strip + apply common abbreviation expansions."""
    n = _clean_team_name(name).lower()
    n = re.sub(r"^(the|a|an)\s+", "", n)
    n = n.replace(".", "")
    n = n.replace("-", " ")
    n = " ".join(n.split())
    n = re.sub(r"^csu\b", "cal state", n)
    n = re.sub(r"\bst$", "state", n)
    # Collapse directional prefixes to single letter so both
    # "S Utah" (VSIN) and "Southern Utah" (OddsTrader) normalize the same.
    n = re.sub(r"^north(?:ern)?\s", "n ", n)
    n = re.sub(r"^south(?:ern)?\s", "s ", n)
    n = re.sub(r"^east(?:ern)?\s", "e ", n)
    n = re.sub(r"^west(?:ern)?\s", "w ", n)
    # Normalize "UT <school>" → "texas <school>" so VSIN's
    # "Texas-Arlington" matches OddsTrader's "UT Arlington", etc.
    n = re.sub(r"^ut\s", "texas ", n)
    return _TEAM_ABBREV.get(n, n)


def _teams_match(vsin_name: str, oddstrader_name: str) -> bool:
    """
    Fuzzy match: normalized equality OR word-level prefix match.

    Prefix match handles "Penn State" vs "Penn State Nittany Lions" (OddsTrader
    includes mascot names) while rejecting false positives like "Arizona" vs
    "N Arizona" where the shorter name appears mid-string in the longer one.
    """
    a = _normalize_team(vsin_name)
    b = _normalize_team(oddstrader_name)
    if a == b:
        return True
    a_words = a.split()
    b_words = b.split()
    shorter, longer = (a_words, b_words) if len(a_words) <= len(b_words) else (b_words, a_words)
    if shorter and longer[:len(shorter)] == shorter:
        return True
    return False


def _alert_key(alert) -> tuple:
    away = _clean_team_name(alert.away_team).lower()
    home = _clean_team_name(alert.home_team).lower()
    if alert.market == "Spread":
        raw_team = re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip()
        team = _clean_team_name(raw_team).lower()
        return (away, home, "spread", team)
    else:
        direction = "over" if alert.side.lower().startswith("over") else "under"
        return (away, home, direction)
