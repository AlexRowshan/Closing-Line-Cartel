"""
Bovada line lookup: matches VSIN SplitAlert objects against
OddsTrader BovadaEntry records using fuzzy two-team verification.
"""

import re

from .team_utils import _teams_match


def _both_teams_match(alert, entry) -> bool:
    """
    Verify that the OddsTrader entry belongs to the same game as the alert
    by checking that BOTH teams match (entry.team + entry.opponent against
    alert.away_team + alert.home_team in either order).
    """
    if not entry.opponent:
        return False
    if _teams_match(alert.away_team, entry.team) and _teams_match(alert.home_team, entry.opponent):
        return True
    if _teams_match(alert.home_team, entry.team) and _teams_match(alert.away_team, entry.opponent):
        return True
    return False


def _get_bovada_entry_for_alert(alert, bovada_spreads: dict, bovada_totals: dict):
    """
    Find the BovadaEntry that corresponds to this alert.
    Requires BOTH teams in the matchup to match to avoid false positives
    from partial name matches (e.g. "Mississippi" != "Mississippi State").
    """
    if alert.market == "Spread":
        team_name = re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip()
        for bov_name, entry in bovada_spreads.items():
            if _teams_match(team_name, entry.team) and _both_teams_match(alert, entry):
                return entry
        for bov_name, entry in bovada_spreads.items():
            if _both_teams_match(alert, entry):
                return entry

    else:  # Total
        direction = "over" if alert.side.lower().startswith("over") else "under"
        for bov_name, entry in bovada_totals.items():
            if entry.direction == direction and _both_teams_match(alert, entry):
                return entry
        for bov_name, entry in bovada_totals.items():
            if _both_teams_match(alert, entry):
                return entry

    return None


def _has_bovada_best(alert, bovada_spreads: dict, bovada_totals: dict) -> bool:
    entry = _get_bovada_entry_for_alert(alert, bovada_spreads, bovada_totals)
    return entry is not None and entry.is_best_price
