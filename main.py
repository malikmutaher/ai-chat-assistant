"""
FastAPI app entrypoint.

Run with:
    uvicorn main:app --reload

Then point shopping_assistant_frontend.html's BACKEND_URL at this server
(default http://localhost:8000) and uncomment the real fetch() calls in
its <script> block.
"""

from pathlib import Path 

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database.db import init_db
from api.routes_scrape import router as scrape_router
from api.routes_profile import router as profile_router
from api.routes_chat import router as chat_router

app = FastAPI(title="AI Shopping Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ALLOW_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scrape_router)
app.include_router(profile_router)
app.include_router(chat_router)

# Serve frontend static files (must be last so API routes take priority)
BASE_DIR = Path(__file__).parent
app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="static")


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
