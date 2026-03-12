"""
Date parsing and past-game filtering for VSIN alert objects.
"""

import re
from datetime import datetime, date

WEEKDAY_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_alert_date(date_str: str) -> date | None:
    """
    Parse dates like "Wednesday, Feb 18" or "Wednesday,Feb 18".
    Returns a date object or None if unparseable.
    """
    m = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d+)",
        date_str, re.IGNORECASE
    )
    if not m:
        return None
    month = WEEKDAY_MONTH_MAP.get(m.group(1).lower()[:3])
    if not month:
        return None
    day = int(m.group(2))
    year = datetime.now().year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _filter_future_games(alerts: list) -> list:
    """Keep only alerts for today or future dates."""
    today = date.today()
    result = []
    for alert in alerts:
        game_date = _parse_alert_date(alert.date)
        if game_date is None or game_date >= today:
            result.append(alert)
    return result
