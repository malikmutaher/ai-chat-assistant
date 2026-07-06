"""
Selenium-based page scraper.

Given a clothing website URL, loads the page in a headless Chrome browser
(so JS-rendered product listings actually appear in the DOM, unlike a plain
requests.get) and returns the rendered HTML for scraping/cleaner.py to turn
into structured Product rows.

This replaces the SeleniumURLLoader/LangChain document-loading step used in
the original RAG prototype — we now want raw HTML (to parse for prices,
sizes, colors) rather than LangChain Document chunks for embedding.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    url: str
    html: str
    success: bool
    error: Optional[str] = None


def _build_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    # Return after the initial DOM is ready instead of waiting for every
    # image/tracker/script. Storefronts often keep long-running requests open.
    options.page_load_strategy = "eager"
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # A realistic UA reduces the odds of being served a bot-blocked page.
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not urlparse(url).scheme:
        return f"https://{url}"
    return url


def scrape_website(
    url: str,
    wait_seconds: int = 20,
    scroll_passes: int = 3,
    scroll_pause: float = 1.0,
) -> ScrapeResult:
    """
    Loads `url` in headless Chrome and returns the fully rendered HTML.

    - Waits for <body> to be present before reading the page.
    - Scrolls down a few times (`scroll_passes`), since many storefronts
      lazy-load product grids as the user scrolls.
    - Never raises on failure — returns ScrapeResult(success=False, error=...)
      so the FastAPI route can return a clean error to the frontend instead
      of a 500.
    """
    driver = None
    url = _normalize_url(url)
    try:
        driver = _build_driver()
        driver.set_page_load_timeout(wait_seconds)
        try:
            driver.get(url)
        except TimeoutException:
            logger.warning("Page load timed out, attempting to use partial HTML: %s", url)
            # Stop pending network activity; the DOM may already contain the
            # product grid even though Chrome was still loading assets.
            try:
                driver.execute_script("window.stop();")
            except WebDriverException:
                pass

        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        for _ in range(scroll_passes):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause)

        html = driver.page_source
        if html and "<body" in html.lower():
            return ScrapeResult(url=url, html=html, success=True)
        return ScrapeResult(url=url, html="", success=False, error="Page loaded without readable HTML")

    except TimeoutException:
        logger.warning("Timed out waiting for page to load: %s", url)
        return ScrapeResult(url=url, html="", success=False, error="Page load timed out")

    except WebDriverException as e:
        logger.error("WebDriver error scraping %s: %s", url, e)
        return ScrapeResult(url=url, html="", success=False, error=str(e))

    finally:
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    # Manual smoke test: `python scraper.py <url>`
    import sys

    logging.basicConfig(level=logging.INFO)
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.breakout.com.pk/"
    result = scrape_website(test_url)
    if result.success:
        print(f"Scraped {len(result.html)} characters from {test_url}")
    else:
        print(f"Scrape failed: {result.error}")
