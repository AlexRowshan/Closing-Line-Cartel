"""
VSiN Betting Splits Parser
---------------------------
Parses raw text from VSiN's betting splits page and identifies spread/total lines
where the handle% exceeds the bet% by at least a given threshold (default 25%).

The raw copy-paste from VSiN produces a format where each value is on its own line:
    Team1
    Team2
    spread1, spread2
    spreadHandle1%, spreadHandle2%
    spreadBets1%, spreadBets2%
    total1, total2
    totalHandle1%, totalHandle2%
    totalBets1%, totalBets2%
    ml1, ml2
    mlHandle1%, mlHandle2%
    mlBets1%, mlBets2%

Moneyline data is completely ignored.

Usage:
    python vsin_splits_parser.py <splits_file.txt> [threshold]
"""

import re
import sys
from dataclasses import dataclass
from collections import defaultdict


MAX_HANDLE_PCT = 95
WEEKDAY_ORDER = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


@dataclass
class SplitAlert:
    date: str
    away_team: str
    home_team: str
    market: str        # "Spread" or "Total"
    side: str          # e.g. "Oklahoma ST -1.5" or "Under 151.5"
    handle_pct: int
    bets_pct: int
    diff: int


def clean_line(s: str) -> str:
    return s.strip().rstrip("\t")


def is_pct(s: str) -> bool:
    return bool(re.match(r"^\d+%\s*$", s.strip()))


def parse_pct(s: str) -> int:
    return int(re.search(r"(\d+)", s).group(1))


def is_number_line(s: str) -> bool:
    """Check if a line is a numeric value (spread, total, or ML)."""
    s = s.strip()
    return bool(re.match(r"^[+-]?\d+\.?\d*$", s))


def is_team_name(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if is_pct(s) or is_number_line(s):
        return False
    if s == "-":
        return False
    # Reject known non-team header/title lines
    lower = s.lower()
    skip_phrases = [
        "betting splits", "betting picks", "vsin", "subscribe",
        "about the", "college basketball", "nba ", "nfl ", "mlb ",
        "nhl ", "pro tools", "article calendar", "parlay calculator",
    ]
    for phrase in skip_phrases:
        if phrase in lower:
            return False
    return bool(re.match(r"^[A-Za-z]", s))


def is_date_header(s: str) -> bool:
    return bool(re.match(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*\w+\s+\d+",
        s.strip(), re.IGNORECASE
    ))


def is_column_header(s: str) -> bool:
    return "Spread" in s and "Handle" in s and "Bets" in s


def parse_splits(text: str, threshold: int = 25) -> list[SplitAlert]:
    raw_lines = text.splitlines()
    lines = [clean_line(l) for l in raw_lines if clean_line(l)]

    alerts: list[SplitAlert] = []
    current_date = ""
    i = 0

    while i < len(lines):
        line = lines[i]

        if is_date_header(line):
            current_date = line.split("\t")[0].strip()
            i += 1
            continue

        if is_column_header(line):
            # Sometimes the date header is on the same line as column headers
            # e.g. "Friday,Feb 13\tSpread\tHandle\tBets..."
            # The date would have been captured above already
            i += 1
            continue

        # Detect game: two consecutive team names
        if is_team_name(line) and i + 1 < len(lines) and is_team_name(lines[i + 1]):
            away_team = line.strip()
            home_team = lines[i + 1].strip()

            # Collect the next data values (numbers and percentages)
            data_start = i + 2
            data_vals = []
            j = data_start
            while j < len(lines) and len(data_vals) < 18:
                val = lines[j].strip()
                # Stop if we hit another team pair or date
                if is_date_header(val) or is_column_header(val):
                    break
                # Check if this is a team name AND the next line is also a team name
                # (indicates start of next game)
                if is_team_name(val):
                    if j + 1 < len(lines) and is_team_name(lines[j + 1]):
                        break
                # Accept numbers, percentages, and "-" (missing ML)
                if is_number_line(val) or is_pct(val) or val == "-":
                    data_vals.append(val)
                j += 1

            if len(data_vals) >= 12:
                game_alerts = _process_game(
                    away_team, home_team, data_vals, current_date, threshold
                )
                alerts.extend(game_alerts)

            i = j
            continue

        i += 1

    return alerts


def _process_game(
    away: str, home: str, vals: list[str], date: str, threshold: int
) -> list[SplitAlert]:
    """
    Expected vals layout (18 values):
    [0]  spread_away      e.g. "-2.5"
    [1]  spread_home       e.g. "+2.5"
    [2]  spread_handle_away%   e.g. "65%"
    [3]  spread_handle_home%   e.g. "35%"
    [4]  spread_bets_away%
    [5]  spread_bets_home%
    [6]  total_line        e.g. "136.5"
    [7]  total_line_dup    e.g. "136.5"
    [8]  total_handle_over%
    [9]  total_handle_under%
    [10] total_bets_over%
    [11] total_bets_under%
    [12-17] moneyline (ignored)
    """
    alerts = []

    try:
        spread_away = vals[0]
        spread_home = vals[1]
        sh_away = parse_pct(vals[2])
        sh_home = parse_pct(vals[3])
        sb_away = parse_pct(vals[4])
        sb_home = parse_pct(vals[5])

        total_val = vals[6]
        th_over = parse_pct(vals[8])
        th_under = parse_pct(vals[9])
        tb_over = parse_pct(vals[10])
        tb_under = parse_pct(vals[11])
    except (IndexError, AttributeError):
        return alerts

    # Spread checks
    diff_away = sh_away - sb_away
    if diff_away >= threshold and sh_away <= MAX_HANDLE_PCT:
        alerts.append(SplitAlert(
            date=date, away_team=away, home_team=home,
            market="Spread",
            side=f"{away} {spread_away}",
            handle_pct=sh_away, bets_pct=sb_away, diff=diff_away,
        ))

    diff_home = sh_home - sb_home
    if diff_home >= threshold and sh_home <= MAX_HANDLE_PCT:
        alerts.append(SplitAlert(
            date=date, away_team=away, home_team=home,
            market="Spread",
            side=f"{home} {spread_home}",
            handle_pct=sh_home, bets_pct=sb_home, diff=diff_home,
        ))

    # Total checks
    diff_over = th_over - tb_over
    if diff_over >= threshold and th_over <= MAX_HANDLE_PCT:
        alerts.append(SplitAlert(
            date=date, away_team=away, home_team=home,
            market="Total",
            side=f"Over {total_val}",
            handle_pct=th_over, bets_pct=tb_over, diff=diff_over,
        ))

    diff_under = th_under - tb_under
    if diff_under >= threshold and th_under <= MAX_HANDLE_PCT:
        alerts.append(SplitAlert(
            date=date, away_team=away, home_team=home,
            market="Total",
            side=f"Under {total_val}",
            handle_pct=th_under, bets_pct=tb_under, diff=diff_under,
        ))

    return alerts


def format_alerts(alerts: list[SplitAlert]) -> str:
    if not alerts:
        return "No discrepancies found at the given threshold."

    header = (
        f"{'Date':<18} {'Matchup':<45} {'Market':<8} "
        f"{'Side':<35} {'Handle%':>8} {'Bets%':>6} {'Diff':>6}"
    )
    sep = "-" * len(header)
    grouped_alerts: dict[str, list[SplitAlert]] = defaultdict(list)

    for a in alerts:
        weekday = a.date.split(",", 1)[0].strip() if "," in a.date else a.date.strip()
        grouped_alerts[weekday].append(a)

    sorted_weekdays = sorted(
        grouped_alerts.keys(),
        key=lambda day: (WEEKDAY_ORDER.get(day, 99), day),
    )

    rows: list[str] = []
    for idx, weekday in enumerate(sorted_weekdays):
        if idx > 0:
            rows.append("")
        rows.append(f"=== {weekday} ===")
        rows.append(header)
        rows.append(sep)

        day_alerts = sorted(grouped_alerts[weekday], key=lambda a: a.diff, reverse=True)
        for a in day_alerts:
            matchup = f"{a.away_team} @ {a.home_team}"
            if len(matchup) > 43:
                matchup = matchup[:43]
            rows.append(
                f"{a.date:<18} {matchup:<45} {a.market:<8} "
                f"{a.side:<35} {a.handle_pct:>7}% {a.bets_pct:>5}% {a.diff:>5}%"
            )

    return "\n".join(rows)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python vsin_splits_parser.py <splits_file.txt> [threshold]")
        print("  threshold: minimum handle% - bets% difference (default: 25)")
        sys.exit(1)

    filepath = sys.argv[1]
    thresh = int(sys.argv[2]) if len(sys.argv) > 2 else 25

    with open(filepath, "r") as f:
        raw_text = f.read()

    results = parse_splits(raw_text, threshold=thresh)
    print(f"\n=== VSiN Sharp Money Alerts (Handle% - Bets% >= {thresh}%) ===\n")
    print(format_alerts(results))
    print(f"\nTotal alerts: {len(results)}")
