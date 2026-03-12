"""
Given any OddsTrader market file (spreads or totals), prints team pairs
where the best-priced book is Bovada.

Usage:
    python tools/bovada_best.py <file.txt>
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/bovada_best.py <file.txt>")
        sys.exit(1)

    filename = sys.argv[1]
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
            number = tm.group(2).replace("½", ".5")
            odds = tm.group(3)
            label = f"{direction} {number} ({odds})"
        elif sm:
            spread = sm.group(1).replace("½", ".5")
            odds = sm.group(2)
            label = f"{spread} ({odds})"
        else:
            continue

        team_entries.append(
            {"name": name, "label": label, "book": book_line}
        )

    bovada_lines = []
    for idx in range(0, len(team_entries) - 1, 2):
        team1 = team_entries[idx]
        team2 = team_entries[idx + 1]
        matchup = f"{team1['name']} vs {team2['name']}"

        if team1["book"] == "Bovada":
            bovada_lines.append(
                f"{matchup}: {team1['name']} {team1['label']} — best on Bovada"
            )
        if team2["book"] == "Bovada":
            bovada_lines.append(
                f"{matchup}: {team2['name']} {team2['label']} — best on Bovada"
            )

    if bovada_lines:
        print(f"Found {len(bovada_lines)} Bovada best-priced line(s):\n")
        for line in bovada_lines:
            print(line)
    else:
        print("No Bovada best-priced lines found.")


if __name__ == "__main__":
    main()
