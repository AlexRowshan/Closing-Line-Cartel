"""
Playwright-based scraper for VSIN betting splits.

CBB (vsin_use_tabs=True):
  VSIN: https://data.vsin.com/college-basketball/betting-splits/
    - Scrapes DraftKings tab (default), then clicks Circa Sports tab.

NBA (vsin_use_tabs=False):
  VSIN: Two direct URLs — no tab clicking needed.
    - DK:    https://data.vsin.com/betting-splits/?bookid=dk&view=nba
    - Circa: https://data.vsin.com/betting-splits/?bookid=circa&view=nba
"""

import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from sport_config import get_config
from .browser_utils import BROWSER_ARGS, _new_page, _get_inner_text


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
                page = await _new_page(browser)

                await page.goto(config["vsin_dk_url"], wait_until="domcontentloaded", timeout=20000)
                try:
                    await page.wait_for_selector("table", timeout=8000)
                except PlaywrightTimeoutError:
                    pass
                await asyncio.sleep(1)
                dk_text = await _get_inner_text(page)

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
                dk_text = await _fetch_vsin_direct(browser, config["vsin_dk_url"])
                circa_text = await _fetch_vsin_direct(browser, config["vsin_circa_url"])

        finally:
            await browser.close()

    return dk_text, circa_text
