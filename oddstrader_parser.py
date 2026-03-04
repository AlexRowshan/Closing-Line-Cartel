"""
OddsTrader Betting Lines Parser
---------------------------------
Parses raw innerText from OddsTrader's NCAAB spread and totals comparison pages
and extracts Bovada-specific lines.

Actual OddsTrader text format (confirmed from spreadsplits.txt / totalsmarket.txt):

  Team Name        <- team name (alpha string)
  10-15            <- win-loss record (\d+-\d+)
  53%              <- public betting percentage (ignored)
  +5 -110          <- best line across all books (value + odds)
  Everygame        <- book offering the best line
                   <- blank
  +4 -110          <- Opener
                   <- blank
  +5 -115          <- BetOnline
                   <- blank
  +4½ -105         <- BetAnything
                   <- blank
  +5 -115          <- Bovada  (4th book, index 3)
                   <- blank
  +4½ -108         <- Heritage
  +5 -115          <- Bookmaker
  +5 -115          <- JustBet

Book column order is extracted dynamically from the page header so this stays
correct if OddsTrader ever reorders books.

For totals, line values look like "o148½ -110" (over) or "u149 -108" (under).
"""

import re
from dataclasses import dataclass

RECORD_RE = re.compile(r"^\d+-\d+$")
PCT_RE = re.compile(r"^\d+%$")

# Spread line: e.g. "+5 -110", "-4½ -115", "+14½ -110"
SPREAD_LINE_RE = re.compile(
    r"^([+-]\d+(?:½|\.\d+)?)\s+([+-]\d+)$"
)

# Totals line: e.g. "o148½ -110", "u149 -108"
TOTAL_LINE_RE = re.compile(
    r"^([ou])(\d+(?:½|\.\d+)?)\s+([+-]\d+)$"
)

# Noise lines to discard
NOISE_PATTERNS = [
    re.compile(r"^bell$", re.I),
    re.compile(r"^personalize", re.I),
    re.compile(r"^starts in", re.I),
    re.compile(r"^got it$", re.I),
    re.compile(r"^logo-", re.I),
    re.compile(r"^ncaab$", re.I),
    re.compile(r"^tv", re.I),
    re.compile(r"^\d+%$"),  # pct lines (dealt with separately, also skip as noise later)
    re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)\s+\d{2}/\d{2}$", re.I),
    re.compile(r"^\s*$"),
]

# Known book names on OddsTrader (used to detect end of a team block)
KNOWN_BOOKS = {
    "opener", "betonline", "betanything", "bovada", "heritage",
    "bookmaker", "justbet", "everygame", "mybookie", "betmgm",
    "draftkings", "fanduel", "caesars", "pointsbet", "bet365",
    "barstool", "espnbet", "fanatics",
}


def _is_noise(line: str) -> bool:
    for pat in NOISE_PATTERNS:
        if pat.match(line.strip()):
            return True
    return False


def _is_record(line: str) -> bool:
    return bool(RECORD_RE.match(line.strip()))


def _is_book_name(line: str) -> bool:
    return line.strip().lower() in KNOWN_BOOKS


def _is_line_value(line: str) -> bool:
    s = line.strip()
    return bool(SPREAD_LINE_RE.match(s) or TOTAL_LINE_RE.match(s))


def _normalize_line(line_str: str) -> str:
    """Convert ½ to .5 for consistency."""
    return line_str.replace("½", ".5")


def _team_name_key(name: str) -> str:
    return name.strip().lower()


@dataclass
class BovadaEntry:
    team: str          # normalized team name
    opponent: str      # the other team in the same game (for two-team matching)
    bovada_line: str   # e.g. "+5" for spread, "148.5" for total
    bovada_odds: str   # e.g. "-115"
    is_best_price: bool
    direction: str     # "over" / "under" for totals; "" for spreads
    market: str        # "spread" or "total"


def _parse_blocks(text: str) -> list[dict]:
    """
    Split the raw innerText into team blocks.
    Each block = {name, record, lines: [line_str, ...], best_book}
    """
    raw_lines = [l.strip() for l in text.splitlines()]

    # First pass: find the book order from the header section
    # The header lists book names before any team data appears.
    # We'll detect the column order by finding consecutive known-book lines
    # near the top of the file.
    book_order = _extract_book_order(raw_lines)

    blocks = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]

        # Skip noise
        if _is_noise(line) or not line:
            i += 1
            continue

        # Detect team block start: alpha line followed by record
        if re.match(r"^[A-Za-z]", line) and not _is_book_name(line):
            # Peek ahead for a record line (skip blanks/noise)
            j = i + 1
            while j < len(raw_lines) and (_is_noise(raw_lines[j]) or not raw_lines[j]):
                j += 1

            if j < len(raw_lines) and _is_record(raw_lines[j]):
                team_name = line
                record = raw_lines[j]

                # Skip past record, then skip pct line
                k = j + 1
                while k < len(raw_lines) and (_is_noise(raw_lines[k]) or not raw_lines[k]):
                    k += 1

                # Skip the public-% line (either "X%" or "-" no-data placeholder)
                if k < len(raw_lines) and (
                    PCT_RE.match(raw_lines[k].strip()) or raw_lines[k].strip() == "-"
                ):
                    k += 1

                # Next non-blank is best_line_value
                while k < len(raw_lines) and (not raw_lines[k] or _is_noise(raw_lines[k])):
                    k += 1

                if k < len(raw_lines) and _is_line_value(raw_lines[k]):
                    best_line = raw_lines[k]
                    k += 1

                    # Next non-blank is best_book name
                    while k < len(raw_lines) and (not raw_lines[k] or _is_noise(raw_lines[k])):
                        k += 1

                    best_book = ""
                    if k < len(raw_lines) and _is_book_name(raw_lines[k]):
                        best_book = raw_lines[k].strip()
                        k += 1

                    # Collect individual book lines (up to MAX_BOOKS).
                    # Keep "-" as a None placeholder so Bovada's index stays correct
                    # when a book has no line for a given game.
                    MAX_BOOKS = 8
                    individual_lines = []
                    while k < len(raw_lines) and len(individual_lines) < MAX_BOOKS:
                        val = raw_lines[k].strip()
                        k += 1
                        if not val or _is_noise(val):
                            continue
                        # Stop if we hit a new team block
                        if re.match(r"^[A-Za-z]", val) and not _is_book_name(val):
                            # Check if next non-blank is a record
                            m = k
                            while m < len(raw_lines) and (not raw_lines[m] or _is_noise(raw_lines[m])):
                                m += 1
                            if m < len(raw_lines) and _is_record(raw_lines[m]):
                                k = k - 1  # back up so outer loop sees this team
                                break
                        # Accept valid line values OR "-" (no line at this book)
                        if _is_line_value(val):
                            individual_lines.append(val)
                        elif val == "-":
                            individual_lines.append(None)  # placeholder, preserves index

                    blocks.append({
                        "name": team_name,
                        "record": record,
                        "best_line": best_line,
                        "best_book": best_book.lower(),
                        "individual_lines": individual_lines,
                        "book_order": book_order,
                    })
                    i = k
                    continue

        i += 1

    return blocks


def _extract_book_order(raw_lines: list[str]) -> list[str]:
    """
    Find consecutive known-book name lines near the top of the file
    (the header column row). Returns list of lowercased book names.

    The standard OddsTrader NCAAB book order is:
      Opener, BetOnline, BetAnything, Bovada, Heritage, Bookmaker, JustBet

    If the page only shows a partial header (e.g. just "OPENER"), fall back
    to the full standard order so _bovada_index() returns 3 correctly.
    """
    book_sequence = []
    collecting = False
    for line in raw_lines[:150]:
        s = line.strip().lower()
        if s in KNOWN_BOOKS:
            book_sequence.append(s)
            collecting = True
        elif collecting and s:
            break

    # Only trust the extracted order if it lists at least 4 books (enough to
    # include Bovada). Otherwise use the known standard order.
    if len(book_sequence) < 4:
        book_sequence = ["opener", "betonline", "betanything", "bovada",
                         "heritage", "bookmaker", "justbet"]
    return book_sequence


def _bovada_index(book_order: list[str]) -> int:
    """Return 0-based index of Bovada in the book order list."""
    try:
        return book_order.index("bovada")
    except ValueError:
        return 3  # fallback: 4th position (0-indexed: 3)


def _parse_spread_line(line_str: str) -> tuple[str, str]:
    """Returns (spread_value, odds) e.g. ('+5', '-110')"""
    m = SPREAD_LINE_RE.match(line_str.strip())
    if m:
        return _normalize_line(m.group(1)), m.group(2)
    return "", ""


def _parse_total_line(line_str: str) -> tuple[str, str, str]:
    """Returns (direction, number, odds) e.g. ('over', '148.5', '-110')"""
    m = TOTAL_LINE_RE.match(line_str.strip())
    if m:
        direction = "over" if m.group(1) == "o" else "under"
        number = _normalize_line(m.group(2))
        return direction, number, m.group(3)
    return "", "", ""


def parse_oddstrader(
    spreads_text: str,
    totals_text: str,
) -> tuple[dict[str, BovadaEntry], dict[str, BovadaEntry]]:
    """
    Parse OddsTrader spreads and totals text.

    Returns:
        bovada_spreads: dict mapping lowercased team name → BovadaEntry (market="spread")
        bovada_totals:  dict mapping lowercased team name → BovadaEntry (market="total")
    """
    bovada_spreads: dict[str, BovadaEntry] = {}
    bovada_totals: dict[str, BovadaEntry] = {}

    # --- Spreads ---
    spread_blocks = _parse_blocks(spreads_text)
    # Pair consecutive blocks: OddsTrader always lists away team then home team
    for i in range(0, len(spread_blocks) - 1, 2):
        block_a = spread_blocks[i]
        block_b = spread_blocks[i + 1]

        for block, opp_block in [(block_a, block_b), (block_b, block_a)]:
            book_order = block["book_order"]
            bov_idx = _bovada_index(book_order)
            is_best = block["best_book"] == "bovada"

            if is_best:
                spread_val, odds = _parse_spread_line(block["best_line"])
            else:
                ind = block["individual_lines"]
                if bov_idx < len(ind) and ind[bov_idx] is not None:
                    spread_val, odds = _parse_spread_line(ind[bov_idx])
                else:
                    spread_val, odds = "", ""

            if spread_val:
                key = _team_name_key(block["name"])
                bovada_spreads[key] = BovadaEntry(
                    team=block["name"],
                    opponent=opp_block["name"],
                    bovada_line=spread_val,
                    bovada_odds=odds,
                    is_best_price=is_best,
                    direction="",
                    market="spread",
                )

    # Handle odd trailing block (no opponent to pair with)
    if len(spread_blocks) % 2 == 1:
        block = spread_blocks[-1]
        book_order = block["book_order"]
        bov_idx = _bovada_index(book_order)
        is_best = block["best_book"] == "bovada"
        if is_best:
            spread_val, odds = _parse_spread_line(block["best_line"])
        else:
            ind = block["individual_lines"]
            if bov_idx < len(ind) and ind[bov_idx] is not None:
                spread_val, odds = _parse_spread_line(ind[bov_idx])
            else:
                spread_val, odds = "", ""
        if spread_val:
            key = _team_name_key(block["name"])
            bovada_spreads[key] = BovadaEntry(
                team=block["name"], opponent="",
                bovada_line=spread_val, bovada_odds=odds,
                is_best_price=is_best, direction="", market="spread",
            )

    # --- Totals ---
    total_blocks = _parse_blocks(totals_text)
    for i in range(0, len(total_blocks) - 1, 2):
        block_a = total_blocks[i]
        block_b = total_blocks[i + 1]

        for block, opp_block in [(block_a, block_b), (block_b, block_a)]:
            book_order = block["book_order"]
            bov_idx = _bovada_index(book_order)
            is_best = block["best_book"] == "bovada"

            if is_best:
                direction, number, odds = _parse_total_line(block["best_line"])
            else:
                ind = block["individual_lines"]
                if bov_idx < len(ind) and ind[bov_idx] is not None:
                    direction, number, odds = _parse_total_line(ind[bov_idx])
                else:
                    direction, number, odds = "", "", ""

            if number:
                key = _team_name_key(block["name"])
                bovada_totals[key] = BovadaEntry(
                    team=block["name"],
                    opponent=opp_block["name"],
                    bovada_line=number,
                    bovada_odds=odds,
                    is_best_price=is_best,
                    direction=direction,
                    market="total",
                )

    # Handle odd trailing block
    if len(total_blocks) % 2 == 1:
        block = total_blocks[-1]
        book_order = block["book_order"]
        bov_idx = _bovada_index(book_order)
        is_best = block["best_book"] == "bovada"
        if is_best:
            direction, number, odds = _parse_total_line(block["best_line"])
        else:
            ind = block["individual_lines"]
            if bov_idx < len(ind) and ind[bov_idx] is not None:
                direction, number, odds = _parse_total_line(ind[bov_idx])
            else:
                direction, number, odds = "", "", ""
        if number:
            key = _team_name_key(block["name"])
            bovada_totals[key] = BovadaEntry(
                team=block["name"], opponent="",
                bovada_line=number, bovada_odds=odds,
                is_best_price=is_best, direction=direction, market="total",
            )

    return bovada_spreads, bovada_totals


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python oddstrader_parser.py <spreadsplits.txt> <totalsmarket.txt>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        spreads_text = f.read()
    with open(sys.argv[2]) as f:
        totals_text = f.read()

    bovada_spreads, bovada_totals = parse_oddstrader(spreads_text, totals_text)

    print("=== Bovada Spread Lines ===")
    for team, entry in sorted(bovada_spreads.items()):
        flag = " *** BEST PRICE ***" if entry.is_best_price else ""
        print(f"  {entry.team}: {entry.bovada_line} ({entry.bovada_odds}){flag}")

    print("\n=== Bovada Total Lines ===")
    for team, entry in sorted(bovada_totals.items()):
        flag = " *** BEST PRICE ***" if entry.is_best_price else ""
        print(f"  {entry.team}: {entry.direction} {entry.bovada_line} ({entry.bovada_odds}){flag}")
