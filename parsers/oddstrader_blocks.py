"""
OddsTrader raw-text block parser.
Splits the page innerText into per-team data blocks and extracts the book column order.
"""

import re

from .oddstrader_values import (
    PCT_RE, KNOWN_BOOKS,
    _is_noise, _is_record, _is_book_name, _is_line_value,
)


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


def _parse_blocks(text: str) -> list[dict]:
    """
    Split the raw innerText into team blocks.
    Each block = {name, record, lines: [line_str, ...], best_book}
    """
    raw_lines = [l.strip() for l in text.splitlines()]
    book_order = _extract_book_order(raw_lines)

    blocks = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]

        if _is_noise(line) or not line:
            i += 1
            continue

        # Detect team block start: alpha line followed by record
        if re.match(r"^[A-Za-z]", line) and not _is_book_name(line):
            j = i + 1
            while j < len(raw_lines) and (_is_noise(raw_lines[j]) or not raw_lines[j]):
                j += 1

            if j < len(raw_lines) and _is_record(raw_lines[j]):
                team_name = line
                record = raw_lines[j]

                k = j + 1
                while k < len(raw_lines) and (_is_noise(raw_lines[k]) or not raw_lines[k]):
                    k += 1

                # Skip the public-% line (either "X%" or "-" no-data placeholder)
                if k < len(raw_lines) and (
                    PCT_RE.match(raw_lines[k].strip()) or raw_lines[k].strip() == "-"
                ):
                    k += 1

                while k < len(raw_lines) and (not raw_lines[k] or _is_noise(raw_lines[k])):
                    k += 1

                if k < len(raw_lines) and _is_line_value(raw_lines[k]):
                    best_line = raw_lines[k]
                    k += 1

                    while k < len(raw_lines) and (not raw_lines[k] or _is_noise(raw_lines[k])):
                        k += 1

                    best_book = ""
                    if k < len(raw_lines) and _is_book_name(raw_lines[k]):
                        best_book = raw_lines[k].strip()
                        k += 1

                    MAX_BOOKS = 8
                    individual_lines = []
                    while k < len(raw_lines) and len(individual_lines) < MAX_BOOKS:
                        val = raw_lines[k].strip()
                        k += 1
                        if not val or _is_noise(val):
                            continue
                        # Stop if we hit a new team block
                        if re.match(r"^[A-Za-z]", val) and not _is_book_name(val):
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
