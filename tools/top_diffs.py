"""
Top 5 Biggest Diffs Extractor
-----------------------------
Calls parsers/vsin_parser.py and extracts the top 5 biggest handle% - bets% differences.

Usage:
    python tools/top_diffs.py [splits.txt] [threshold] [top_n]
"""

import subprocess
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_parser_output(output_text: str) -> list[dict]:
    """
    Parse the formatted output from vsin_parser.py and extract alert data.
    Returns a list of dictionaries with alert information.
    """
    lines = output_text.splitlines()
    alerts = []

    start_parsing = False
    for line in lines:
        if not start_parsing:
            if line.strip().startswith("---"):
                start_parsing = True
            continue

        if line.strip().startswith("Total alerts:"):
            break

        if not line.strip():
            continue

        match = re.match(
            r"^(.{18})\s+(.{45})\s+(.{8})\s+(.{35})\s+(\d+)%\s+(\d+)%\s+(\d+)%",
            line
        )

        if match:
            alerts.append({
                'date': match.group(1).strip(),
                'matchup': match.group(2).strip(),
                'market': match.group(3).strip(),
                'side': match.group(4).strip(),
                'handle_pct': int(match.group(5)),
                'bets_pct': int(match.group(6)),
                'diff': int(match.group(7)),
            })

    return alerts


def get_top_diffs(splits_file: str = "splits.txt", threshold: int = 25, top_n: int = 5):
    """
    Call parsers/vsin_parser.py and return the top N biggest diffs.
    """
    script_path = Path(__file__).parent.parent / "parsers" / "vsin_parser.py"

    try:
        result = subprocess.run(
            [sys.executable, str(script_path), splits_file, str(threshold)],
            capture_output=True,
            text=True,
            check=True
        )
        alerts = parse_parser_output(result.stdout)
        alerts.sort(key=lambda x: x['diff'], reverse=True)
        return alerts[:top_n]

    except subprocess.CalledProcessError as e:
        print(f"Error running parser: {e}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: Could not find {script_path}", file=sys.stderr)
        sys.exit(1)


def format_top_diffs(alerts: list[dict]) -> str:
    """Format the top diffs for display."""
    if not alerts:
        return "No alerts found."

    lines = ["\n=== TOP 5 BIGGEST DIFFS ===\n"]

    for i, alert in enumerate(alerts, 1):
        lines.append(f"{i}. {alert['matchup']}")
        lines.append(f"   Date: {alert['date']}")
        lines.append(f"   Market: {alert['market']} - {alert['side']}")
        lines.append(f"   Handle%: {alert['handle_pct']}% | Bets%: {alert['bets_pct']}% | Diff: {alert['diff']}%")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    splits_file = "splits.txt"
    threshold = 25
    top_n = 5

    if len(sys.argv) > 1:
        splits_file = sys.argv[1]
    if len(sys.argv) > 2:
        threshold = int(sys.argv[2])
    if len(sys.argv) > 3:
        top_n = int(sys.argv[3])

    top_alerts = get_top_diffs(splits_file, threshold, top_n)
    print(format_top_diffs(top_alerts))
