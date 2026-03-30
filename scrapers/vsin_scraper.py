"""
HTTP-based scraper for VSIN betting splits (no Playwright needed).

DraftKings: fetches structured JSON from the public DK splits API.
Circa: fetches server-rendered HTML table from data.vsin.com.

Both sources are converted directly into SplitAlert objects.
"""

import re
import asyncio
from html.parser import HTMLParser

import aiohttp

from sport_config import get_config
from parsers.vsin_parser import SplitAlert

# ---------------------------------------------------------------------------
# DraftKings — public JSON API
# ---------------------------------------------------------------------------

DK_SPLITS_API = "https://gwa.us-east4.prod.dkapis.com/trending/v1/trending/bets/splits/"

# DK league IDs by sport
DK_LEAGUE_IDS = {
    "nba": "42648",
    "cbb": "92483",
}

MAX_HANDLE_PCT = 95


def _parse_pct(s: str | None) -> int:
    """'72%' → 72, None → 0"""
    if not s:
        return 0
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else 0


def _extract_spread_line(betslip: str) -> str:
    """'PHI 76ers -2.5' → '-2.5'"""
    m = re.search(r"([+-]?\d+\.?\d*)$", betslip.strip())
    return m.group(1) if m else ""


def _dk_event_to_alerts(event: dict, threshold: int) -> list[SplitAlert]:
    """Convert one DK API event into SplitAlert objects for qualifying sides."""
    alerts = []
    event_name = event.get("eventName", "")
    start_date = event.get("eventStartDate", "")

    # Parse "PHI 76ers @ MIA Heat" → away, home
    parts = event_name.split(" @ ")
    if len(parts) != 2:
        return alerts
    away_team = parts[0].strip()
    home_team = parts[1].strip()

    # Parse date for display: "2026-03-30T23:10:00Z" → "Monday, March 30"
    date_str = ""
    if start_date:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%A, %B %-d")
        except Exception:
            pass

    markets = {m.get("marketType", ""): m for m in event.get("markets", [])}

    # --- Spread ---
    spread_mkt = markets.get("Spread")
    if spread_mkt:
        outcomes = {}
        for out in spread_mkt.get("outcomes", []):
            outcomes[out.get("outcomeType", "")] = out

        away_out = outcomes.get("Away", {})
        home_out = outcomes.get("Home", {})

        away_handle = _parse_pct(away_out.get("handlePercent"))
        away_bets = _parse_pct(away_out.get("betPercent"))
        home_handle = _parse_pct(home_out.get("handlePercent"))
        home_bets = _parse_pct(home_out.get("betPercent"))

        away_betslip = away_out.get("betslipLine", "")
        home_betslip = home_out.get("betslipLine", "")

        away_spread = _extract_spread_line(away_betslip)
        home_spread = _extract_spread_line(home_betslip)

        diff_away = away_handle - away_bets
        if diff_away >= threshold and away_handle <= MAX_HANDLE_PCT:
            alerts.append(SplitAlert(
                date=date_str, away_team=away_team, home_team=home_team,
                market="Spread",
                side=f"{away_betslip}" if away_betslip else f"{away_team} {away_spread}",
                handle_pct=away_handle, bets_pct=away_bets, diff=diff_away,
            ))

        diff_home = home_handle - home_bets
        if diff_home >= threshold and home_handle <= MAX_HANDLE_PCT:
            alerts.append(SplitAlert(
                date=date_str, away_team=away_team, home_team=home_team,
                market="Spread",
                side=f"{home_betslip}" if home_betslip else f"{home_team} {home_spread}",
                handle_pct=home_handle, bets_pct=home_bets, diff=diff_home,
            ))

    # --- Total ---
    total_mkt = markets.get("Total")
    if total_mkt:
        outcomes = {}
        for out in total_mkt.get("outcomes", []):
            outcomes[out.get("outcomeType", "")] = out

        over_out = outcomes.get("Over", {})
        under_out = outcomes.get("Under", {})

        over_handle = _parse_pct(over_out.get("handlePercent"))
        over_bets = _parse_pct(over_out.get("betPercent"))
        under_handle = _parse_pct(under_out.get("handlePercent"))
        under_bets = _parse_pct(under_out.get("betPercent"))

        # Extract total value from betslipLine: "Over 243.5" → "243.5"
        over_betslip = over_out.get("betslipLine", "")
        total_val_match = re.search(r"([\d.]+)", over_betslip)
        total_val = total_val_match.group(1) if total_val_match else ""

        diff_over = over_handle - over_bets
        if diff_over >= threshold and over_handle <= MAX_HANDLE_PCT:
            alerts.append(SplitAlert(
                date=date_str, away_team=away_team, home_team=home_team,
                market="Total", side=f"Over {total_val}",
                handle_pct=over_handle, bets_pct=over_bets, diff=diff_over,
            ))

        diff_under = under_handle - under_bets
        if diff_under >= threshold and under_handle <= MAX_HANDLE_PCT:
            alerts.append(SplitAlert(
                date=date_str, away_team=away_team, home_team=home_team,
                market="Total", side=f"Under {total_val}",
                handle_pct=under_handle, bets_pct=under_bets, diff=diff_under,
            ))

    return alerts


async def _fetch_dk_splits(sport: str, threshold: int) -> list[SplitAlert]:
    """Fetch DK splits from the public API and return SplitAlert list."""
    league_id = DK_LEAGUE_IDS.get(sport)
    if not league_id:
        return []

    url = f"{DK_SPLITS_API}{league_id}?limit=1000"
    headers = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    alerts = []
    for event in data.get("events", []):
        alerts.extend(_dk_event_to_alerts(event, threshold))
    return alerts


# ---------------------------------------------------------------------------
# Circa — server-rendered HTML table from data.vsin.com
# ---------------------------------------------------------------------------

CIRCA_URLS = {
    "nba": "https://data.vsin.com/betting-splits/?source=CIRCA&sport=NBA",
    "cbb": "https://data.vsin.com/betting-splits/?source=CIRCA&sport=CBB",
}


class _TableParser(HTMLParser):
    """Extracts rows from the first <table> on the page."""

    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_cell = False
        self.rows: list[list[str]] = []
        self.current_row: list[str] = []
        self.current_cell: str = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.in_tr = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_tr:
            self.in_cell = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
        elif tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            self.current_row.append(self.current_cell.strip())

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


def _clean_pct(s: str) -> int:
    """'97%' or '86% ▲' → 97/86. Returns 0 on failure."""
    m = re.search(r"(\d+)%", s)
    return int(m.group(1)) if m else 0


def _circa_rows_to_alerts(rows: list[list[str]], threshold: int) -> list[SplitAlert]:
    """
    Parse Circa HTML table rows (paired: away then home per game) into SplitAlerts.

    Row layout (from HTML):
    [0] rank/icon, [1] team_name, [2] spread, [3] handle%, [4] bets%,
    [5] total, [6] total_handle%, [7] total_bets%,
    [8] moneyline, [9] ml_handle%, [10] ml_bets%

    First row is the header — skip it.
    """
    alerts = []

    # Extract date from header row if present
    date_str = ""
    start_idx = 0
    if rows and any("SpreadSPR" in c or "Spread" in c for c in rows[0]):
        # Header row: first cell often contains date like "NBA - Monday, Mar 30Mar 30"
        header = rows[0][0] if rows[0] else ""
        # Parse "NBA - Monday, Mar 30Mar 30" or "CBB - Saturday, Apr 4Apr 4"
        m = re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*(\w+)\s+(\d+)", header)
        if m:
            date_str = f"{m.group(1)}, {m.group(2)} {m.group(3)}"
        start_idx = 1

    # Process rows in pairs (away, home)
    i = start_idx
    while i + 1 < len(rows):
        away_row = rows[i]
        home_row = rows[i + 1]
        i += 2

        # Need at least 8 columns: rank, name, spread, handle, bets, total, t_handle, t_bets
        if len(away_row) < 8 or len(home_row) < 8:
            continue

        away_team = away_row[1].strip()
        home_team = home_row[1].strip()
        away_spread = away_row[2].strip()
        home_spread = home_row[2].strip()

        # Spread splits
        sh_away = _clean_pct(away_row[3])
        sb_away = _clean_pct(away_row[4])
        sh_home = _clean_pct(home_row[3])
        sb_home = _clean_pct(home_row[4])

        diff_away = sh_away - sb_away
        if diff_away >= threshold and sh_away <= MAX_HANDLE_PCT:
            alerts.append(SplitAlert(
                date=date_str, away_team=away_team, home_team=home_team,
                market="Spread", side=f"{away_team} {away_spread}",
                handle_pct=sh_away, bets_pct=sb_away, diff=diff_away,
            ))

        diff_home = sh_home - sb_home
        if diff_home >= threshold and sh_home <= MAX_HANDLE_PCT:
            alerts.append(SplitAlert(
                date=date_str, away_team=away_team, home_team=home_team,
                market="Spread", side=f"{home_team} {home_spread}",
                handle_pct=sh_home, bets_pct=sb_home, diff=diff_home,
            ))

        # Total splits
        total_val = away_row[5].strip()  # same for both rows
        th_over = _clean_pct(away_row[6])   # away row = over
        tb_over = _clean_pct(away_row[7])
        th_under = _clean_pct(home_row[6])  # home row = under
        tb_under = _clean_pct(home_row[7])

        diff_over = th_over - tb_over
        if diff_over >= threshold and th_over <= MAX_HANDLE_PCT:
            alerts.append(SplitAlert(
                date=date_str, away_team=away_team, home_team=home_team,
                market="Total", side=f"Over {total_val}",
                handle_pct=th_over, bets_pct=tb_over, diff=diff_over,
            ))

        diff_under = th_under - tb_under
        if diff_under >= threshold and th_under <= MAX_HANDLE_PCT:
            alerts.append(SplitAlert(
                date=date_str, away_team=away_team, home_team=home_team,
                market="Total", side=f"Under {total_val}",
                handle_pct=th_under, bets_pct=tb_under, diff=diff_under,
            ))

    return alerts


async def _fetch_circa_splits(sport: str, threshold: int) -> list[SplitAlert]:
    """Fetch Circa splits from the server-rendered HTML table."""
    url = CIRCA_URLS.get(sport)
    if not url:
        return []

    headers = {"User-Agent": "Mozilla/5.0"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            html = await resp.text(encoding="latin-1")

    parser = _TableParser()
    parser.feed(html)

    if not parser.rows:
        return []

    return _circa_rows_to_alerts(parser.rows, threshold)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def scrape_vsin(sport: str = "cbb") -> tuple[list[SplitAlert], list[SplitAlert]]:
    """
    Fetch DK and Circa splits concurrently via HTTP (no Playwright).

    Returns (dk_alerts, circa_alerts) — lists of SplitAlert objects.
    """
    config = get_config(sport)
    threshold = config.get("threshold", 25)

    dk_alerts, circa_alerts = await asyncio.gather(
        _fetch_dk_splits(sport, threshold),
        _fetch_circa_splits(sport, threshold),
    )

    return dk_alerts, circa_alerts
