"""
FastAPI app entrypoint.

Run with:
    uvicorn main:app --reload

Then point index.html's BACKEND_URL at this server
(default http://localhost:8000).
"""

from pathlib import Path
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from config import settings
from database.db import init_db
from api.routes_scrape import router as scrape_router
from api.routes_profile import router as profile_router
from api.routes_chat import router as chat_router

# Configure comprehensive logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger(__name__)
logger.info("=" * 80)
logger.info("STARTING AI SHOPPING ASSISTANT BACKEND")
logger.info("=" * 80)

app = FastAPI(title="AI Shopping Assistant API")

logger.info("[STARTUP] FastAPI app created")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ALLOW_ORIGINS),
    allow_credentials=False,  # we don't use cookies; keep this False so a wildcard origin is actually valid
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info(f"[STARTUP] CORS configured - allow_origins: {settings.CORS_ALLOW_ORIGINS}")

app.include_router(scrape_router)
app.include_router(profile_router)
app.include_router(chat_router)

logger.info("[STARTUP] All routers registered")


@app.get("/health")
def health():
    logger.debug("[HEALTH_CHECK] Health check requested")
    return {"status": "ok"}

# Serve ONLY the frontend file — never the whole project directory
# (that used to expose config.py, database/models.py, and the live
# shopping_assistant.db over HTTP).
BASE_DIR = Path(__file__).parent
FRONTEND_FILE = BASE_DIR / "index.html"


@app.get("/")
def serve_frontend():
    return FileResponse(str(FRONTEND_FILE))

logger.info(f"[STARTUP] Frontend will be served from: {FRONTEND_FILE}")


@app.on_event("startup")
def on_startup():
    logger.info("[STARTUP] Application startup event triggered")
    try:
        init_db()
        logger.info("[STARTUP] Database initialized successfully")
    except Exception as e:
        logger.error(f"[STARTUP] Database initialization failed: {str(e)}")
        import traceback
        logger.error(f"[STARTUP] Traceback: {traceback.format_exc()}")
        raise

logger.info("[STARTUP] Application fully initialized and ready to accept requests")
logger.info("=" * 80)