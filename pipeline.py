"""
Sharp Betting Analysis Pipeline
---------------------------------
Orchestrates the full filtering pipeline:
  1. Parse VSIN DK and Circa splits
  2. Parse OddsTrader Bovada lines
  3. Filter out past games
  4. Tiered play selection:
       Tier 1: DK ∩ Circa ∩ Bovada best price
       Tier 2: DK ∩ Circa
       Tier 3: DK ∩ Bovada best price
       Tier 4: Top DK sharp plays (by diff)
  5. Attach Bovada line to each selected play
"""

import re
from dataclasses import dataclass
from datetime import datetime, date

from vsin_splits_parser import SplitAlert, parse_splits
from oddstrader_parser import BovadaEntry, parse_oddstrader
from sport_config import get_config, CBB_TEAM_ABBREV

# Max plays to pass into the Gemini prompt (table shows all plays)
PROMPT_MAX_PLAYS = 5

# Active abbreviation map — set at the start of run_pipeline() based on sport.
# Single-threaded (one analysis at a time via _analysis_running lock in app.py).
_TEAM_ABBREV: dict = CBB_TEAM_ABBREV


@dataclass
class Play:
    alert: SplitAlert
    bovada_line: str          # e.g. "+15.0" or "135.5"
    bovada_odds: str          # e.g. "-115" or "-110"
    bovada_direction: str     # "over"/"under" for totals, "" for spreads
    is_bovada_best_price: bool
    conviction_tier: int      # 1 = highest, 4 = lowest
    confidence_score: int     # composite score for ranking: (5-tier)*30 + diff

    def to_dict(self) -> dict:
        alert = self.alert
        return {
            "date": alert.date,
            "away": _clean_team_name(alert.away_team),
            "home": _clean_team_name(alert.home_team),
            "market": alert.market,
            "side": alert.side,
            "handle_pct": alert.handle_pct,
            "bets_pct": alert.bets_pct,
            "diff": alert.diff,
            "bovada_line": self.bovada_line,
            "bovada_odds": self.bovada_odds,
            "bovada_direction": self.bovada_direction,
            "is_bovada_best_price": self.is_bovada_best_price,
            "conviction_tier": self.conviction_tier,
            "confidence_score": self.confidence_score,
        }


# ---------------------------------------------------------------------------
# Team name normalization
# ---------------------------------------------------------------------------

def _clean_team_name(name: str) -> str:
    """
    Strip non-breaking spaces, AP poll rankings like (4) or #12,
    and extra whitespace from team names sourced from VSIN's page.
    """
    n = name.replace("\xa0", " ")          # non-breaking space → regular space
    n = re.sub(r"\s*\(?\#?\d+\)?\s*$", "", n)  # trailing "(4)" or "#12"
    n = re.sub(r"^\s*\(?\#?\d+\)?\s*", "", n)  # leading "(4)" or "#12"
    return " ".join(n.split())             # collapse internal whitespace


def _normalize_team(name: str) -> str:
    """Lowercase + strip + apply common abbreviation expansions."""
    n = _clean_team_name(name).lower()
    # Remove leading articles
    n = re.sub(r"^(the|a|an)\s+", "", n)
    # Strip periods (e.g. "L.A. Clippers" → "la clippers") before abbreviation lookup
    n = n.replace(".", "")
    # Replace hyphens with spaces so "Loyola-Marymount" matches "Loyola Marymount"
    n = n.replace("-", " ")
    n = " ".join(n.split())  # collapse any double spaces left behind
    # Expand common prefixes (VSIN "CSU-X" → OddsTrader "Cal State X")
    n = re.sub(r"^csu\b", "cal state", n)
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
    # The shorter token list must match the beginning of the longer token list
    shorter, longer = (a_words, b_words) if len(a_words) <= len(b_words) else (b_words, a_words)
    if shorter and longer[:len(shorter)] == shorter:
        return True
    return False


# ---------------------------------------------------------------------------
# Alert de-duplication key (same logic as find_sharp_overlap.py)
# ---------------------------------------------------------------------------

def _alert_key(alert: SplitAlert) -> tuple:
    away = _clean_team_name(alert.away_team).lower()
    home = _clean_team_name(alert.home_team).lower()
    if alert.market == "Spread":
        raw_team = re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip()
        team = _clean_team_name(raw_team).lower()
        return (away, home, "spread", team)
    else:
        direction = "over" if alert.side.lower().startswith("over") else "under"
        return (away, home, direction)


# ---------------------------------------------------------------------------
# Past-game filter
# ---------------------------------------------------------------------------

WEEKDAY_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def _parse_alert_date(date_str: str) -> date | None:
    """
    Parse dates like "Wednesday, Feb 18" or "Wednesday,Feb 18".
    Returns a date object or None if unparseable.
    """
    m = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d+)",
        date_str, re.IGNORECASE
    )
    if not m:
        return None
    month = WEEKDAY_MONTH_MAP.get(m.group(1).lower()[:3])
    if not month:
        return None
    day = int(m.group(2))
    year = datetime.now().year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _filter_future_games(alerts: list[SplitAlert]) -> list[SplitAlert]:
    """Keep only alerts for today or future dates."""
    today = date.today()
    result = []
    for alert in alerts:
        game_date = _parse_alert_date(alert.date)
        if game_date is None or game_date >= today:
            result.append(alert)
    return result


# ---------------------------------------------------------------------------
# Bovada line lookup
# ---------------------------------------------------------------------------

def _both_teams_match(alert: SplitAlert, entry: BovadaEntry) -> bool:
    """
    Verify that the OddsTrader entry belongs to the same game as the alert
    by checking that BOTH teams match (entry.team + entry.opponent against
    alert.away_team + alert.home_team in either order).
    """
    if not entry.opponent:
        return False
    # entry.team matches one side AND entry.opponent matches the other
    if _teams_match(alert.away_team, entry.team) and _teams_match(alert.home_team, entry.opponent):
        return True
    if _teams_match(alert.home_team, entry.team) and _teams_match(alert.away_team, entry.opponent):
        return True
    return False


def _get_bovada_entry_for_alert(
    alert: SplitAlert,
    bovada_spreads: dict[str, BovadaEntry],
    bovada_totals: dict[str, BovadaEntry],
) -> BovadaEntry | None:
    """
    Find the BovadaEntry that corresponds to this alert.
    Requires BOTH teams in the matchup to match to avoid false positives
    from partial name matches (e.g. "Mississippi" != "Mississippi State").
    """
    if alert.market == "Spread":
        # Primary: match the sharp-side team AND verify both teams match
        team_name = re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip()
        for bov_name, entry in bovada_spreads.items():
            if _teams_match(team_name, entry.team) and _both_teams_match(alert, entry):
                return entry
        # Fallback: match either team but still require both-team verification
        for bov_name, entry in bovada_spreads.items():
            if _both_teams_match(alert, entry):
                return entry

    else:  # Total
        direction = "over" if alert.side.lower().startswith("over") else "under"
        for bov_name, entry in bovada_totals.items():
            if entry.direction == direction and _both_teams_match(alert, entry):
                return entry
        # Relaxed: match by both teams regardless of direction
        for bov_name, entry in bovada_totals.items():
            if _both_teams_match(alert, entry):
                return entry

    return None


def _has_bovada_best(
    alert: SplitAlert,
    bovada_spreads: dict[str, BovadaEntry],
    bovada_totals: dict[str, BovadaEntry],
) -> bool:
    entry = _get_bovada_entry_for_alert(alert, bovada_spreads, bovada_totals)
    return entry is not None and entry.is_best_price


# ---------------------------------------------------------------------------
# DK ∩ Circa overlap
# ---------------------------------------------------------------------------

def _find_overlap(
    dk_alerts: list[SplitAlert],
    circa_alerts: list[SplitAlert],
) -> list[SplitAlert]:
    """Return DK alerts that also appear in Circa alerts (same game + side)."""
    circa_keys = {_alert_key(a) for a in circa_alerts}
    return [a for a in dk_alerts if _alert_key(a) in circa_keys]


def _find_circa_only(
    dk_alerts: list[SplitAlert],
    circa_alerts: list[SplitAlert],
) -> list[SplitAlert]:
    """Return Circa alerts that do NOT appear in DK alerts."""
    dk_keys = {_alert_key(a) for a in dk_alerts}
    return [a for a in circa_alerts if _alert_key(a) not in dk_keys]


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def _confidence_score(tier: int, diff: int) -> int:
    """
    Composite score for ranking plays.
    Raw formula: (7 - tier) * 25 + diff
      Tier 1 base = 150, Tier 2 = 125, Tier 3 = 100,
      Tier 4 = 75,  Tier 5 = 50,  Tier 6 = 25

    We then linearly rescale to a 25-100 range using:
      - raw floor 50  (Tier 6 base 25 + minimum qualifying diff 25)
      - raw cap 213   (Tier 1 base 150 + elite diff ~63)
    Any score above the cap is clamped at 100.
    """
    raw_score = (7 - tier) * 25 + diff
    min_raw_score = 50   # Tier 6 (25) + threshold diff 25
    max_raw_score = 213  # Tier 1 (150) + elite diff ~63
    scaled = round(
        25 + ((raw_score - min_raw_score) / (max_raw_score - min_raw_score)) * 75
    )
    return max(25, min(100, scaled))


def run_pipeline(
    dk_text: str,
    circa_text: str,
    spreads_text: str,
    totals_text: str,
    sport: str = "cbb",
    threshold: int | None = None,
) -> list[Play]:
    """
    Full analysis pipeline.

    Returns ALL qualifying plays sorted by confidence_score (highest first).
    The caller is responsible for slicing to PROMPT_MAX_PLAYS for the Gemini
    prompt while showing the full list in the UI table.
    """
    config = get_config(sport)
    global _TEAM_ABBREV
    _TEAM_ABBREV = config["team_abbrev"]

    if threshold is None:
        threshold = config.get("threshold", 25)

    dk_alerts = parse_splits(dk_text, threshold)
    circa_alerts = parse_splits(circa_text, threshold) if circa_text.strip() else []
    bovada_spreads, bovada_totals = parse_oddstrader(spreads_text, totals_text)

    # Filter out past games
    dk_alerts = _filter_future_games(dk_alerts)
    circa_alerts = _filter_future_games(circa_alerts)

    # Sort DK by diff descending so within each tier higher diffs are added first
    dk_alerts.sort(key=lambda a: a.diff, reverse=True)

    dk_circa_overlap = _find_overlap(dk_alerts, circa_alerts)
    circa_only = _find_circa_only(dk_alerts, circa_alerts)
    circa_only.sort(key=lambda a: a.diff, reverse=True)

    selected: list[tuple[SplitAlert, int]] = []  # (alert, tier)
    seen_keys: set = set()

    def add(alert: SplitAlert, tier: int) -> None:
        key = _alert_key(alert)
        if key in seen_keys:
            return
        seen_keys.add(key)
        selected.append((alert, tier))

    # Tier 1: DK ∩ Circa ∩ Bovada best price (highest conviction)
    for alert in dk_circa_overlap:
        if _has_bovada_best(alert, bovada_spreads, bovada_totals):
            add(alert, 1)

    # Tier 2: Circa ∩ Bovada best price (Circa-only + Bovada, not in DK)
    for alert in circa_only:
        if _has_bovada_best(alert, bovada_spreads, bovada_totals):
            add(alert, 2)

    # Tier 3: DK ∩ Circa (not already Tier 1)
    for alert in dk_circa_overlap:
        add(alert, 3)

    # Tier 4: DK ∩ Bovada best price (not already Tier 1/3)
    for alert in dk_alerts:
        if _has_bovada_best(alert, bovada_spreads, bovada_totals):
            add(alert, 4)

    # Tier 5: Circa only (not already Tier 2)
    for alert in circa_only:
        add(alert, 5)

    # Tier 6: All remaining DK sharp plays
    for alert in dk_alerts:
        add(alert, 6)

    # Build Play objects, compute confidence scores, sort
    plays: list[Play] = []
    for alert, tier in selected:
        entry = _get_bovada_entry_for_alert(alert, bovada_spreads, bovada_totals)
        plays.append(Play(
            alert=alert,
            bovada_line=entry.bovada_line if entry else "",
            bovada_odds=entry.bovada_odds if entry else "",
            bovada_direction=entry.direction if entry else "",
            is_bovada_best_price=entry.is_best_price if entry else False,
            conviction_tier=tier,
            confidence_score=_confidence_score(tier, alert.diff),
        ))

    plays.sort(key=lambda p: p.confidence_score, reverse=True)
    return plays


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 5:
        print(
            "Usage: python pipeline.py "
            "<splits.txt> <circasplits.txt> <spreadsplits.txt> <totalsmarket.txt>"
        )
        sys.exit(1)

    with open(sys.argv[1]) as f:
        dk = f.read()
    with open(sys.argv[2]) as f:
        circa = f.read()
    with open(sys.argv[3]) as f:
        spreads = f.read()
    with open(sys.argv[4]) as f:
        totals = f.read()

    plays = run_pipeline(dk, circa, spreads, totals)

    if not plays:
        print("No plays found.")
    else:
        print(f"\n=== Selected Plays ({len(plays)}) ===\n")
        tier_labels = {
            1: "DK+Circa+Bovada Best", 2: "Circa+Bovada Best",
            3: "DK+Circa", 4: "DK+Bovada Best",
            5: "Circa Only", 6: "DK Only",
        }
        for i, play in enumerate(plays, 1):
            a = play.alert
            line = f"{play.bovada_line} ({play.bovada_odds})" if play.bovada_line else "N/A"
            print(
                f"  {i}. [{tier_labels[play.conviction_tier]}] "
                f"{a.away_team} @ {a.home_team} | {a.market} | {a.side} | "
                f"Handle:{a.handle_pct}% Bets:{a.bets_pct}% Diff:{a.diff}% | "
                f"Bovada: {line}"
            )
