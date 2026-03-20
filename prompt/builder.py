"""
Gemini Deep Research Prompt Builder
--------------------------------------
Formats the selected Play objects into the exact sharp betting analysis
prompt template used with Gemini Deep Research.
Supports both CBB and NBA sport modes.
"""

import re

from pipeline import _clean_team_name
from .cbb_template import _build_cbb_prompt
from .nba_template import _build_nba_prompt


def _format_line_label(play) -> str:
    """
    Build the exact line string for the prompt, e.g.:
      "Under 135.5 (-110)"
      "San Francisco +15.0 (-115)"
    """
    if play.market == "Total":
        if play.bovada_line:
            number = play.bovada_line
            odds = play.bovada_odds or "-110"
            direction = play.bovada_direction.capitalize() if play.bovada_direction else (
                "Over" if play.side.lower().startswith("over") else "Under"
            )
        else:
            m = re.match(r"(Over|Under)\s+([\d.]+)", play.side, re.I)
            direction = m.group(1).capitalize() if m else "Over"
            number = m.group(2) if m else ""
            odds = "-110"
        return f"{direction} {number} ({odds})"

    else:  # Spread
        if play.bovada_line:
            team_name = _clean_team_name(re.sub(r"\s+[+-][\d.]+$", "", play.side).strip())
            line = play.bovada_line
            odds = play.bovada_odds or "-110"
        else:
            team_name = _clean_team_name(re.sub(r"\s+[+-][\d.]+$", "", play.side).strip())
            m = re.search(r"([+-][\d.]+)$", play.side)
            line = m.group(1) if m else ""
            odds = "-110"

        if line and not line.startswith(("+", "-")):
            line = "+" + line

        return f"{team_name} {line} ({odds})"


def _build_games_section(plays: list) -> str:
    lines = []
    for i, play in enumerate(plays, 1):
        matchup = f"{_clean_team_name(play.away_team)} @ {_clean_team_name(play.home_team)}"
        market_label = "Total Options" if play.market == "Total" else "Spread Options"
        line_label = _format_line_label(play)

        lines.append(f"### Game {i}: {matchup}")
        lines.append(f"**{market_label}:**")
        lines.append(f"- {line_label}")
        lines.append("")

    return "\n".join(lines).rstrip()


def build_prompt(plays: list, sport: str = "cbb") -> str:
    if not plays:
        return "No sharp plays found for today's slate."

    games_section = _build_games_section(plays)
    n_eliminated = len(plays) - 1

    if sport.lower() == "nba":
        return _build_nba_prompt(plays, games_section, n_eliminated)
    return _build_cbb_prompt(plays, games_section, n_eliminated)
