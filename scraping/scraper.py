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
from collections import deque
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException

logger = logging.getLogger(__name__)

# Words that show up in category/collection nav links on clothing storefronts.
# Used to tell a "hub" link (worth crawling into) from a random footer/legal
# link (About Us, Privacy Policy, Contact, etc.) when a page has no products
# of its own — e.g. a homepage that only links out to /collections/men-shirts.
CATEGORY_LINK_KEYWORDS = [
    "shirt", "pant", "trouser", "chino", "jean", "denim", "shoe", "sneaker",
    "loafer", "boot", "kurta", "polo", "tee", "t-shirt", "hoodie", "jacket",
    "blazer", "suit", "collection", "men", "women", "kids", "shop", "category",
    "clothing", "apparel", "new-arrivals", "sale",
]

# Link text/href words that mean "skip this, it's not a product category".
CATEGORY_LINK_EXCLUDE = [
    "about", "contact", "privacy", "terms", "faq", "blog", "career",
    "return", "shipping", "track", "login", "signin", "signup", "cart",
    "wishlist", "account", "policy", "help", "store-locator",
]


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


def find_category_links(html: str, base_url: str, max_links: int = 8) -> List[str]:
    """
    Given the HTML of a page with no detectable products (e.g. a homepage),
    extracts likely category/collection links so the caller can crawl into
    them one level deep — e.g. monark.com.pk (no products) -> discovers
    monark.com.pk/collections/men-shirts, /collections/men-pants, etc.

    Heuristics only, same spirit as cleaner.py:
    - Same-domain links only (avoids wandering off to social media / payment
      gateway domains linked in the footer).
    - Link text OR href must contain a CATEGORY_LINK_KEYWORDS word.
    - Skip anything matching CATEGORY_LINK_EXCLUDE (about/contact/privacy/etc).
    - Deduplicated, capped at `max_links` to avoid crawling an entire site.
    """
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc

    seen: set = set()
    links: List[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc != base_domain:
            continue

        text = a.get_text(strip=True).lower()
        haystack = f"{text} {href.lower()}"

        if any(bad in haystack for bad in CATEGORY_LINK_EXCLUDE):
            continue
        if not any(kw in haystack for kw in CATEGORY_LINK_KEYWORDS):
            continue

        # Normalize away query/fragment so paginated or filtered variants of
        # the same category collapse into one crawl target.
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if clean_url in seen or clean_url == base_url.rstrip("/"):
            continue
        seen.add(clean_url)
        links.append(clean_url)

        if len(links) >= max_links:
            break

    return links


# Common button text for "load more products" patterns (as an alternative
# to pure infinite scroll — some storefronts use a button instead/as well).
LOAD_MORE_BUTTON_TEXT = [
    "load more", "show more", "view more", "more products", "load more products",
]


def _click_load_more_if_present(driver) -> bool:
    """
    Looks for a visible button/link whose text matches a "load more" pattern
    and clicks it. Returns True if something was clicked.
    Wrapped defensively — a failed click here should never crash the scrape.
    """
    try:
        candidates = driver.find_elements(By.XPATH, "//button | //a")
        for el in candidates:
            try:
                text = (el.text or "").strip().lower()
                if not text or not el.is_displayed():
                    continue
                if any(phrase in text for phrase in LOAD_MORE_BUTTON_TEXT):
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                    el.click()
                    return True
            except WebDriverException:
                continue
    except WebDriverException:
        pass
    return False


def _scroll_until_stable(
    driver,
    scroll_pause: float,
    max_scrolls: int,
    stable_rounds_required: int = 2,
) -> None:
    """
    Scrolls to the bottom repeatedly until the page height stops growing
    (i.e. no more lazy-loaded content appeared), rather than a fixed number
    of passes. This handles infinite-scroll grids that only load ~12
    products at a time as you scroll, instead of stopping after 3 scrolls.

    - `stable_rounds_required`: how many consecutive no-growth scrolls
      before we conclude there's nothing left to load (guards against a
      single slow-loading batch being mistaken for "done").
    - `max_scrolls`: hard cap so a truly infinite feed can't hang the
      scrape forever.
    - Also tries clicking a "Load more" button each round, since some
      storefronts paginate that way instead of (or in addition to) scroll.
    """
    last_height = driver.execute_script("return document.body.scrollHeight")
    stable_rounds = 0

    for _ in range(max_scrolls):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause)
        _click_load_more_if_present(driver)
        time.sleep(scroll_pause)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height <= last_height:
            stable_rounds += 1
            if stable_rounds >= stable_rounds_required:
                break
        else:
            stable_rounds = 0
        last_height = new_height


def scrape_website(
    url: str,
    wait_seconds: int = 20,
    scroll_passes: int = 3,
    scroll_pause: float = 1.0,
    max_scrolls: int = 25,
) -> ScrapeResult:
    """
    Loads `url` in headless Chrome and returns the fully rendered HTML.

    - Waits for <body> to be present before reading the page.
    - Scrolls repeatedly until the page height stops growing (handles
      infinite-scroll product grids that lazy-load in batches, e.g. 12 at
      a time), also clicking a "Load more" button if one appears, instead
      of a fixed `scroll_passes` count that stops too early.
    - `scroll_passes` is kept as a parameter for backward compatibility but
      is now used as a floor: we always do at least this many scrolls
      before considering height-stability.
    - `max_scrolls` is a hard cap so a genuinely endless feed can't hang
      the scrape indefinitely.
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

        # Guarantee at least `scroll_passes` scrolls (old behavior), then
        # keep going until height stabilizes or max_scrolls is hit.
        for _ in range(scroll_passes):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause)

        _scroll_until_stable(
            driver,
            scroll_pause=scroll_pause,
            max_scrolls=max(max_scrolls - scroll_passes, 0),
        )

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


def _is_same_domain(url: str, base_domain: str) -> bool:
    return urlparse(url).netloc == base_domain


def _extract_links(html: str, base_url: str) -> List[str]:
    """Extract all same-domain hyperlinks from HTML, skipping non-page links."""
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc
    links: Set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc != base_domain:
            continue
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if clean_url:
            links.add(clean_url)

    return list(links)


def _is_product_or_category_url(url: str) -> bool:
    """Check if a URL is likely a product listing or product detail page."""
    excluded = ["about", "contact", "privacy", "terms", "faq", "blog",
                "career", "return", "shipping", "track", "login", "signin",
                "signup", "cart", "wishlist", "account", "policy", "help",
                "store-locator", "search"]
    lower = url.lower()
    if any(bad in lower for bad in excluded):
        return False
    return True


def crawl_website(
    start_url: str,
    wait_seconds: int = 20,
    scroll_passes: int = 3,
    max_pages: int = 30,
) -> ScrapeResult:
    """
    BFS crawl starting from `start_url`.
    Visits product/category pages within the same domain, scrolls each for
    lazy-loaded products, and aggregates all HTML into one ScrapeResult.
    `max_pages` caps the total pages crawled to avoid runaway crawls.
    """
    start_url = _normalize_url(start_url)
    base_domain = urlparse(start_url).netloc

    visited: Set[str] = set()
    queue: deque = deque([start_url])
    all_html_parts: List[str] = []
    pages_crawled = 0
    last_error: Optional[str] = None

    while queue and pages_crawled < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if not _is_product_or_category_url(url):
            continue

        logger.info("Crawling [%d/%d]: %s", pages_crawled + 1, max_pages, url)

        result = scrape_website(
            url,
            wait_seconds=wait_seconds,
            scroll_passes=scroll_passes,
        )

        if result.success:
            all_html_parts.append(result.html)
            pages_crawled += 1

            new_links = _extract_links(result.html, url)
            for link in new_links:
                if link not in visited:
                    queue.append(link)
        else:
            last_error = result.error
            logger.warning("Failed to crawl %s: %s", url, result.error)

    if not all_html_parts:
        error_msg = last_error or "No pages could be crawled"
        return ScrapeResult(url=start_url, html="", success=False, error=error_msg)

    combined_html = "<html><body>" + "".join(all_html_parts) + "</body></html>"
    logger.info("Crawl complete: %d pages, %d chars total", pages_crawled, len(combined_html))
    return ScrapeResult(url=start_url, html=combined_html, success=True)


if __name__ == "__main__":
    # Manual smoke test: `python scraper.py <url>`
    import sys

    logging.basicConfig(level=logging.INFO)
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.breakout.com.pk/"
    result = crawl_website(test_url)
    if result.success:
        print(f"Crawled {len(result.html)} characters from {test_url}")
    else:
        print(f"Crawl failed: {result.error}")