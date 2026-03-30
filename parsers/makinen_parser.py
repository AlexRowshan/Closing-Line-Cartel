"""
Parser for Steve Makinen's NBA Strength Ratings from VSIN.

Extracts projected edges from the "Today's NBA Strength Ratings" section
and maps them into TSIProjection / TSIBet objects for pipeline compatibility.

The article contains multiple rating systems (Power Ratings, Effective
Strength Ratings, Bettors Ratings), each listing top-3 underpriced
underdogs/favorites and over/under totals.  We average the edges across
all systems per team/game to get a single composite projection.
"""

import re
import sys
from collections import defaultdict
from datetime import date

from .tsi_parser import TSIProjection, TSIBet


# ---------------------------------------------------------------------------
# Team name normalization (Makinen ALL-CAPS → pipeline-compatible names)
# ---------------------------------------------------------------------------

# Maps Makinen's ALL-CAPS city names to the pipeline's expected format.
# The pipeline's _normalize_team() + _teams_match() handle the rest
# (prefix matching, abbreviation expansion, etc.)
_MAKINEN_TO_PIPELINE = {
    "CHICAGO": "Chicago Bulls",
    "PHILADELPHIA": "Philadelphia 76ers",
    "ATLANTA": "Atlanta Hawks",
    "DETROIT": "Detroit Pistons",
    "LA LAKERS": "Los Angeles Lakers",
    "INDIANA": "Indiana Pacers",
    "OKLAHOMA CITY": "Oklahoma City Thunder",
    "BOSTON": "Boston Celtics",
    "MIAMI": "Miami Heat",
    "CLEVELAND": "Cleveland Cavaliers",
    "SAN ANTONIO": "San Antonio Spurs",
    "MEMPHIS": "Memphis Grizzlies",
    "WASHINGTON": "Washington Wizards",
    "UTAH": "Utah Jazz",
    "HOUSTON": "Houston Rockets",
    "MINNESOTA": "Minnesota Timberwolves",
    "MILWAUKEE": "Milwaukee Bucks",
    "PORTLAND": "Portland Trail Blazers",
    "DALLAS": "Dallas Mavericks",
    "DENVER": "Denver Nuggets",
    "BROOKLYN": "Brooklyn Nets",
    "GOLDEN STATE": "Golden State Warriors",
    "TORONTO": "Toronto Raptors",
    "LA CLIPPERS": "Los Angeles Clippers",
    "SACRAMENTO": "Sacramento Kings",
    "ORLANDO": "Orlando Magic",
    "NEW YORK": "New York Knicks",
    "NEW ORLEANS": "New Orleans Pelicans",
    "PHOENIX": "Phoenix Suns",
    "CHARLOTTE": "Charlotte Hornets",
}


def _to_pipeline_name(makinen_name: str) -> str:
    """Convert Makinen ALL-CAPS team name to pipeline-compatible name."""
    upper = makinen_name.strip().upper()
    return _MAKINEN_TO_PIPELINE.get(upper, makinen_name.strip().title())


# ---------------------------------------------------------------------------
# Section isolation
# ---------------------------------------------------------------------------

def _normalize_apostrophes(text: str) -> str:
    """Replace curly/smart apostrophes with straight ones."""
    return text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')


def _extract_ratings_section(raw_text: str) -> str:
    """
    Strictly slice text below 'Today's NBA Strength Ratings' header.

    Everything above the header is discarded — AJ's Angles, DK Splits,
    trend matches, etc. are all noise for this parser.
    """
    raw_text = _normalize_apostrophes(raw_text)
    lines = raw_text.split("\n")
    start = -1
    for i, line in enumerate(lines):
        if re.search(r"(?i)today.s\s+nba\s+strength\s+ratings", line):
            start = i + 1
            break
    if start == -1:
        return ""

    end = len(lines)
    for i in range(start, len(lines)):
        stripped = lines[i].strip().lower()
        if any(marker in stripped for marker in (
            "tags", "about the author", "related articles",
            "share this", "subscribe",
        )):
            end = i
            break
    return "\n".join(lines[start:end])


def _extract_game_matchups(raw_text: str) -> dict[str, tuple[str, str]]:
    """
    Parse game matchups from the head-to-head section.

    Pattern: '(559) CHICAGO at (560) PHILADELPHIA'
    Returns dict mapping normalized team name → (pipeline_away, pipeline_home).
    Both teams are keys pointing to the same tuple.
    """
    matchups: dict[str, tuple[str, str]] = {}
    pattern = re.compile(
        r"\(\d+\)\s+(.+?)\s+at\s+\(\d+\)\s+(.+?)$", re.MULTILINE
    )
    for m in pattern.finditer(raw_text):
        away_raw = m.group(1).strip()
        home_raw = m.group(2).strip()
        away = _to_pipeline_name(away_raw)
        home = _to_pipeline_name(home_raw)
        matchups[away_raw.upper()] = (away, home)
        matchups[home_raw.upper()] = (away, home)
    return matchups


# ---------------------------------------------------------------------------
# Rating entry parsing
# ---------------------------------------------------------------------------

# Spread: "1. CHICAGO +6.5 (+3.7)" or "Ratings Matches: 1. CHICAGO +6.5 (+3.7)"
# Also handles "1(tie)." numbering and missing closing paren: "(+3.7"
_SPREAD_ENTRY_RE = re.compile(
    r"(?:Ratings\s+Matches?:\s*)?"
    r"\d+(?:\s*\(tie\))?\s*\.?\s+"
    r"([A-Z][A-Z\s]+?)\s+"          # team name (uppercase words)
    r"([+-]\d+\.?\d*)\s+"           # market line
    r"\(([+-]\d+\.?\d*)\)?"         # edge in parens — MUST have +/- sign
)

# Total: "1. OKC-BOS OVER 218.5 (+2.3)" — closing paren optional
_TOTAL_ENTRY_RE = re.compile(
    r"(?:Ratings\s+Matches?:\s*)?"
    r"\d+(?:\s*\(tie\))?\s*\.?\s+"
    r"([A-Z][\w]*-[A-Z][\w]*)\s+"  # team abbrevs with dash
    r"(OVER|UNDER)\s+"
    r"(\d+\.?\d*)\s+"              # total line
    r"\(([+-]\d+\.?\d*)\)?"        # edge in parens — MUST have +/- sign
    ,
    re.IGNORECASE,
)


def _parse_rating_entries(section: str) -> tuple[list[dict], list[dict]]:
    """
    Parse all numbered rating entries from the strength ratings section.

    Returns (spread_entries, total_entries) where each entry is a dict with
    keys: team, line, edge (and direction for totals).
    """
    spreads = []
    totals = []

    for line in section.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Try totals first (more specific pattern)
        total_matched = False
        for m in _TOTAL_ENTRY_RE.finditer(stripped):
            edge_val = float(m.group(4))
            # Sanity: edge should be small (< 20). If not, skip — likely a misparsed line number.
            if abs(edge_val) > 20:
                continue
            totals.append({
                "teams_abbrev": m.group(1).strip().upper(),
                "direction": m.group(2).lower(),
                "line": float(m.group(3)),
                "edge": edge_val,
            })
            total_matched = True

        # Try spreads — but skip lines that already matched as totals
        if not total_matched:
            for m in _SPREAD_ENTRY_RE.finditer(stripped):
                edge_val = float(m.group(3))
                # Sanity: edge should be small (< 20). Skip absurd values.
                if abs(edge_val) > 20:
                    continue
                spreads.append({
                    "team": m.group(1).strip(),
                    "line": float(m.group(2)),
                    "edge": edge_val,
                })

    return spreads, totals


# ---------------------------------------------------------------------------
# Aggregation & projection building
# ---------------------------------------------------------------------------

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# Abbreviation → Makinen full city name (for resolving total entries like "OKC-BOS")
_ABBREV_TO_FULL = {
    "CHI": "CHICAGO", "PHI": "PHILADELPHIA", "ATL": "ATLANTA",
    "DET": "DETROIT", "LAL": "LA LAKERS", "IND": "INDIANA",
    "OKC": "OKLAHOMA CITY", "BOS": "BOSTON", "MIA": "MIAMI",
    "CLE": "CLEVELAND", "SAS": "SAN ANTONIO", "SA": "SAN ANTONIO",
    "MEM": "MEMPHIS", "WSH": "WASHINGTON", "WAS": "WASHINGTON",
    "UTA": "UTAH", "HOU": "HOUSTON", "MIN": "MINNESOTA",
    "MIL": "MILWAUKEE", "POR": "PORTLAND", "DAL": "DALLAS",
    "DEN": "DENVER", "BKN": "BROOKLYN", "BK": "BROOKLYN",
    "GSW": "GOLDEN STATE", "GS": "GOLDEN STATE",
    "TOR": "TORONTO", "LAC": "LA CLIPPERS",
    "SAC": "SACRAMENTO", "ORL": "ORLANDO", "NYK": "NEW YORK",
    "NY": "NEW YORK", "NOP": "NEW ORLEANS", "NO": "NEW ORLEANS",
    "PHX": "PHOENIX", "CHA": "CHARLOTTE",
}


def _resolve_team_name(
    abbrev: str, matchups: dict[str, tuple[str, str]]
) -> str | None:
    """Try to resolve a short abbreviation to a full team name via matchups."""
    abbrev_upper = abbrev.upper().strip()
    # Direct match
    if abbrev_upper in matchups:
        return abbrev_upper
    full = _ABBREV_TO_FULL.get(abbrev_upper)
    if full and full in matchups:
        return full
    return None


def _build_projections(
    spread_entries: list[dict],
    total_entries: list[dict],
    matchups: dict[str, tuple[str, str]],
    today: date,
) -> tuple[list[TSIProjection], list[TSIBet]]:
    """
    Aggregate edges across all rating systems and build TSIProjection objects.

    For spreads: averages multiple edge readings per team, then computes
    tsi_spread = market_line - avg_edge (the Makinen-projected line).

    For totals: averages edges per game/direction, then computes
    tsi_total = market_total +/- avg_edge.
    """
    date_str = f"{today.month}/{today.day}/{today.year}"

    # --- Aggregate spread edges per team ---
    # team_upper → {line: float, edges: [float]}
    spread_agg: dict[str, dict] = defaultdict(lambda: {"line": 0.0, "edges": []})
    for entry in spread_entries:
        key = entry["team"].upper()
        spread_agg[key]["line"] = entry["line"]  # last seen market line
        spread_agg[key]["edges"].append(entry["edge"])

    # --- Aggregate total edges per game ---
    # teams_abbrev → {line: float, direction: str, edges: [float]}
    total_agg: dict[str, dict] = defaultdict(lambda: {"line": 0.0, "direction": "", "edges": []})
    for entry in total_entries:
        key = entry["teams_abbrev"]
        total_agg[key]["line"] = entry["line"]
        total_agg[key]["direction"] = entry["direction"]
        total_agg[key]["edges"].append(entry["edge"])

    # --- Build one TSIProjection per game ---
    game_projections: dict[tuple[str, str], TSIProjection] = {}
    game_spread_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    bets: list[TSIBet] = []

    # Process spread entries: find opponent via matchups, compute tsi_spread
    for team_upper, agg in spread_agg.items():
        avg_edge = _avg(agg["edges"])
        market_line = agg["line"]

        projected_line = market_line - avg_edge

        # Find opponent
        if team_upper not in matchups:
            continue
        away, home = matchups[team_upper]
        game_key = (_normalize_key(away), _normalize_key(home))

        if game_key not in game_projections:
            game_projections[game_key] = TSIProjection(
                date=date_str,
                team_left=away,
                team_right=home,
                tsi_spread=0.0,
                tsi_total=0.0,
            )

        if team_upper == _normalize_key(away).upper() or _to_pipeline_name(team_upper) == away:
            game_spread_values[game_key].append(-projected_line)
        else:
            game_spread_values[game_key].append(projected_line)

        # Create bet for strong edges
        if avg_edge >= 2.0:
            pipeline_name = _to_pipeline_name(team_upper)
            bets.append(TSIBet(
                teams=[pipeline_name],
                market="spread",
                side=pipeline_name,
                line=market_line,
            ))

    # Process total entries: resolve team abbrevs, compute tsi_total
    for teams_abbrev, agg in total_agg.items():
        avg_edge = _avg(agg["edges"])
        market_total = agg["line"]
        direction = agg["direction"]

        tsi_total = market_total + avg_edge

        # Resolve abbreviations to full names
        parts = teams_abbrev.split("-")
        if len(parts) != 2:
            continue

        away_name = _resolve_team_name(parts[0], matchups)
        home_name = _resolve_team_name(parts[1], matchups)
        if not away_name or not home_name:
            continue

        away_full = matchups[away_name][0]
        home_full = matchups[away_name][1]
        game_key = (_normalize_key(away_full), _normalize_key(home_full))

        if game_key in game_projections:
            proj = game_projections[game_key]
            # Average if we already have a total from a different rating system
            if proj.tsi_total != 0.0:
                proj.tsi_total = (proj.tsi_total + tsi_total) / 2
            else:
                proj.tsi_total = tsi_total
        else:
            proj = TSIProjection(
                date=date_str,
                team_left=away_full,
                team_right=home_full,
                tsi_spread=0.0,
                tsi_total=tsi_total,
            )
            game_projections[game_key] = proj

        # Create bet for strong total edges
        if abs(avg_edge) >= 2.0:
            bets.append(TSIBet(
                teams=[away_full, home_full],
                market="total",
                side=direction,
                line=market_total,
            ))

    # Average tsi_spread values when multiple teams in the same game have entries
    for game_key, spread_vals in game_spread_values.items():
        if game_key in game_projections and spread_vals:
            game_projections[game_key].tsi_spread = _avg(spread_vals)

    return list(game_projections.values()), bets


def _normalize_key(name: str) -> str:
    return name.strip().upper()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_makinen(raw_text: str) -> tuple[list[TSIProjection], list[TSIBet]]:
    """
    Parse Makinen's NBA Strength Ratings into TSIProjection and TSIBet objects.

    Returns (projections, bets) — same types as parse_tsi() for pipeline
    compatibility.
    """
    # Normalize curly apostrophes so header matching works on live site text
    raw_text = _normalize_apostrophes(raw_text)

    # Step 1: Extract game matchups from head-to-head section
    matchups = _extract_game_matchups(raw_text)

    # Step 2: Extract and parse the strength ratings section ONLY
    section = _extract_ratings_section(raw_text)
    if not section:
        return [], []

    spread_entries, total_entries = _parse_rating_entries(section)
    if not spread_entries and not total_entries:
        return [], []

    # Step 3: Build projections
    return _build_projections(spread_entries, total_entries, matchups, date.today())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m parsers.makinen_parser <raw_text_file>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        raw = f.read()

    projections, bets = parse_makinen(raw)

    print(f"\n{'='*60}")
    print(f"Makinen Projections ({len(projections)} games)")
    print(f"{'='*60}")
    for p in projections:
        r = p.team_right or "(unknown)"
        print(
            f"  {p.date}  {p.team_left:25s} vs {r:25s}  "
            f"spread={p.tsi_spread:+.1f}  total={p.tsi_total:.1f}"
        )

    print(f"\n{'='*60}")
    print(f"Makinen Bets ({len(bets)} picks)")
    print(f"{'='*60}")
    for b in bets:
        teams_str = " / ".join(b.teams)
        print(f"  [{b.market:6s}] {teams_str:40s}  {b.side} {b.line:+.1f}")
