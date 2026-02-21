"""
Finds bets that appear in BOTH the VSiN splits alerts AND Circa splits alerts.
Matching is by team + bet type (spread or over/under), ignoring actual numbers.

Usage:
    python find_sharp_overlap.py <splits.txt> <circasplits.txt> [threshold]
"""

import sys
import re
from vsin_splits_parser import parse_splits, format_alerts


def make_key(alert):
    """
    Build a matching key from an alert: (game, bet_type).
    - Spread: key is (away, home, "spread", team_name)
    - Total:  key is (away, home, "over"/"under")
    """
    away = alert.away_team.lower()
    home = alert.home_team.lower()

    if alert.market == "Spread":
        team = re.sub(r"\s+[+-][\d.]+$", "", alert.side).strip().lower()
        return (away, home, "spread", team)
    else:
        direction = "over" if alert.side.lower().startswith("over") else "under"
        return (away, home, direction)


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python find_sharp_overlap.py "
            "<splits.txt> <circasplits.txt> [threshold]"
        )
        sys.exit(1)

    file_a = sys.argv[1]
    file_b = sys.argv[2]
    threshold = int(sys.argv[3]) if len(sys.argv) > 3 else 25

    with open(file_a, "r") as f:
        alerts_a = parse_splits(f.read(), threshold=threshold)
    with open(file_b, "r") as f:
        alerts_b = parse_splits(f.read(), threshold=threshold)

    keys_b = {make_key(a) for a in alerts_b}

    overlaps = [a for a in alerts_a if make_key(a) in keys_b]

    print(
        f"\n=== Overlapping Sharp Alerts: "
        f"{file_a} ∩ {file_b} (threshold >= {threshold}%) ===\n"
    )
    if overlaps:
        print(format_alerts(overlaps))
        print(f"\nOverlapping alerts: {len(overlaps)}")
    else:
        print("No overlapping alerts found.")


if __name__ == "__main__":
    main()
