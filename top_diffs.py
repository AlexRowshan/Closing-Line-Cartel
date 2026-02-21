"""
Top 5 Biggest Diffs Extractor
-----------------------------
Calls vsin_splits_parser.py and extracts the top 5 biggest handle% - bets% differences.
"""

import subprocess
import re
import sys
from pathlib import Path


def parse_parser_output(output_text: str) -> list[dict]:
    """
    Parse the formatted output from vsin_splits_parser.py and extract alert data.
    Returns a list of dictionaries with alert information.
    """
    lines = output_text.splitlines()
    alerts = []
    
    # Skip header lines until we find the separator line
    start_parsing = False
    for line in lines:
        # Skip until we see the separator line (dashes)
        if not start_parsing:
            if line.strip().startswith("---"):
                start_parsing = True
            continue
        
        # Stop at footer line
        if line.strip().startswith("Total alerts:"):
            break
        
        # Skip empty lines
        if not line.strip():
            continue
        
        # Parse the formatted row
        # Format: Date               Matchup                                       Market   Side                                 Handle%  Bets%   Diff
        # Example: Saturday,Feb 14    California Baptist @ Utah Tech                Total    Under 142.5                              94%    21%    73%
        
        # Use regex to extract the parts
        # The date is at the start, then matchup (up to 45 chars), market (8 chars), side (35 chars), then percentages
        match = re.match(
            r"^(.{18})\s+(.{45})\s+(.{8})\s+(.{35})\s+(\d+)%\s+(\d+)%\s+(\d+)%",
            line
        )
        
        if match:
            date = match.group(1).strip()
            matchup = match.group(2).strip()
            market = match.group(3).strip()
            side = match.group(4).strip()
            handle_pct = int(match.group(5))
            bets_pct = int(match.group(6))
            diff = int(match.group(7))
            
            alerts.append({
                'date': date,
                'matchup': matchup,
                'market': market,
                'side': side,
                'handle_pct': handle_pct,
                'bets_pct': bets_pct,
                'diff': diff
            })
    
    return alerts


def get_top_diffs(splits_file: str = "splits.txt", threshold: int = 25, top_n: int = 5):
    """
    Call vsin_splits_parser.py and return the top N biggest diffs.
    
    Args:
        splits_file: Path to the splits.txt file
        threshold: Minimum diff threshold to use (default: 25)
        top_n: Number of top results to return (default: 5)
    
    Returns:
        List of top N alerts sorted by diff (descending)
    """
    # Call the parser script
    script_path = Path(__file__).parent / "vsin_splits_parser.py"
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path), splits_file, str(threshold)],
            capture_output=True,
            text=True,
            check=True
        )
        
        output = result.stdout
        alerts = parse_parser_output(output)
        
        # Sort by diff descending and return top N
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
    # Default values
    splits_file = "splits.txt"
    threshold = 25
    top_n = 5
    
    # Allow command line arguments
    if len(sys.argv) > 1:
        splits_file = sys.argv[1]
    if len(sys.argv) > 2:
        threshold = int(sys.argv[2])
    if len(sys.argv) > 3:
        top_n = int(sys.argv[3])
    
    top_alerts = get_top_diffs(splits_file, threshold, top_n)
    print(format_top_diffs(top_alerts))
