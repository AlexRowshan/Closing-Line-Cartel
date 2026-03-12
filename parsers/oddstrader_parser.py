"""
OddsTrader Betting Lines Parser
---------------------------------
Parses raw innerText from OddsTrader's NCAAB spread and totals comparison pages
and extracts Bovada-specific lines.

Usage:
    python oddstrader_parser.py <spreadsplits.txt> <totalsmarket.txt>
"""

from dataclasses import dataclass

from .oddstrader_blocks import _parse_blocks, _bovada_index
from .oddstrader_values import _parse_spread_line, _parse_total_line


@dataclass
class BovadaEntry:
    team: str          # normalized team name
    opponent: str      # the other team in the same game (for two-team matching)
    bovada_line: str   # e.g. "+5" for spread, "148.5" for total
    bovada_odds: str   # e.g. "-115"
    is_best_price: bool
    direction: str     # "over" / "under" for totals; "" for spreads
    market: str        # "spread" or "total"


def _team_name_key(name: str) -> str:
    return name.strip().lower()


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
        bov_idx = _bovada_index(block["book_order"])
        is_best = block["best_book"] == "bovada"
        if is_best:
            spread_val, odds = _parse_spread_line(block["best_line"])
        else:
            ind = block["individual_lines"]
            spread_val, odds = (_parse_spread_line(ind[bov_idx])
                                if bov_idx < len(ind) and ind[bov_idx] is not None
                                else ("", ""))
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
        bov_idx = _bovada_index(block["book_order"])
        is_best = block["best_book"] == "bovada"
        if is_best:
            direction, number, odds = _parse_total_line(block["best_line"])
        else:
            ind = block["individual_lines"]
            direction, number, odds = (_parse_total_line(ind[bov_idx])
                                       if bov_idx < len(ind) and ind[bov_idx] is not None
                                       else ("", "", ""))
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
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from parsers.oddstrader_parser import parse_oddstrader as _parse

    if len(sys.argv) < 3:
        print("Usage: python oddstrader_parser.py <spreadsplits.txt> <totalsmarket.txt>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        spreads_text = f.read()
    with open(sys.argv[2]) as f:
        totals_text = f.read()

    bovada_spreads, bovada_totals = _parse(spreads_text, totals_text)

    print("=== Bovada Spread Lines ===")
    for team, entry in sorted(bovada_spreads.items()):
        flag = " *** BEST PRICE ***" if entry.is_best_price else ""
        print(f"  {entry.team}: {entry.bovada_line} ({entry.bovada_odds}){flag}")

    print("\n=== Bovada Total Lines ===")
    for team, entry in sorted(bovada_totals.items()):
        flag = " *** BEST PRICE ***" if entry.is_best_price else ""
        print(f"  {entry.team}: {entry.direction} {entry.bovada_line} ({entry.bovada_odds}){flag}")
