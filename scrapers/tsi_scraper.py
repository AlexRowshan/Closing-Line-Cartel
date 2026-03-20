"""
Playwright-based scraper for Tyler Shoemaker's TSI projections on VSIN.

Discovers article URLs from the author page, then fetches raw text from
each article matching the target dates.
"""

import asyncio
import re
from datetime import date, timedelta
from playwright.async_api import async_playwright

from .browser_utils import BROWSER_ARGS, _new_page, _get_inner_text


AUTHOR_URL = "https://vsin.com/author/tyler-shoemaker/"

# Block heavy resources — we only need plain text from these article pages.
_TSI_BLOCK_TYPES = {"image", "media", "font", "stylesheet"}

# Month names/abbreviations used in article titles
_MONTH_NAMES = {
    1: ("January", "Jan"),
    2: ("February", "Feb"),
    3: ("March", "Mar"),
    4: ("April", "Apr"),
    5: ("May", "May"),
    6: ("June", "Jun"),
    7: ("July", "Jul"),
    8: ("August", "Aug"),
    9: ("September", "Sep"),
    10: ("October", "Oct"),
    11: ("November", "Nov"),
    12: ("December", "Dec"),
}


def _title_matches_date(title: str, target_date: date) -> bool:
    """Check if an article title contains a date like 'March 19' or 'Mar 19'."""
    full_name, abbrev = _MONTH_NAMES[target_date.month]
    day = str(target_date.day)
    title_lower = title.lower()
    for name in (full_name, abbrev):
        if name.lower() in title_lower and day in title:
            # Verify it's actually "Month day" not a substring match on day
            pattern = rf"(?i){name}\s+{day}(?!\d)"
            if re.search(pattern, title):
                return True
    return False


async def _find_tsi_article_urls(
    page, target_dates: list[date]
) -> list[str]:
    """Discover TSI article URLs from the author page."""
    try:
        await page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in _TSI_BLOCK_TYPES
            else route.continue_(),
        )
        await page.goto(AUTHOR_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(1)
    except Exception as e:
        print(f"[tsi_scraper] Failed to load author page: {e}")
        return []

    links = await page.query_selector_all("a")
    urls = []
    for link in links:
        try:
            href = await link.get_attribute("href")
            text = await link.inner_text()
        except Exception:
            continue
        if not href or not text:
            continue
        text_lower = text.lower()
        if "college basketball" not in text_lower:
            continue
        for target_date in target_dates:
            if _title_matches_date(text, target_date):
                if href not in urls:
                    urls.append(href)
                break

    return urls


async def _fetch_article_text(browser, url: str) -> str:
    """Fetch raw innerText from a single article page."""
    page = await _new_page(browser)
    try:
        await page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in _TSI_BLOCK_TYPES
            else route.continue_(),
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(1)
        return await _get_inner_text(page)
    finally:
        await page.close()


async def scrape_tsi(
    target_dates: list[date] | None = None,
) -> list[tuple[str, str]]:
    """
    Scrape TSI projection articles for the given dates.

    Returns list of (url, raw_text) tuples.
    Defaults target_dates to [today, tomorrow].
    """
    if target_dates is None:
        today = date.today()
        target_dates = [today, today + timedelta(days=1)]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        try:
            page = await _new_page(browser)
            urls = await _find_tsi_article_urls(page, target_dates)
            await page.close()

            if not urls:
                print(f"[tsi_scraper] No TSI articles found for {target_dates}")
                return []

            print(f"[tsi_scraper] Found {len(urls)} article(s): {urls}")

            results = []
            for url in urls:
                try:
                    text = await _fetch_article_text(browser, url)
                    results.append((url, text))
                except Exception as e:
                    print(f"[tsi_scraper] Failed to fetch {url}: {e}")
                    continue

            return results
        finally:
            await browser.close()


if __name__ == "__main__":
    results = asyncio.run(scrape_tsi())
    if not results:
        print("No articles found.")
    for url, text in results:
        print(f"\n{'='*80}")
        print(f"URL: {url}")
        print(f"{'='*80}")
        print(text[:500], "...")

    # Dump to file for parser testing
    if results:
        with open("tsi_raw.txt", "w") as f:
            for url, text in results:
                f.write(f"=== {url} ===\n")
                f.write(text)
                f.write("\n\n")
        print(f"\nDumped raw text to tsi_raw.txt")
