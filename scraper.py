"""
Playwright-based scrapers for VSIN and OddsTrader.

VSIN: https://data.vsin.com/college-basketball/betting-splits/
  - Scrapes DraftKings tab (default), then clicks Circa Sports tab.
  - Returns raw innerText strings matching the copy-paste format the
    existing vsin_splits_parser.py was designed for.

OddsTrader:
  - Spreads: https://www.oddstrader.com/ncaa-college-basketball/
  - Totals:  https://www.oddstrader.com/ncaa-college-basketball/?eid&g=game&m=total
  - Each view has its own URL so no tab-clicking needed.
"""

import asyncio
import re
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

VSIN_URL = "https://data.vsin.com/college-basketball/betting-splits/"
ODDSTRADER_SPREADS_URL = "https://www.oddstrader.com/ncaa-college-basketball/"
ODDSTRADER_TOTALS_URL = "https://www.oddstrader.com/ncaa-college-basketball/?eid&g=game&m=total"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Flags that prevent Chromium from crashing in memory-constrained Docker containers.
# --disable-dev-shm-usage is the most critical: without it Chromium writes to /dev/shm
# which is capped at 64 MB in most containers, causing "Target crashed" on heavy pages.
BROWSER_ARGS = [
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-sync",
    "--no-first-run",
    "--mute-audio",
]

# Resource types to block on OddsTrader.
# Keep this conservative: OddsTrader appears to depend on some visual assets for
# complete sportsbook labeling (e.g., Bovada rows).
_BLOCK_TYPES = {"media", "font"}


async def _new_page(browser) -> Page:
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
    )
    page = await context.new_page()
    return page


async def _get_inner_text(page: Page) -> str:
    return await page.evaluate("document.body.innerText")


async def scrape_vsin() -> tuple[str, str]:
    """
    Returns (dk_text, circa_text): raw innerText from the VSIN DraftKings
    and Circa Sports betting splits tabs.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        page = await _new_page(browser)

        try:
            await page.goto(VSIN_URL, wait_until="domcontentloaded", timeout=30000)

            # Wait for game data rows to appear
            try:
                await page.wait_for_selector("table", timeout=15000)
            except PlaywrightTimeoutError:
                pass  # Page may not use a <table>; proceed anyway

            # Small delay for any JS post-render
            await asyncio.sleep(2)
            dk_text = await _get_inner_text(page)

            # Find and click the Circa Sports tab
            # Common patterns: button/tab with text "Circa" or "Circa Sports"
            clicked_circa = False
            for selector in [
                "text=Circa Sports",
                "text=Circa",
                "[data-book='circa']",
                "button:has-text('Circa')",
                "a:has-text('Circa')",
                "li:has-text('Circa')",
            ]:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0:
                        await element.click()
                        await asyncio.sleep(2)
                        clicked_circa = True
                        break
                except Exception:
                    continue

            if not clicked_circa:
                # Return DK text twice as fallback; pipeline handles empty Circa gracefully
                circa_text = ""
            else:
                circa_text = await _get_inner_text(page)

        finally:
            await browser.close()

    return dk_text, circa_text


async def _fetch_oddstrader_page(browser, url: str) -> str:
    """Load a single OddsTrader URL using an existing browser instance."""
    page = await _new_page(browser)
    try:
        # Block visual-heavy resources; we only need text data from the DOM.
        await page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in _BLOCK_TYPES
            else route.continue_(),
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Wait for game rows (win-loss records indicate data has loaded)
        try:
            await page.wait_for_selector("text=/\\d+-\\d+/", timeout=15000)
        except PlaywrightTimeoutError:
            pass
        await asyncio.sleep(2)
        return await _get_inner_text(page)
    finally:
        await page.close()


async def scrape_oddstrader() -> tuple[str, str]:
    """
    Returns (spreads_text, totals_text): raw innerText from OddsTrader's
    NCAAB spreads and totals pages.
    Both pages share one browser instance to minimise memory usage.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        try:
            spreads_text = await _fetch_oddstrader_page(browser, ODDSTRADER_SPREADS_URL)
            totals_text = await _fetch_oddstrader_page(browser, ODDSTRADER_TOTALS_URL)
        finally:
            await browser.close()
    return spreads_text, totals_text


if __name__ == "__main__":
    async def main():
        print("Scraping VSIN...")
        dk, circa = await scrape_vsin()
        print(f"DK text length: {len(dk)}")
        print(f"Circa text length: {len(circa)}")
        with open("dk_raw.txt", "w") as f:
            f.write(dk)
        with open("circa_raw.txt", "w") as f:
            f.write(circa)

        print("\nScraping OddsTrader...")
        spreads, totals = await scrape_oddstrader()
        print(f"Spreads text length: {len(spreads)}")
        print(f"Totals text length: {len(totals)}")
        with open("spreads_raw.txt", "w") as f:
            f.write(spreads)
        with open("totals_raw.txt", "w") as f:
            f.write(totals)
        print("Raw text saved to *_raw.txt files for inspection.")

    asyncio.run(main())
