"""
Playwright-based scrapers for VSIN and OddsTrader.

CBB (vsin_use_tabs=True):
  VSIN: https://data.vsin.com/college-basketball/betting-splits/
    - Scrapes DraftKings tab (default), then clicks Circa Sports tab.

NBA (vsin_use_tabs=False):
  VSIN: Two direct URLs — no tab clicking needed.
    - DK:    https://data.vsin.com/betting-splits/?bookid=dk&view=nba
    - Circa: https://data.vsin.com/betting-splits/?bookid=circa&view=nba

OddsTrader: sport-specific URLs, each view is a separate URL (no tab clicking).
"""

import asyncio
import re
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

from sport_config import get_config

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


async def _fetch_vsin_direct(browser, url: str) -> str:
    """
    Fetch a VSIN page by navigating directly to a URL (used for NBA where
    each book has its own URL with query params).
    """
    page = await _new_page(browser)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        try:
            await page.wait_for_selector("table", timeout=8000)
        except PlaywrightTimeoutError:
            pass
        await asyncio.sleep(1)
        return await _get_inner_text(page)
    finally:
        await page.close()


async def scrape_vsin(sport: str = "cbb") -> tuple[str, str]:
    """
    Returns (dk_text, circa_text): raw innerText from the VSIN DraftKings
    and Circa Sports betting splits pages for the given sport.

    CBB: loads one URL then clicks the Circa tab.
    NBA: loads two separate direct URLs (no tab clicking needed).
    """
    config = get_config(sport)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        try:
            if config["vsin_use_tabs"]:
                # CBB path: one base URL, click Circa tab for second dataset
                page = await _new_page(browser)

                await page.goto(config["vsin_dk_url"], wait_until="domcontentloaded", timeout=20000)
                try:
                    await page.wait_for_selector("table", timeout=8000)
                except PlaywrightTimeoutError:
                    pass
                await asyncio.sleep(1)
                dk_text = await _get_inner_text(page)

                # Find and click the Circa Sports tab
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
                            await asyncio.sleep(1)
                            clicked_circa = True
                            break
                    except Exception:
                        continue

                circa_text = await _get_inner_text(page) if clicked_circa else ""

            else:
                # NBA path: two direct URLs, fetched sequentially on the same browser
                dk_text = await _fetch_vsin_direct(browser, config["vsin_dk_url"])
                circa_text = await _fetch_vsin_direct(browser, config["vsin_circa_url"])

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
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        # Wait for game rows (win-loss records indicate data has loaded)
        try:
            await page.wait_for_selector("text=/\\d+-\\d+/", timeout=8000)
        except PlaywrightTimeoutError:
            pass
        await asyncio.sleep(1)
        return await _get_inner_text(page)
    finally:
        await page.close()


async def scrape_oddstrader(sport: str = "cbb") -> tuple[str, str]:
    """
    Returns (spreads_text, totals_text): raw innerText from OddsTrader's
    spreads and totals pages for the given sport.
    Both pages share one browser instance to minimise memory usage.
    """
    config = get_config(sport)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        try:
            spreads_text = await _fetch_oddstrader_page(browser, config["oddstrader_spreads_url"])
            totals_text = await _fetch_oddstrader_page(browser, config["oddstrader_totals_url"])
        finally:
            await browser.close()
    return spreads_text, totals_text


if __name__ == "__main__":
    import sys

    sport_arg = sys.argv[1] if len(sys.argv) > 1 else "cbb"
    print(f"Sport: {sport_arg.upper()}")

    async def main():
        print("Scraping VSIN...")
        dk, circa = await scrape_vsin(sport_arg)
        print(f"DK text length: {len(dk)}")
        print(f"Circa text length: {len(circa)}")
        with open("dk_raw.txt", "w") as f:
            f.write(dk)
        with open("circa_raw.txt", "w") as f:
            f.write(circa)

        print("\nScraping OddsTrader...")
        spreads, totals = await scrape_oddstrader(sport_arg)
        print(f"Spreads text length: {len(spreads)}")
        print(f"Totals text length: {len(totals)}")
        with open("spreads_raw.txt", "w") as f:
            f.write(spreads)
        with open("totals_raw.txt", "w") as f:
            f.write(totals)
        print("Raw text saved to *_raw.txt files for inspection.")

    asyncio.run(main())
