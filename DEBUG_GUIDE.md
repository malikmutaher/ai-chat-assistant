# AI Shopping Assistant - Comprehensive Debug Guide

## Overview
This document explains all the improvements made to fix the 500 error and add comprehensive debugging to the backend.

---

## Problems Solved

### 1. **500 Internal Server Error on POST /api/scrape**
- **Root Cause**: Unhandled exceptions in scraping pipeline without proper error logging
- **Fix**: Added try/except blocks with detailed logging at every step

### 2. **No Error Visibility**
- **Root Cause**: FastAPI HTTPException hides actual errors from frontend
- **Fix**: Now returns JSON error responses with full traceback and step information

### 3. **Missing Dependency Imports**
- **Root Cause**: `webdriver_manager` wasn't installed
- **Fix**: Installed `webdriver-manager` and updated imports in `scraper.py`

### 4. **No Logging at All**
- **Root Cause**: No logging configuration anywhere
- **Fix**: Added comprehensive logging to every module with detailed step tracking

---

## Improvements Made

### 1. **routes_scrape.py** - Complete Rewrite
✅ Added 5-step request flow tracking:
- Step 1: URL validation
- Step 2: Website scraping
- Step 3: HTML product cleaning
- Step 4: Database website record creation
- Step 5: Product save to database

✅ Each step has:
- `logger.info()` for major milestones
- `logger.debug()` for detailed state info
- `logger.error()` for failures
- Full traceback on exceptions

✅ Returns JSON errors instead of crashing:
```json
{
  "success": false,
  "error": "Description of what failed",
  "step": "which_step_failed",
  "url": "the_url_being_processed",
  "traceback": "full_python_traceback"
}
```

### 2. **scraper.py** - Enhanced ChromeDriver & Selenium
✅ `_build_driver()`:
- Logs ChromeDriver initialization
- Logs webdriver-manager path resolution
- Catches driver creation errors with details

✅ `scrape_website()`:
- Logs every scroll pass
- Logs browser timeout handling
- Logs page source extraction
- Handles WebDriver exceptions gracefully
- Ensures driver.quit() even on error
- Catches and logs all exceptions

✅ `crawl_website()`:
- Logs sitemap discovery
- Tracks pages crawled vs max_pages
- Logs link extraction
- Logs total bytes and pages at completion

### 3. **cleaner.py** - BeautifulSoup Error Handling
✅ `clean_products()`:
- Logs HTML parsing
- Logs product card discovery
- Tracks cards with prices vs skipped
- Logs individual product extraction with price
- Catches errors per-card without failing entire batch

### 4. **main.py** - Application Startup Logging
✅ Added logging initialization:
- Logs startup banner with visual separator
- Logs CORS configuration
- Logs router registration
- Logs database initialization
- Logs full startup sequence with timestamps

---

## How to Debug

### Option 1: View Terminal Output
When the backend is running, all logs print to the terminal:

```
2026-07-14 17:08:05,976 - main - INFO - [STARTUP] FastAPI app created
2026-07-14 17:08:05,977 - api.routes_scrape - INFO - [SCRAPE_START] URL: https://www.breakout.com.pk/
2026-07-14 17:08:05,978 - scraping.scraper - INFO - [SCRAPE_WEBSITE] Starting scrape
...
```

### Option 2: Use Frontend Error Response
When scraping fails, the frontend now receives detailed error info:

```javascript
{
  "success": false,
  "error": "WebDriver error: ...",
  "error_type": "ChromeDriverException",
  "step": "scraping",
  "url": "https://www.breakout.com.pk/",
  "traceback": "Full Python traceback here..."
}
```

### Option 3: Test Endpoint Directly
```bash
# Test with curl
curl -X POST http://localhost:8000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.breakout.com.pk/"}'

# Or use Python
import requests
response = requests.post(
    "http://localhost:8000/api/scrape",
    json={"url": "https://www.breakout.com.pk/"}
)
print(response.json())
```

---

## Log Levels & Prefixes

### DEBUG (Detailed Info)
Prefix: `[DEBUG_INFO]`, `[DRIVER_BUILD]`, etc.
- ChromeDriver path
- Page load configuration
- Scroll pass details
- HTML parsing steps

### INFO (Important Milestones)
Prefix: `[STARTUP]`, `[SCRAPE_START]`, `[SCRAPE_WEBSITE]`, etc.
- Backend startup
- Request started/completed
- Database operations
- Scraping progress

### WARNING (Recoverable Errors)
Prefix: `[WARNING]`
- Page load timeout (attempts partial HTML)
- Sitemap discovery failed (non-critical)
- Card processing errors (continues with others)

### ERROR (Critical Failures)
Prefix: `[ERROR]`
- WebDriver crashes
- Database errors
- HTML parsing failures
- Unexpected exceptions

---

## Checking 

### 1. Is Ollama Running?
```bash
curl http://localhost:11434/api/tags
```
If it fails, the LLM recommendation agent won't work, but scraping will.

### 2. Is Database OK?
Check terminal for:
```
[STARTUP] Database initialized successfully
```

### 3. Is ChromeDriver Installed?
Check terminal for:
```
[DRIVER_BUILD] ChromeDriver path: C:\...\.wdm\...
[DRIVER_BUILD] WebDriver initialized successfully
```

### 4. Is CORS Working?
The response should NOT include CORS errors anymore.

### 5. Is Scraping Working?
Terminal should show:
```
[SCRAPE_WEBSITE] Starting scrape
[SCRAPE_WEBSITE] Building WebDriver...
[SCRAPE_WEBSITE] Navigating to: https://www.breakout.com.pk/
[SCRAPE_WEBSITE] Waiting for <body> element...
[SCRAPE_WEBSITE] Beginning initial 3 scroll passes...
[SCRAPE_WEBSITE] Page source extracted: 2345678 bytes
[SCRAPE_WEBSITE] Success: Scraped 2345678 bytes
```

---

## Common Error Messages & Fixes

### Error: "No module named 'webdriver_manager'"
**Fix**: Run in the virtual environment:
```bash
.\.venv\Scripts\Activate.ps1
pip install webdriver-manager
```

### Error: "ChromeDriver path not found"
**Fix**: webdriver-manager will auto-download. Check for firewall blocks or network issues.

### Error: "Page load timed out"
**This is OK!** The scraper will use partial HTML. Check for Cloudflare or slow network.

### Error: "No products detected"
**This is expected!** The site's HTML structure may not match our heuristics. Check terminal logs to see what was found.

### Error: "Database error"
Check terminal for specific SQLAlchemy error. Likely a schema issue.

---

## Testing the Full Flow

### Step 1: Ensure Backend is Running
```bash
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload
```

### Step 2: Refresh Frontend
Open browser and navigate to `http://localhost:8000`

### Step 3: Submit a URL
Enter: `https://www.breakout.com.pk/`

### Step 4: Check Terminal Output
Look for:
- `[SCRAPE_START]` - Request received
- `[SCRAPE_WEBSITE]` - Scraping started
- `[CLEAN_PRODUCTS]` - Products extracted
- `[SCRAPE_SUCCESS]` - Completed successfully

### Step 5: Check Frontend Response
Should show: "Indexed X products from breakout.com.pk"

---

## Performance Monitoring

### Typical Timing
- WebDriver initialization: ~5-10 seconds
- Single page scrape: ~20-30 seconds
- Full site crawl (multi-page): 2-10 minutes depending on site size

### Monitor in Terminal
```
[SCRAPE_WEBSITE] Starting scrape
... (wait for status messages)
[SCRAPE_WEBSITE] Success: Scraped 3456789 bytes from https://www.breakout.com.pk/
```

---

## Configuration

### Scraping Timeout
Edit `config.py`:
```python
SCRAPE_WAIT_SECONDS: int = 20  # Increase if pages load slowly
SCRAPE_SCROLL_PASSES: int = 3  # More passes = slower but more complete
```

### Log Level
Edit `main.py`:
```python
logging.basicConfig(
    level=logging.DEBUG,  # Change to WARNING for less output
    ...
)
```

---

## Files Modified

1. **api/routes_scrape.py** - Complete rewrite with step-by-step error handling
2. **scraping/scraper.py** - Enhanced ChromeDriver initialization and error logging
3. **scraping/cleaner.py** - Added product extraction logging
4. **main.py** - Added startup logging
5. **requirements.txt** - Added webdriver-manager

---

## Next Steps

If scraping still fails:
1. Check terminal logs for specific error step
2. Test the failing step independently
3. Share the full error log from terminal
4. Check if the website has:
   - Cloudflare protection (needs additional handling)
   - JavaScript-heavy rendering (check if products appear in <body>)
   - Rate limiting (may need delays between requests)

---

**✅ Backend is now fully debugged and ready for production testing!**
