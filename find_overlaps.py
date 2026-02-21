"""
Finds bets that appear in both the VSiN sharp money alerts AND have
the best market price on Bovada.

Usage:
    python find_overlaps.py <splits.txt> <spreadsplits.txt> <totalsmarket.txt> [threshold]
"""

import sys
import re
from vsin_splits_parser import parse_splits, format_alerts


def get_bovada_teams(filename):
    """
    Parse a Bovada market file and return two things:
      - bovada_teams: set of lowercased team names whose best line is on Bovada
      - market_type: "spread" or "total" (auto-detected from file contents)
      - direction_map: for totals files, maps lowercased team name -> "over"/"under"
    """
    with open(filename, "r") as f:
        lines = [line.rstrip() for line in f.readlines()]

    totals_re = re.compile(r"^([ou])(\d+[½]?)\s+([+-]\d+)$")
    spread_re = re.compile(r"^([+-]\d+[½]?)\s+([+-]\d+)$")
    record_re = re.compile(r"^\d+-\d+$")

    team_entries = []
    for i in range(len(lines) - 4):
        name = lines[i].strip()
        record = lines[i + 1].strip()
        dash = lines[i + 2].strip()
        line_val = lines[i + 3].strip()
        book_line = lines[i + 4].strip()

        if not (name and record_re.match(record) and dash == "-"):
            continue

        tm = totals_re.match(line_val)
        sm = spread_re.match(line_val)

        if tm:
            direction = "over" if tm.group(1) == "o" else "under"
            market = "total"
        elif sm:
            direction = None
            market = "spread"
        else:
            continue

        team_entries.append({
            "name": name,
            "market": market,
            "direction": direction,
            "book": book_line,
        })

    bovada_spread_teams = set()
    bovada_total_dir = {}

    for idx in range(0, len(team_entries) - 1, 2):
        for entry in (team_entries[idx], team_entries[idx + 1]):
            if entry["book"] != "Bovada":
                continue
            key = entry["name"].lower()
            if entry["market"] == "spread":
                bovada_spread_teams.add(key)
            else:
                bovada_total_dir[key] = entry["direction"]

    return bovada_spread_teams, bovada_total_dir


def main():
    if len(sys.argv) < 4:
        print(
            "Usage: python find_overlaps.py "
            "<splits.txt> <spreadsplits.txt> <totalsmarket.txt> [threshold]"
        )
        sys.exit(1)

    splits_file = sys.argv[1]
    spread_file = sys.argv[2]
    totals_file = sys.argv[3]
    threshold = int(sys.argv[4]) if len(sys.argv) > 4 else 25

    with open(splits_file, "r") as f:
        raw_text = f.read()
    alerts = parse_splits(raw_text, threshold=threshold)

    bovada_spread_teams, bovada_total_dir = get_bovada_teams(spread_file)
    ts2, bovada_total_dir2 = get_bovada_teams(totals_file)
    bovada_total_dir.update(bovada_total_dir2)

    overlaps = []
    for alert in alerts:
        if alert.market == "Spread":
            team = re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip().lower()
            if team in bovada_spread_teams:
                overlaps.append(alert)

        elif alert.market == "Total":
            direction = "over" if alert.side.lower().startswith("over") else "under"
            away_low = alert.away_team.lower()
            home_low = alert.home_team.lower()
            if any(
                bovada_total_dir.get(t) == direction
                for t in (away_low, home_low)
            ):
                overlaps.append(alert)

    print(
        f"\n=== Sharp + Bovada Best Price Overlaps "
        f"(Handle% - Bets% >= {threshold}%) ===\n"
    )
    if overlaps:
        print(format_alerts(overlaps))
        print(f"\nOverlapping alerts: {len(overlaps)}")
    else:
        print("No overlapping alerts found.")


if __name__ == "__main__":
    main()
