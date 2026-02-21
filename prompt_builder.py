"""
Gemini Deep Research Prompt Builder
--------------------------------------
Formats the selected Play objects into the exact sharp betting analysis
prompt template used with Gemini Deep Research.
"""

import re
from pipeline import Play, _clean_team_name


def _format_line_label(play: Play) -> str:
    """
    Build the exact line string for the prompt, e.g.:
      "Under 135.5 (-110)"
      "San Francisco +15.0 (-115)"
    """
    alert = play.alert

    if alert.market == "Total":
        # Use Bovada line if available, else fall back to VSIN line number
        if play.bovada_line:
            number = play.bovada_line
            odds = play.bovada_odds or "-110"
            direction = play.bovada_direction.capitalize() if play.bovada_direction else (
                "Over" if alert.side.lower().startswith("over") else "Under"
            )
        else:
            # Parse number from alert.side e.g. "Under 135.5"
            m = re.match(r"(Over|Under)\s+([\d.]+)", alert.side, re.I)
            direction = m.group(1).capitalize() if m else "Over"
            number = m.group(2) if m else ""
            odds = "-110"
        return f"{direction} {number} ({odds})"

    else:  # Spread
        if play.bovada_line:
            # alert.side = "Team Name -9" — extract team name, then clean it
            team_name = _clean_team_name(re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip())
            line = play.bovada_line
            odds = play.bovada_odds or "-110"
        else:
            # Fall back to VSIN line
            team_name = _clean_team_name(re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip())
            m = re.search(r"([+-][\d.]+)$", alert.side)
            line = m.group(1) if m else ""
            odds = "-110"

        # Ensure line has explicit + or -
        if line and not line.startswith(("+", "-")):
            line = "+" + line

        return f"{team_name} {line} ({odds})"


def build_prompt(plays: list[Play]) -> str:
    if not plays:
        return "No sharp plays found for today's slate."

    # -----------------------------------------------------------------------
    # Build games section
    # -----------------------------------------------------------------------
    games_section_lines = []
    for i, play in enumerate(plays, 1):
        alert = play.alert
        matchup = f"{_clean_team_name(alert.away_team)} at {_clean_team_name(alert.home_team)}"
        market_label = "Total Options" if alert.market == "Total" else "Spread Options"
        line_label = _format_line_label(play)

        games_section_lines.append(f"### Game {i}: {matchup}")
        games_section_lines.append(f"**{market_label}:**")
        games_section_lines.append(f"- {line_label}")
        games_section_lines.append("")

    games_section = "\n".join(games_section_lines).rstrip()

    # Count games for the elimination section
    n_plays = len(plays)
    n_eliminated = n_plays - 1

    prompt = f"""# SHARP BETTING ANALYSIS: CBB SLATE

## YOUR TASK
You are a professional CBB sharp handicapper with 15 years of experience. Analyze today's slate and select the SINGLE highest-value betting opportunity from the exact options provided below.

---

## ⚠️ THE ONLY BETTING OPTIONS YOU CAN RECOMMEND ⚠️


## GAMES TO ANALYZE


{games_section}

---

## 🚨 ABSOLUTE CONSTRAINTS 🚨

**1. LINE DISCIPLINE:**
- These lines ARE the market consensus
- Do NOT claim different lines exist elsewhere
- Do NOT recommend lines not listed above
- Your final recommendation MUST be copy-pasted exactly from the list above

**2. MANDATORY OUTPUT SECTIONS:**
- **SHARP BET SELECTION:** Pick ONE option from the options above
- **ELIMINATED OPTIONS:** Explain why you rejected every non-selected option

**If you violate either constraint, your analysis is invalid.**

---

## RESEARCH FRAMEWORK

Analyze each option through these factors:

**Factor 1: Advanced Efficiency Metrics** - Adjusted offensive/defensive efficiency per 100 possessions, turnover rate, offensive rebounding rate

**Factor 2: Pace and Tempo Dynamics** - Possessions per game, efficiency vs speed correlation, half-court vs transition effectiveness

**Factor 3: Situational Spots** - Let-down games after emotional wins, travel fatigue from road stretches, time zone shifts

**Factor 4: Home/Road Splits** - Venue-specific advantages, shooting percentage variance by location

**Factor 5: Roster Depth & Injuries** - Primary ball-handler status, bench talent drop-off, foul trouble risks for key players

---

## REQUIRED OUTPUT FORMAT

### SHARP BET SELECTION

**Recommended Bet:** [Copy-paste exactly from the line options above]

**Why This is the Play:**
[2-3 paragraphs explaining which factors create the edge and why this specific line is mispriced]

**Overall Confidence:** [Low/Medium/High]

**Risk Factors:** [What could go wrong with this bet]

---

### ELIMINATED OPTIONS (MANDATORY)

**YOU MUST EXPLAIN WHY YOU REJECTED EACH OF THE {n_eliminated} NON-SELECTED OPTIONS.**

Format each elimination like this:

**Option [X]: [Exact option text]**
- **Why Eliminated:** [2-3 sentences citing which of the 5 factors were weak or contradicted this bet]

---

## CRITICAL REMINDERS

✅ Your recommendation must be EXACTLY one of the options listed at the top
✅ The eliminated options section is MANDATORY
✅ Use recent data (last 15 games) and cite sources when possible. Do not rely on internal knowledge; verify current form.
✅ Think like a sharp bettor finding market inefficiencies, not a fan picking favorites

❌ Do NOT recommend lines not listed above
❌ Do NOT claim "the consensus line is different than what you provided"
❌ Do NOT skip the eliminated options section"""

    return prompt


if __name__ == "__main__":
    # Quick test with dummy plays
    from vsin_splits_parser import SplitAlert
    from pipeline import Play

    dummy_alerts = [
        SplitAlert(
            date="Wednesday, Feb 19",
            away_team="Illinois",
            home_team="USC",
            market="Total",
            side="Under 151.0",
            handle_pct=72,
            bets_pct=38,
            diff=34,
        ),
        SplitAlert(
            date="Wednesday, Feb 19",
            away_team="Gonzaga",
            home_team="San Francisco",
            market="Spread",
            side="San Francisco +15.0",
            handle_pct=68,
            bets_pct=42,
            diff=26,
        ),
    ]

    dummy_plays = [
        Play(alert=dummy_alerts[0], bovada_line="151.0", bovada_odds="-110",
             bovada_direction="under", is_bovada_best_price=True, conviction_tier=1),
        Play(alert=dummy_alerts[1], bovada_line="+15.0", bovada_odds="-115",
             bovada_direction="", is_bovada_best_price=False, conviction_tier=2),
    ]

    print(build_prompt(dummy_plays))
