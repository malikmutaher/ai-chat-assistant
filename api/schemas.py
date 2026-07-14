"""Pydantic request/response models for the FastAPI routes."""

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# POST /api/scrape
# ---------------------------------------------------------------------------

class ScrapeRequest(BaseModel):
    url: str


class ScrapeResponse(BaseModel):
    website_id: int
    products_scraped: int
    message: str


# ---------------------------------------------------------------------------
# POST /api/profile
# ---------------------------------------------------------------------------

class ProfileRequest(BaseModel):
    session_id: str
    name: str
    gender: str  # "Men" | "Women"
    phone: Optional[str] = None


class ProfileResponse(BaseModel):
    user_id: int
    message: str


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    # website_id is returned by /api/scrape; the frontend holds onto it
    # (alongside sessionId) and includes it on every /api/chat call so the
    # Recommendation Agent knows which site's products to filter.
    website_id: int

    message: Optional[str] = None  # free-text follow-up, if any

    category: Optional[str] = None
    # Comma-separated item types (e.g. "shirt,pant,shoes") the user wants.
    item_types: Optional[str] = None
    age: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    waist_in: Optional[float] = None
    budget: Optional[float] = None

    # Set by the frontend when the user explicitly asks for something
    # different after already getting a recommendation.
    new_request: bool = False


class ChatResponse(BaseModel):
    reply: Optional[str] = None
    stage: str
    is_ready: bool
    shirt_size: Optional[str] = None
    pant_size: Optional[str] = None
    item_types: Optional[str] = None
