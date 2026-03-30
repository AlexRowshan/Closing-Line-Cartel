"""
Sharp Betting Analysis Pipeline — Game-Driven Architecture
------------------------------------------------------------
Evaluates EVERY game on the board via independent scoring modules:
  Module B — TSI: projection edge scoring (0–65, primary driver)
  Module A — Splits: tiered DK/Circa overlap scoring (0–35)
Composite confidence_score = tsi_score + splits_score, clamped [0, 100].
65/35 weighted system: TSI edge is the primary signal.
"""

import re
from dataclasses import dataclass

from parsers import SplitAlert, parse_splits, BovadaEntry, parse_oddstrader
from parsers import TSIProjection, TSIBet
from sport_config import get_config

from .team_utils import (
    _clean_team_name, _alert_key, _game_key, _normalize_team,
    _teams_match, set_team_abbrev,
)
from .date_filter import _filter_future_games
from .bovada_match import _get_bovada_entry_for_alert, _has_bovada_best
from .tsi_match import (
    _calc_spread_edge, _calc_total_edge, _translate_tsi_spread,
    _find_tsi_projection, _is_tsi_bet_match, derive_tsi_side,
)

PROMPT_MAX_PLAYS = 5


@dataclass
class Play:
    away_team: str
    home_team: str
    date: str
    market: str                    # "Spread" or "Total"
    side: str                      # e.g. "Oklahoma ST -1.5", "Under 151.5"
    handle_pct: int | None         # None for TSI-only games
    bets_pct: int | None
    diff: int | None
    bovada_line: str
    bovada_odds: str
    bovada_direction: str
    is_bovada_best_price: bool
    conviction_tier: int | None    # None for TSI-only games
    confidence_score: int
    tsi_edge: float = 0.0
    is_tsi_bet: bool = False
    source: str = ""               # "splits", "tsi", "splits+tsi"

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "away": _clean_team_name(self.away_team),
            "home": _clean_team_name(self.home_team),
            "market": self.market,
            "side": self.side,
            "handle_pct": self.handle_pct,
            "bets_pct": self.bets_pct,
            "diff": self.diff,
            "bovada_line": self.bovada_line,
            "bovada_odds": self.bovada_odds,
            "bovada_direction": self.bovada_direction,
            "is_bovada_best_price": self.is_bovada_best_price,
            "conviction_tier": self.conviction_tier,
            "confidence_score": self.confidence_score,
            "tsi_edge": self.tsi_edge,
            "is_tsi_bet": self.is_tsi_bet,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Module A — Splits scoring
# ---------------------------------------------------------------------------

def _find_overlap(dk_alerts: list[SplitAlert], circa_alerts: list[SplitAlert]) -> list[SplitAlert]:
    """Return DK alerts that also appear in Circa alerts (same game + side)."""
    circa_keys = {_alert_key(a) for a in circa_alerts}
    return [a for a in dk_alerts if _alert_key(a) in circa_keys]


def _find_circa_only(dk_alerts: list[SplitAlert], circa_alerts: list[SplitAlert]) -> list[SplitAlert]:
    """Return Circa alerts that do NOT appear in DK alerts."""
    dk_keys = {_alert_key(a) for a in dk_alerts}
    return [a for a in circa_alerts if _alert_key(a) not in dk_keys]


def _splits_confidence(tier: int, diff: int) -> int:
    """
    Splits score in range 0-35.
    Tier base: T1=32, T2=26, T3=20, T4=14, T5=12, T6=7.
    Circa is weighted 2x DK: diff bonus = diff/5 for DK tiers, diff/2.5
    for Circa tiers, so a 20% Circa diff ≈ 40% DK diff.
    Circa-involved tiers: T1 (DK+Circa+Bovada), T2 (Circa+Bovada),
    T3 (DK+Circa), T5 (Circa only).
    """
    tier_bases = {1: 32, 2: 26, 3: 20, 4: 14, 5: 12, 6: 7}
    circa_tiers = {1, 2, 3, 5}
    tier_base = tier_bases.get(tier, 7)
    diff_bonus = diff / 2.5 if tier in circa_tiers else diff / 5
    return max(0, min(35, round(tier_base + diff_bonus)))


def _score_splits(
    dk_alerts: list[SplitAlert],
    circa_alerts: list[SplitAlert],
    bovada_spreads: dict,
    bovada_totals: dict,
) -> list[tuple[SplitAlert, int, int]]:
    """
    Run the tiered selection and return (alert, tier, splits_score) triples.
    """
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

    # Tier 1: DK ∩ Circa ∩ Bovada best
    for alert in dk_circa_overlap:
        if _has_bovada_best(alert, bovada_spreads, bovada_totals):
            add(alert, 1)
    # Tier 2: Circa ∩ Bovada best (Circa-only)
    for alert in circa_only:
        if _has_bovada_best(alert, bovada_spreads, bovada_totals):
            add(alert, 2)
    # Tier 3: DK ∩ Circa
    for alert in dk_circa_overlap:
        add(alert, 3)
    # Tier 4: DK ∩ Bovada best
    for alert in dk_alerts:
        if _has_bovada_best(alert, bovada_spreads, bovada_totals):
            add(alert, 4)
    # Tier 5: Circa only
    for alert in circa_only:
        add(alert, 5)
    # Tier 6: All remaining DK sharp plays
    for alert in dk_alerts:
        add(alert, 6)

    results = []
    for alert, tier in selected:
        score = _splits_confidence(tier, alert.diff)
        results.append((alert, tier, score))
    return results


# ---------------------------------------------------------------------------
# Module B — TSI scoring
# ---------------------------------------------------------------------------

def _score_tsi_for_alert(
    alert: SplitAlert,
    bovada_entry: BovadaEntry | None,
    proj: TSIProjection | None,
    bets: list[TSIBet],
) -> tuple[int, float, bool]:
    """
    TSI score for a splits-based play. Returns (tsi_score, edge, is_tsi_bet).
    Score range: 0-60. Linear scaling based on edge size.
    Spread: edge * 10, Total: edge * 6, Explicit pick bonus: +15.
    """
    tsi_edge = 0.0
    tsi_score = 0
    is_tsi_bet = False

    if proj and bovada_entry:
        if alert.market == "Spread":
            team_name = re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip()
            tsi_line = _translate_tsi_spread(proj, team_name)
            if tsi_line is not None:
                tsi_edge = _calc_spread_edge(bovada_entry.bovada_line, tsi_line)
                tsi_score = round(max(0, tsi_edge) * 10)
        elif alert.market == "Total" and proj.tsi_total != 0.0:
            direction = bovada_entry.direction if bovada_entry.direction else (
                "over" if alert.side.lower().startswith("over") else "under"
            )
            tsi_edge = _calc_total_edge(bovada_entry.bovada_line, proj.tsi_total, direction)
            tsi_score = round(max(0, tsi_edge) * 6)

    for bet in bets:
        if _is_tsi_bet_match(alert, bet):
            is_tsi_bet = True
            tsi_score += 15
            break

    tsi_score = max(0, min(65, tsi_score))
    return tsi_score, tsi_edge, is_tsi_bet


def _score_tsi_standalone(
    proj: TSIProjection,
    bovada_spread: BovadaEntry | None,
    bovada_total: BovadaEntry | None,
    bets: list[TSIBet],
) -> list[tuple[str, str, int, float, bool, BovadaEntry | None]]:
    """
    TSI scoring for games with NO split data.
    Returns list of (market, side, tsi_score, edge, is_tsi_bet, bovada_entry).
    Linear scaling: Spread edge * 10, Total edge * 6. Explicit pick +15. Cap 70.
    Only includes entries with positive edge.
    """
    results = []

    # Check spread edge
    if bovada_spread and bovada_spread.bovada_line:
        tsi_line = _translate_tsi_spread(proj, bovada_spread.team)
        if tsi_line is not None:
            edge = _calc_spread_edge(bovada_spread.bovada_line, tsi_line)
            if edge > 0:
                score = round(edge * 10)

                line_str = bovada_spread.bovada_line
                if not line_str.startswith(("+", "-")):
                    line_str = "+" + line_str
                side = f"{bovada_spread.team} {line_str}"

                is_tsi_bet = False
                for bet in bets:
                    if bet.market == "spread":
                        team_name = re.sub(r"\s+[+-][\d.]+$", "", side).strip()
                        if _teams_match(team_name, bet.side):
                            is_tsi_bet = True
                            score += 15
                            break

                score = max(0, min(65, score))
                if score > 0:
                    results.append(("Spread", side, score, edge, is_tsi_bet, bovada_spread))

    # Check total edge — skip when tsi_total == 0.0 (no projection)
    if bovada_total and bovada_total.bovada_line and proj.tsi_total != 0.0:
        over_edge = _calc_total_edge(bovada_total.bovada_line, proj.tsi_total, "over")
        under_edge = _calc_total_edge(bovada_total.bovada_line, proj.tsi_total, "under")

        best_direction = "over" if over_edge >= under_edge else "under"
        best_edge = max(over_edge, under_edge)

        if best_edge > 0:
            score = round(best_edge * 6)
            side = f"{'Over' if best_direction == 'over' else 'Under'} {bovada_total.bovada_line}"

            is_tsi_bet = False
            for bet in bets:
                if bet.market == "total" and bet.side == best_direction:
                    for bt in bet.teams:
                        if (_teams_match(proj.team_left, bt) or _teams_match(proj.team_right, bt)):
                            is_tsi_bet = True
                            score += 15
                            break
                    if is_tsi_bet:
                        break

            score = max(0, min(65, score))
            if score > 0:
                results.append(("Total", side, score, best_edge, is_tsi_bet, bovada_total))

    return results


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    dk_text: str,
    circa_text: str,
    spreads_text: str,
    totals_text: str,
    tsi_projections: list[TSIProjection] | None = None,
    tsi_bets: list[TSIBet] | None = None,
    sport: str = "cbb",
    threshold: int | None = None,
) -> list[Play]:
    """
    Game-driven analysis pipeline.

    Builds a master game registry from all sources, scores each game with
    independent modules (splits + TSI), and returns ALL qualifying plays
    sorted by confidence_score (highest first).
    """
    config = get_config(sport)
    set_team_abbrev(config["team_abbrev"])

    if threshold is None:
        threshold = config.get("threshold", 25)

    tsi_projections = tsi_projections or []
    tsi_bets = tsi_bets or []

    # --- Parse all sources ---
    dk_alerts = parse_splits(dk_text, threshold)
    circa_alerts = parse_splits(circa_text, threshold) if circa_text.strip() else []
    bovada_spreads, bovada_totals = parse_oddstrader(spreads_text, totals_text)

    dk_alerts = _filter_future_games(dk_alerts)
    circa_alerts = _filter_future_games(circa_alerts)

    # --- Module A: Score splits ---
    scored_splits = _score_splits(dk_alerts, circa_alerts, bovada_spreads, bovada_totals)

    # Build a set of game keys that have splits data (to avoid double-counting in TSI)
    splits_game_keys: set[tuple[str, str]] = set()
    # Also track (game_key, market, side_key) to dedup across modules
    seen_play_keys: set = set()

    plays: list[Play] = []

    for alert, tier, splits_score in scored_splits:
        gk = _game_key(alert.away_team, alert.home_team)
        splits_game_keys.add(gk)

        entry = _get_bovada_entry_for_alert(alert, bovada_spreads, bovada_totals)
        proj = _find_tsi_projection(alert, tsi_projections)

        tsi_score, tsi_edge, is_tsi_bet = _score_tsi_for_alert(
            alert, entry, proj, tsi_bets
        )

        confidence = min(100, tsi_score + splits_score)

        # Veto penalty: TSI violently disagrees with splits-driven play
        if tier is not None and proj is not None:
            if alert.market == "Spread" and tsi_edge < -2.5:
                confidence = confidence // 2
            elif alert.market == "Total" and tsi_edge < -4.0:
                confidence = confidence // 2

        confidence = max(0, confidence)
        source = "splits+tsi" if tsi_score > 0 else "splits"

        play_key = _alert_key(alert)
        if play_key in seen_play_keys:
            continue
        seen_play_keys.add(play_key)

        plays.append(Play(
            away_team=alert.away_team,
            home_team=alert.home_team,
            date=alert.date,
            market=alert.market,
            side=alert.side,
            handle_pct=alert.handle_pct,
            bets_pct=alert.bets_pct,
            diff=alert.diff,
            bovada_line=entry.bovada_line if entry else "",
            bovada_odds=entry.bovada_odds if entry else "",
            bovada_direction=entry.direction if entry else "",
            is_bovada_best_price=entry.is_best_price if entry else False,
            conviction_tier=tier,
            confidence_score=confidence,
            tsi_edge=tsi_edge,
            is_tsi_bet=is_tsi_bet,
            source=source,
        ))

    # --- Module B: TSI-only games (no split data) ---
    def _proj_matches_game_key(proj: TSIProjection, gk_set: set) -> bool:
        """Check if a TSI projection matches any game in the splits set using fuzzy matching."""
        for s_gk in gk_set:
            # s_gk is (norm_a, norm_b) — check fuzzy match against proj teams
            if ((_teams_match(proj.team_left, s_gk[0]) and _teams_match(proj.team_right, s_gk[1]))
                or (_teams_match(proj.team_left, s_gk[1]) and _teams_match(proj.team_right, s_gk[0]))):
                return True
        return False

    def _find_bovada_for_proj(proj: TSIProjection, bovada_dict: dict) -> BovadaEntry | None:
        """Find a Bovada entry matching a TSI projection using fuzzy team matching."""
        for _name, entry in bovada_dict.items():
            if not entry.opponent:
                continue
            if ((_teams_match(proj.team_left, entry.team) and _teams_match(proj.team_right, entry.opponent))
                or (_teams_match(proj.team_left, entry.opponent) and _teams_match(proj.team_right, entry.team))):
                return entry
        return None

    for proj in tsi_projections:
        if _proj_matches_game_key(proj, splits_game_keys):
            continue

        # Find bovada entries for this game using fuzzy matching
        bov_spread = _find_bovada_for_proj(proj, bovada_spreads)
        bov_total = _find_bovada_for_proj(proj, bovada_totals)

        if not bov_spread and not bov_total:
            continue

        tsi_results = _score_tsi_standalone(proj, bov_spread, bov_total, tsi_bets)

        for market, side, tsi_score, edge, is_bet, bov_entry in tsi_results:
            if tsi_score <= 0:
                continue

            # Use a simple dedup key for TSI-only plays
            away = _clean_team_name(proj.team_left).lower()
            home = _clean_team_name(proj.team_right).lower()
            if market == "Spread":
                raw_team = re.sub(r"\s+[+-][\d.]+$", "", side).strip().lower()
                play_key = (away, home, "spread", raw_team)
            else:
                direction = "over" if side.lower().startswith("over") else "under"
                play_key = (away, home, direction)

            if play_key in seen_play_keys:
                continue
            seen_play_keys.add(play_key)

            # Determine date from bovada entry or use empty
            date_str = ""

            plays.append(Play(
                away_team=proj.team_left,
                home_team=proj.team_right,
                date=date_str,
                market=market,
                side=side,
                handle_pct=None,
                bets_pct=None,
                diff=None,
                bovada_line=bov_entry.bovada_line if bov_entry else "",
                bovada_odds=bov_entry.bovada_odds if bov_entry else "",
                bovada_direction=bov_entry.direction if bov_entry else "",
                is_bovada_best_price=bov_entry.is_best_price if bov_entry else False,
                conviction_tier=None,
                confidence_score=max(0, min(100, tsi_score)),
                tsi_edge=edge,
                is_tsi_bet=is_bet,
                source="tsi",
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
            tier_str = tier_labels.get(play.conviction_tier, "TSI Only")
            line = f"{play.bovada_line} ({play.bovada_odds})" if play.bovada_line else "N/A"
            handle = f"{play.handle_pct}%" if play.handle_pct is not None else "—"
            bets = f"{play.bets_pct}%" if play.bets_pct is not None else "—"
            diff = f"{play.diff}%" if play.diff is not None else "—"
            print(
                f"  {i}. [{tier_str}] "
                f"{play.away_team} @ {play.home_team} | {play.market} | {play.side} | "
                f"Handle:{handle} Bets:{bets} Diff:{diff} | "
                f"Bovada: {line} | Source: {play.source}"
            )
