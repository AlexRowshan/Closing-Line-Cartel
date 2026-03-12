"""
Sharp Betting Analysis Pipeline
---------------------------------
Orchestrates the full filtering pipeline:
  1. Parse VSIN DK and Circa splits
  2. Parse OddsTrader Bovada lines
  3. Filter out past games
  4. Tiered play selection:
       Tier 1: DK ∩ Circa ∩ Bovada best price
       Tier 2: Circa ∩ Bovada best price (Circa-only)
       Tier 3: DK ∩ Circa
       Tier 4: DK ∩ Bovada best price
       Tier 5: Circa only
       Tier 6: All remaining DK sharp plays
  5. Attach Bovada line to each selected play
"""

from dataclasses import dataclass

from parsers import SplitAlert, parse_splits, BovadaEntry, parse_oddstrader
from sport_config import get_config

from .team_utils import _clean_team_name, _alert_key, set_team_abbrev
from .date_filter import _filter_future_games
from .bovada_match import _get_bovada_entry_for_alert, _has_bovada_best

PROMPT_MAX_PLAYS = 5


@dataclass
class Play:
    alert: SplitAlert
    bovada_line: str          # e.g. "+15.0" or "135.5"
    bovada_odds: str          # e.g. "-115" or "-110"
    bovada_direction: str     # "over"/"under" for totals, "" for spreads
    is_bovada_best_price: bool
    conviction_tier: int      # 1 = highest, 6 = lowest
    confidence_score: int     # composite score for ranking: (7-tier)*25 + diff

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
    min_raw_score = 50
    max_raw_score = 213
    scaled = round(
        25 + ((raw_score - min_raw_score) / (max_raw_score - min_raw_score)) * 75
    )
    return max(25, min(100, scaled))


def _find_overlap(dk_alerts: list[SplitAlert], circa_alerts: list[SplitAlert]) -> list[SplitAlert]:
    """Return DK alerts that also appear in Circa alerts (same game + side)."""
    circa_keys = {_alert_key(a) for a in circa_alerts}
    return [a for a in dk_alerts if _alert_key(a) in circa_keys]


def _find_circa_only(dk_alerts: list[SplitAlert], circa_alerts: list[SplitAlert]) -> list[SplitAlert]:
    """Return Circa alerts that do NOT appear in DK alerts."""
    dk_keys = {_alert_key(a) for a in dk_alerts}
    return [a for a in circa_alerts if _alert_key(a) not in dk_keys]


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
    set_team_abbrev(config["team_abbrev"])

    if threshold is None:
        threshold = config.get("threshold", 25)

    dk_alerts = parse_splits(dk_text, threshold)
    circa_alerts = parse_splits(circa_text, threshold) if circa_text.strip() else []
    bovada_spreads, bovada_totals = parse_oddstrader(spreads_text, totals_text)

    dk_alerts = _filter_future_games(dk_alerts)
    circa_alerts = _filter_future_games(circa_alerts)

    dk_alerts.sort(key=lambda a: a.diff, reverse=True)

    dk_circa_overlap = _find_overlap(dk_alerts, circa_alerts)
    circa_only = _find_circa_only(dk_alerts, circa_alerts)
    circa_only.sort(key=lambda a: a.diff, reverse=True)

    selected: list[tuple[SplitAlert, int]] = []
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
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from pipeline.runner import run_pipeline as _run

    if len(sys.argv) < 5:
        print(
            "Usage: python pipeline/runner.py "
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

    plays = _run(dk, circa, spreads, totals)

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
