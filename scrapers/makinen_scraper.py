"""
Playwright-based scraper for Steve Makinen's NBA strength ratings on VSIN.

Generates the article URL dynamically from the current date and fetches
the raw page text for parsing.
"""

import asyncio
from datetime import date

from playwright.async_api import async_playwright

from .browser_utils import BROWSER_ARGS, _new_page, _get_inner_text


# Block heavy resources — we only need plain text.
_BLOCK_TYPES = {"image", "media", "font", "stylesheet"}

_URL_TEMPLATE = (
    "https://vsin.com/nba/"
    "steve-makinens-nba-betting-trends-and-best-bets-for-"
    "{weekday}-{month}-{day}/"
)


def _build_url(target_date: date) -> str:
    """Build the deterministic Makinen article URL for a given date."""
    weekday = target_date.strftime("%A").lower()      # e.g. "wednesday"
    month = target_date.strftime("%B").lower()         # e.g. "march"
    day = str(target_date.day)                         # e.g. "25" (no leading zero)
    return _URL_TEMPLATE.format(weekday=weekday, month=month, day=day)


async def scrape_makinen(
    target_date: date | None = None,
) -> tuple[str, str]:
    """
    Scrape Steve Makinen's NBA strength ratings article for the given date.

    Returns (url, raw_text).  If the article doesn't exist (404 / error),
    raw_text is returned as an empty string so the pipeline can fall back
    to splits-only scoring.
    """
    if target_date is None:
        target_date = date.today()

    url = _build_url(target_date)
    print(f"[makinen_scraper] Target URL: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        try:
            page = await _new_page(browser)
            try:
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in _BLOCK_TYPES
                    else route.continue_(),
                )
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=45000
                )

                # Handle 404 / non-200 gracefully
                if response and response.status >= 400:
                    print(
                        f"[makinen_scraper] Article not found "
                        f"(HTTP {response.status}): {url}"
                    )
                    return (url, "")

                await asyncio.sleep(1)  # let JS settle
                raw_text = await _get_inner_text(page)
                print(
                    f"[makinen_scraper] Fetched {len(raw_text)} chars "
                    f"from {url}"
                )
                return (url, raw_text)

            except Exception as e:
                print(f"[makinen_scraper] Failed to fetch {url}: {e}")
                return (url, "")
            finally:
                await page.close()
        finally:
            await browser.close()


if __name__ == "__main__":
    url, text = asyncio.run(scrape_makinen())
    if not text:
        print("No article text fetched.")
    else:
        print(f"\nURL: {url}")
        print(f"Length: {len(text)} chars")
        print(text[:500], "...")

        with open("makinen_raw.txt", "w") as f:
            f.write(f"=== {url} ===\n")
            f.write(text)
        print("\nDumped raw text to makinen_raw.txt")
