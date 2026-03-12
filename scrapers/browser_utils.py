"""
Shared Playwright browser configuration and low-level page utilities.
"""

from playwright.async_api import Page

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
