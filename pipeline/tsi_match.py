"""
TSI projection matching and edge calculation.

Matches VSIN SplitAlerts against TSI projections to compute alignment
edges, and checks for explicit TSI bet picks.
"""

import re

from parsers import TSIProjection, TSIBet
from .team_utils import _teams_match


def _translate_tsi_spread(proj: TSIProjection, target_team: str) -> float | None:
    """
    Return the projected spread line for target_team.

    Positive TSI spread means team_left is favored, so:
      - team_left's line = -tsi_spread
      - team_right's line = +tsi_spread

    Returns None when tsi_spread == 0.0 (no spread projection exists).
    """
    if proj.tsi_spread == 0.0:
        return None
    if _teams_match(target_team, proj.team_left):
        return -proj.tsi_spread
    if _teams_match(target_team, proj.team_right):
        return proj.tsi_spread
    return None


def _find_tsi_projection(alert, projections: list[TSIProjection]) -> TSIProjection | None:
    """Match a VSIN alert to a TSI projection by matching both teams."""
    for proj in projections:
        if (
            (_teams_match(alert.away_team, proj.team_left) and _teams_match(alert.home_team, proj.team_right))
            or (_teams_match(alert.away_team, proj.team_right) and _teams_match(alert.home_team, proj.team_left))
        ):
            return proj
    return None


def _calc_spread_edge(bovada_line: str, tsi_line: float) -> float:
    """
    Edge = bovada_line - tsi_line.

    Positive = TSI projects team is MORE of a favorite than the book → edge favors that team.
    Example: Bovada Georgia -2, TSI Georgia -3.7 → -2 - (-3.7) = +1.7
    """
    return float(bovada_line) - tsi_line


def _calc_total_edge(bovada_total: str, tsi_total: float, direction: str) -> float:
    """
    Edge for totals.

    raw_diff = tsi_total - bovada_total
    Over: positive raw_diff = edge (TSI higher than book)
    Under: negative raw_diff = edge (TSI lower than book)
    """
    raw_diff = tsi_total - float(bovada_total)
    if direction == "over":
        return raw_diff
    else:  # under
        return -raw_diff


def _is_tsi_bet_match(alert, bet: TSIBet) -> bool:
    """Check if a VSIN alert matches an explicit TSI bet pick."""
    if bet.market == "spread" and alert.market == "Spread":
        # Extract team name from alert side (e.g. "Georgia -2" → "Georgia")
        team_name = re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip()
        return _teams_match(team_name, bet.side)

    if bet.market == "total" and alert.market == "Total":
        # Check direction matches
        alert_dir = "over" if alert.side.lower().startswith("over") else "under"
        if alert_dir != bet.side:
            return False
        # Check at least one team matches
        for bet_team in bet.teams:
            if _teams_match(alert.away_team, bet_team) or _teams_match(alert.home_team, bet_team):
                return True

    return False


def derive_tsi_side(
    proj: TSIProjection, bovada_entry
) -> tuple[str, str] | None:
    """
    Determine the sharp (market, side) for a TSI-only game.

    Computes spread and total edges; returns whichever is larger.
    Returns None if no meaningful edge exists.
    """
    spread_edge = 0.0
    total_edge = 0.0

    if bovada_entry.market == "spread" and bovada_entry.bovada_line:
        # Determine which team this entry is for
        tsi_line = _translate_tsi_spread(proj, bovada_entry.team)
        if tsi_line is not None:
            spread_edge = _calc_spread_edge(bovada_entry.bovada_line, tsi_line)

    if bovada_entry.market == "total" and bovada_entry.bovada_line and proj.tsi_total != 0.0:
        # For totals, compute both over/under and take the positive edge
        # Skip when tsi_total == 0.0 — means no total projection exists
        over_edge = _calc_total_edge(bovada_entry.bovada_line, proj.tsi_total, "over")
        under_edge = _calc_total_edge(bovada_entry.bovada_line, proj.tsi_total, "under")
        total_edge = max(over_edge, under_edge)

    if abs(spread_edge) >= abs(total_edge) and abs(spread_edge) > 0:
        # Spread edge: positive means TSI favors the team more than book
        if spread_edge > 0:
            line_str = bovada_entry.bovada_line
            if not line_str.startswith(("+", "-")):
                line_str = "+" + line_str
            return ("Spread", f"{bovada_entry.team} {line_str}")
        else:
            # Opposite team has the edge — but we need spread entry for them
            return None
    elif total_edge > 0:
        direction = "Over" if (proj.tsi_total - float(bovada_entry.bovada_line)) > 0 else "Under"
        return ("Total", f"{direction} {bovada_entry.bovada_line}")

    return None


