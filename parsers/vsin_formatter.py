"""
Display formatting for VSiN SplitAlert objects.
"""

from collections import defaultdict

WEEKDAY_ORDER = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def format_alerts(alerts) -> str:
    if not alerts:
        return "No discrepancies found at the given threshold."

    header = (
        f"{'Date':<18} {'Matchup':<45} {'Market':<8} "
        f"{'Side':<35} {'Handle%':>8} {'Bets%':>6} {'Diff':>6}"
    )
    sep = "-" * len(header)
    grouped_alerts: dict[str, list] = defaultdict(list)

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
