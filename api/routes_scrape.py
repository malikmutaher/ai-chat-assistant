"""POST /api/scrape — scrapes a clothing website URL and stores its products."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import logging
import traceback
import sys

from database.db import get_db
from database.crud import get_or_create_website, save_cleaned_products
from scraping.scraper import crawl_website
from scraping.cleaner import clean_products
from api.schemas import ScrapeRequest, ScrapeResponse
from config import settings

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/scrape")
async def scrape(request: ScrapeRequest, db: Session = Depends(get_db)):
    """
    Comprehensive debug endpoint for scraping.
    Returns detailed error information instead of crashing.
    """
    logger.info(f"[SCRAPE_START] URL: {request.url}")
    
    try:
        # Step 1: Validate URL
        logger.debug(f"[STEP 1] Validating URL: {request.url}")
        if not request.url or not isinstance(request.url, str):
            logger.error("[VALIDATION] Invalid URL type or empty URL")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "URL must be a non-empty string",
                    "step": "validation"
                }
            )
        
        # Step 2: Scrape the website
        logger.debug(f"[STEP 2] Starting crawl_website for: {request.url}")
        logger.debug(f"[CONFIG] SCRAPE_WAIT_SECONDS={settings.SCRAPE_WAIT_SECONDS}, SCRAPE_SCROLL_PASSES={settings.SCRAPE_SCROLL_PASSES}")
        
        result = crawl_website(
            request.url,
            wait_seconds=settings.SCRAPE_WAIT_SECONDS,
            scroll_passes=settings.SCRAPE_SCROLL_PASSES,
            max_pages=100,
        )
        
        logger.debug(f"[STEP 2] Crawl result - success: {result.success}, html_length: {len(result.html) if result.html else 0}")
        
        if not result.success:
            logger.error(f"[SCRAPE_FAILED] Error: {result.error}")
            return JSONResponse(
                status_code=502,
                content={
                    "success": False,
                    "error": f"Failed to crawl site: {result.error}",
                    "step": "scraping",
                    "url": request.url
                }
            )
        
        # Step 3: Clean products
        logger.debug(f"[STEP 3] Cleaning products from HTML")
        try:
            products = clean_products(result.html, source_url=request.url)
            logger.debug(f"[STEP 3] Found {len(products)} products")
        except Exception as e:
            logger.error(f"[CLEAN_ERROR] Failed to clean products: {str(e)}")
            logger.error(traceback.format_exc())
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"Failed to parse product data: {str(e)}",
                    "step": "cleaning",
                    "url": request.url,
                    "traceback": traceback.format_exc()
                }
            )
        
        if not products:
            logger.warning(f"[NO_PRODUCTS] No products found on {request.url}")
            return JSONResponse(
                status_code=422,
                content={
                    "success": False,
                    "error": "Crawled the site but couldn't detect any products. The site's layout may not be supported yet.",
                    "step": "product_detection",
                    "url": request.url
                }
            )
        
        # Step 4: Get or create website record
        logger.debug(f"[STEP 4] Getting or creating website record")
        try:
            website = get_or_create_website(db, request.url)
            logger.debug(f"[STEP 4] Website ID: {website.id}, domain: {website.domain_name}")
        except Exception as e:
            logger.error(f"[DB_ERROR] Failed to create website record: {str(e)}")
            logger.error(traceback.format_exc())
            db.rollback()
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"Database error: {str(e)}",
                    "step": "website_creation",
                    "url": request.url,
                    "traceback": traceback.format_exc()
                }
            )
        
        # Step 5: Save cleaned products
        logger.debug(f"[STEP 5] Saving {len(products)} products to database")
        try:
            count = save_cleaned_products(db, website.id, products)
            logger.info(f"[STEP 5] Successfully saved {count} products")
        except Exception as e:
            logger.error(f"[DB_SAVE_ERROR] Failed to save products: {str(e)}")
            logger.error(traceback.format_exc())
            db.rollback()
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"Failed to save products to database: {str(e)}",
                    "step": "product_save",
                    "url": request.url,
                    "traceback": traceback.format_exc()
                }
            )
        
        # Success
        message = f"Indexed {count} products from {website.domain_name}."
        logger.info(f"[SCRAPE_SUCCESS] {message}")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "website_id": website.id,
                "products_scraped": count,
                "message": message,
                "domain": website.domain_name
            }
        )
        
    except Exception as e:
        logger.error(f"[UNEXPECTED_ERROR] Unhandled exception: {str(e)}")
        logger.error(traceback.format_exc())
        logger.error(f"[DEBUG_INFO] Exception type: {type(e).__name__}")
        logger.error(f"[DEBUG_INFO] Exception args: {e.args}")
        
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "error_type": type(e).__name__,
                "step": "unknown",
                "url": request.url if 'request' in locals() else None,
                "traceback": traceback.format_exc()
            }
        )