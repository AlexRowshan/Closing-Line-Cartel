"""
Parser for Tyler Shoemaker's TSI (T Shoe Index) projections.

Extracts projected spreads/totals and specific bet picks from raw article text.
"""

import re
import sys
from dataclasses import dataclass, field


@dataclass
class TSIProjection:
    date: str           # "3/19/2026"
    team_left: str      # first team (positive TSI = this team favored)
    team_right: str     # second team
    tsi_spread: float   # projected spread
    tsi_total: float    # projected total


@dataclass
class TSIBet:
    teams: list[str] = field(default_factory=list)  # [team] for spread, [team1, team2] for total
    market: str = ""    # "spread" or "total"
    side: str = ""      # team name for spread, "over"/"under" for total
    line: float = 0.0   # the number


def _find_section_bounds(lines: list[str]) -> tuple[int, int]:
    """Find start/end of Men's Projections section."""
    start = -1
    end = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if start == -1 and re.search(r"(?i)men.s\s+projections", stripped):
            start = i
        elif start != -1 and (
            re.search(r"(?i)women.s\s+projections", stripped)
            or "Follow me on X" in stripped
            or "follow me on x" in stripped.lower()
        ):
            end = i
            break

    return start, end


def _parse_projection_row(line: str) -> TSIProjection | None:
    """Parse a single projection data row."""
    stripped = line.strip()
    if not re.match(r"\d+/\d+", stripped):
        return None

    # Try tab-separated first, then 2+ spaces
    parts = stripped.split("\t")
    if len(parts) < 5:
        parts = re.split(r"\s{2,}", stripped)
    if len(parts) < 5:
        return None

    try:
        return TSIProjection(
            date=parts[0].strip(),
            team_left=parts[1].strip(),
            team_right=parts[2].strip(),
            tsi_spread=float(parts[3].strip()),
            tsi_total=float(parts[4].strip()),
        )
    except (ValueError, IndexError):
        return None


def _parse_bet_line(line: str) -> TSIBet | None:
    """Parse a single bet line."""
    stripped = line.strip()
    if not stripped:
        return None

    # Total bet with slash: "Michigan State / North Dakota State Over 143.5"
    m = re.match(r"^(.+?)\s*/\s*(.+?)\s+(Over|Under)\s+([\d.]+)$", stripped, re.IGNORECASE)
    if m:
        return TSIBet(
            teams=[m.group(1).strip(), m.group(2).strip()],
            market="total",
            side=m.group(3).lower(),
            line=float(m.group(4)),
        )

    # Total bet without slash: "Saint Mary's Texas A&M Over 147.5"
    m = re.match(r"^(.+?)\s+(Over|Under)\s+([\d.]+)$", stripped, re.IGNORECASE)
    if m:
        return TSIBet(
            teams=[m.group(1).strip()],
            market="total",
            side=m.group(2).lower(),
            line=float(m.group(3)),
        )

    # Spread bet: "Troy +13.5" or "Georgia -2"
    m = re.match(r"^(.+?)\s+([+-][\d.]+)$", stripped)
    if m:
        return TSIBet(
            teams=[m.group(1).strip()],
            market="spread",
            side=m.group(1).strip(),
            line=float(m.group(2)),
        )

    return None


def parse_tsi(raw_text: str) -> tuple[list[TSIProjection], list[TSIBet]]:
    """
    Parse TSI article text into projections and bets.

    Returns (projections, bets).
    """
    lines = raw_text.split("\n")

    # --- Projections ---
    start, end = _find_section_bounds(lines)
    projections = []
    if start != -1:
        for line in lines[start + 1 : end]:
            proj = _parse_projection_row(line)
            if proj:
                projections.append(proj)

    # --- Bets ---
    bets = []
    bets_start = -1
    for i in range(start if start != -1 else 0, end):
        if re.match(r"(?i)^\s*bets\s*:", lines[i]):
            bets_start = i + 1
            break

    if bets_start != -1:
        for line in lines[bets_start:end]:
            stripped = line.strip()
            if not stripped:
                continue
            # Stop at section boundaries
            if re.search(r"(?i)women.s\s+projections", stripped):
                break
            if "Follow me on X" in stripped:
                break
            bet = _parse_bet_line(stripped)
            if bet:
                bets.append(bet)

    return projections, bets


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m parsers.tsi_parser <raw_text_file>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        raw = f.read()

    projections, bets = parse_tsi(raw)

    print(f"\n{'='*60}")
    print(f"TSI Projections ({len(projections)} games)")
    print(f"{'='*60}")
    for p in projections:
        print(f"  {p.date}  {p.team_left:25s} vs {p.team_right:25s}  spread={p.tsi_spread:+.1f}  total={p.tsi_total:.1f}")

    print(f"\n{'='*60}")
    print(f"TSI Bets ({len(bets)} picks)")
    print(f"{'='*60}")
    for b in bets:
        teams_str = " / ".join(b.teams)
        print(f"  [{b.market:6s}] {teams_str:40s}  {b.side} {b.line:+.1f}")
