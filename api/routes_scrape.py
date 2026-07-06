"""POST /api/scrape — scrapes a clothing website URL and stores its products."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from database.crud import get_or_create_website, save_cleaned_products
from scraping.scraper import scrape_website
from scraping.cleaner import clean_products
from api.schemas import ScrapeRequest, ScrapeResponse
from config import settings

router = APIRouter()


@router.post("/api/scrape", response_model=ScrapeResponse)
def scrape(request: ScrapeRequest, db: Session = Depends(get_db)):
    result = scrape_website(
        request.url,
        wait_seconds=settings.SCRAPE_WAIT_SECONDS,
        scroll_passes=settings.SCRAPE_SCROLL_PASSES,
    )
    if not result.success:
        raise HTTPException(status_code=502, detail=f"Failed to scrape site: {result.error}")

    products = clean_products(result.html, source_url=request.url)
    if not products:
        raise HTTPException(
            status_code=422,
            detail="Scraped the page but couldn't detect any products on it. "
                   "The site's layout may not be supported yet.",
        )

    website = get_or_create_website(db, request.url)
    count = save_cleaned_products(db, website.id, products)

    return ScrapeResponse(
        website_id=website.id,
        products_scraped=count,
        message=f"Indexed {count} products from {website.domain_name}.",
    )
