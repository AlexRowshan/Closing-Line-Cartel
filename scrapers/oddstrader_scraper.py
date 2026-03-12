"""
Playwright-based scraper for OddsTrader betting lines.
Both pages share one browser instance to minimise memory usage.
"""

import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from sport_config import get_config
from .browser_utils import BROWSER_ARGS, _BLOCK_TYPES, _new_page, _get_inner_text


async def _fetch_oddstrader_page(browser, url: str) -> str:
    """Load a single OddsTrader URL using an existing browser instance."""
    page = await _new_page(browser)
    try:
        await page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in _BLOCK_TYPES
            else route.continue_(),
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
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
