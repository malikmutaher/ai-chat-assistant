"""
FastAPI app entrypoint.

Run with:
    uvicorn main:app --reload

Then point shopping_assistant_frontend.html's BACKEND_URL at this server
(default http://localhost:8000) and uncomment the real fetch() calls in
its <script> block.
"""

from pathlib import Path 
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
    allow_credentials=True,
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

# Serve frontend static files (must be last so API routes take priority)
BASE_DIR = Path(__file__).parent
app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="static")

logger.info(f"[STARTUP] Static files mounted from: {BASE_DIR}")


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
