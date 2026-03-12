"""
VSiN Betting Splits Parser
---------------------------
Parses raw text from VSiN's betting splits page and identifies spread/total lines
where the handle% exceeds the bet% by at least a given threshold (default 25%).

Usage:
    python vsin_parser.py <splits_file.txt> [threshold]
"""

from dataclasses import dataclass

from .vsin_classifiers import (
    clean_line, is_pct, parse_pct, is_number_line,
    is_team_name, is_date_header, is_column_header,
)

MAX_HANDLE_PCT = 95


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
            i += 1
            continue

        if is_team_name(line) and i + 1 < len(lines) and is_team_name(lines[i + 1]):
            away_team = line.strip()
            home_team = lines[i + 1].strip()

            data_start = i + 2
            data_vals = []
            j = data_start
            while j < len(lines) and len(data_vals) < 18:
                val = lines[j].strip()
                if is_date_header(val) or is_column_header(val):
                    break
                if is_team_name(val):
                    if j + 1 < len(lines) and is_team_name(lines[j + 1]):
                        break
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


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from parsers.vsin_formatter import format_alerts

    if len(sys.argv) < 2:
        print("Usage: python vsin_parser.py <splits_file.txt> [threshold]")
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
