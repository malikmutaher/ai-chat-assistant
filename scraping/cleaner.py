"""
Cleans raw scraped HTML into structured product rows matching
database/models.py::Product.

Replaces the RecursiveCharacterTextSplitter + vector-store step from the
original RAG prototype. Instead of chunking text for embedding, this module
extracts discrete product records (name, price, size, color, category,
item_type, deal info) directly, so recommendation can run as a plain SQL
filter rather than a similarity search.

IMPORTANT — this is heuristic, not site-specific:
Every storefront lays out product cards differently, so this uses generic
signals (price patterns, nearby headings/images, keyword matching) rather
than hardcoded CSS selectors for one site. It will not be perfect on every
domain. Treat CATEGORY_KEYWORDS / ITEM_TYPE_KEYWORDS / COLOR_KEYWORDS below
as the first thing to tune once you inspect real scraped HTML (e.g. from
breakout.com.pk) — add site-specific selectors there if the generic pass
misses too much.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

from database.models import Category


# ---------------------------------------------------------------------------
# Heuristic keyword tables — extend these as you see real product names
# ---------------------------------------------------------------------------

PRICE_PATTERN = re.compile(r"(?:Rs\.?|PKR)\s?[\d,]{3,}", re.IGNORECASE)
DEAL_PATTERN = re.compile(r"(\d{1,3}\s?%\s?off|sale|discount)", re.IGNORECASE)
SIZE_TOKEN_PATTERN = re.compile(
    r"\b(XXS|XS|S|M|L|XL|XXL|XXXL|28|30|32|34|36|38|40|42|44)\b"
)

CATEGORY_KEYWORDS = {
    Category.FORMAL: ["formal", "dress shirt", "blazer", "suit", "tuxedo"],
    Category.CASUAL: ["casual", "tee", "t-shirt", "denim", "hoodie"],
    Category.SMART_CASUAL: ["smart casual", "chinos", "polo"],
    Category.SPORTSWEAR: ["sport", "activewear", "gym", "track", "jogger", "athletic"],
    Category.PARTY_WEAR: ["party", "sequin", "evening"],
}

ITEM_TYPE_KEYWORDS = {
    "shirt": ["shirt", "polo", "tee", "t-shirt", "kurta"],
    "pant": ["pant", "trouser", "chino", "jean", "denim", "bottom"],
    "shoes": ["shoe", "sneaker", "loafer", "boot", "sandal"],
}

COLOR_KEYWORDS = [
    "black", "white", "navy", "blue", "red", "green", "grey", "gray",
    "brown", "beige", "maroon", "olive", "khaki", "pink", "purple",
    "yellow", "orange", "cream", "tan",
]


@dataclass
class CleanedProduct:
    name: str
    price: float
    category: Category
    item_type: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    deal_info: Optional[str] = None
    source_url: Optional[str] = None


def _parse_price(text: str) -> Optional[float]:
    match = PRICE_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group())
    return float(digits) if digits else None


def _guess_category(text: str) -> Optional[Category]:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return category
    return None


def _guess_item_type(text: str) -> Optional[str]:
    lowered = text.lower()
    for item_type, keywords in ITEM_TYPE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return item_type
    return None


def _guess_color(text: str) -> Optional[str]:
    lowered = text.lower()
    for color in COLOR_KEYWORDS:
        if color in lowered:
            return color
    return None


def _guess_size(text: str) -> Optional[str]:
    match = SIZE_TOKEN_PATTERN.search(text)
    return match.group(1) if match else None


def _guess_name(card: Tag, fallback_text: str) -> str:
    heading = card.find(["h1", "h2", "h3", "h4", "h5"])
    if heading and heading.get_text(strip=True):
        return heading.get_text(strip=True)

    img = card.find("img", alt=True)
    if img and img["alt"].strip():
        return img["alt"].strip()

    # Fallback: first reasonably short line of text in the card.
    for line in fallback_text.splitlines():
        line = line.strip()
        if 3 <= len(line) <= 80:
            return line
    return fallback_text[:80].strip() or "Unnamed product"


def _find_product_cards(soup: BeautifulSoup) -> List[Tag]:
    """
    Finds candidate "product card" elements using two strategies, since a
    single depth-limited walk misses cards on themes with deep nesting:

    1. Price-anchored walk: starting from the price's text node, walk up
       until we hit an element that also contains an image or heading (a
       decent signal it's a whole product card rather than just a stray
       price string).
    2. Shopify-link anchored walk: many storefronts (very common for
       Pakistani clothing sites) are built on Shopify, where every product
       card contains an <a href="/products/..."> link. Themes with deeply
       nested markup (e.g. "Kalles") can put the shared price+image
       ancestor more than a few levels above the price text, so this
       second pass anchors on the product link instead and walks up to
       find a container that also has a price nearby. This catches cards
       the price-only walk misses.

    Cards found by either strategy are merged and deduplicated by element
    identity.
    """
    cards: List[Tag] = []
    seen: set = set()
    MAX_DEPTH = 8

    # Strategy 1: walk up from price text nodes.
    for text_node in soup.find_all(string=PRICE_PATTERN):
        el = text_node.parent
        depth = 0
        while el is not None and depth < MAX_DEPTH:
            if el.find(["img", "h1", "h2", "h3", "h4", "h5"]) is not None:
                if id(el) not in seen:
                    seen.add(id(el))
                    cards.append(el)
                break
            el = el.parent
            depth += 1

    # Strategy 2: walk up from Shopify "/products/<handle>" links.
    for link in soup.find_all("a", href=True):
        if "/products/" not in link["href"]:
            continue
        el = link.parent
        depth = 0
        while el is not None and depth < MAX_DEPTH:
            if el.find(string=PRICE_PATTERN) is not None:
                if id(el) not in seen:
                    seen.add(id(el))
                    cards.append(el)
                break
            el = el.parent
            depth += 1

    return cards


def clean_products(html: str, source_url: Optional[str] = None) -> List[CleanedProduct]:
    """
    Main entry point. Parses raw HTML (from scraping/scraper.py) into a
    deduplicated list of CleanedProduct records ready to insert as
    database/models.py::Product rows.

    Products with no detectable price or category are skipped — the DB
    schema requires both (price is NOT NULL, category is NOT NULL), and a
    row we can't confidently classify would just pollute recommendations.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = _find_product_cards(soup)

    results: List[CleanedProduct] = []
    dedup_keys = set()

    for card in cards:
        text = card.get_text(separator="\n", strip=True)

        price = _parse_price(text)
        if price is None:
            continue

        category = _guess_category(text)
        if category is None:
            # Can't confidently bucket this into one of our five categories —
            # skip rather than guess wrong and mislead the Recommendation Agent.
            continue

        name = _guess_name(card, text)
        dedup_key = (name.lower(), price)
        if dedup_key in dedup_keys:
            continue
        dedup_keys.add(dedup_key)

        deal_match = DEAL_PATTERN.search(text)

        results.append(
            CleanedProduct(
                name=name,
                price=price,
                category=category,
                item_type=_guess_item_type(text),
                size=_guess_size(text),
                color=_guess_color(text),
                deal_info=deal_match.group(0) if deal_match else None,
                source_url=source_url,
            )
        )

    return results


if __name__ == "__main__":
    # Quick manual test against a small synthetic product listing, since we
    # can't hit a live site from this environment. Run: python cleaner.py
    sample_html = """
    <html><body>
      <div class="product-card">
        <img src="shirt1.jpg" alt="Slim Fit Formal Shirt - Navy">
        <h3>Slim Fit Formal Shirt</h3>
        <p>Size: M</p>
        <p>Color: Navy</p>
        <span class="price">Rs. 4,500</span>
        <span class="badge">20% off</span>
      </div>
      <div class="product-card">
        <img src="pant1.jpg" alt="Chino Trouser - Beige">
        <h3>Casual Chino Trouser</h3>
        <p>Waist: 32</p>
        <span class="price">Rs. 3,200</span>
      </div>
      <div class="unrelated">Free shipping on orders over Rs. 5,000</div>
    </body></html>
    """
    for product in clean_products(sample_html, source_url="https://example.com"):
        print(product)