"""
POST /api/chat — the main conversational endpoint.

Rehydrates ConversationState from the DB (per-user profile + latest
qualification round), merges in whatever the frontend sent this turn,
invokes the LangGraph app, and — per the note in agents/graph.py — if
Qualification just became ready within this same request, immediately
re-invokes once more so the user gets their recommendation without an
extra round trip, instead of needing to send a second, empty message.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from database.crud import (
    get_user_by_session,
    get_latest_preference,
    get_pending_item_types,
)
from agents.graph import app_graph
from agents.state import ConversationState
from api.schemas import ChatRequest, ChatResponse

router = APIRouter()

# Safety cap on automatic re-invocations within one HTTP request, in case
# of an unexpected state combination — prevents any possibility of a
# runaway loop.
MAX_AUTO_ADVANCES = 2


@router.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    user = get_user_by_session(db, request.session_id)
    if not user:
        raise HTTPException(
            status_code=400,
            detail="No profile found for this session — call /api/profile first.",
        )

    # Fall back to the latest (possibly not-yet-ready) preference round for
    # any field the frontend didn't send this turn, so multi-turn answers
    # (category now, measurements later) aren't lost between requests.
    latest_pref = None if request.new_request else get_latest_preference(db, user.id)

    def _pick(request_value, fallback_attr):
        if request_value is not None:
            return request_value
        return getattr(latest_pref, fallback_attr, None) if latest_pref else None

    # Handle item_types: check request, then preference, then pending on User
    item_types_raw = request.item_types
    if not item_types_raw and latest_pref and latest_pref.item_types:
        item_types_raw = latest_pref.item_types
    if not item_types_raw:
        pending = get_pending_item_types(db, user)
        item_types_raw = pending

    item_types_list = (
        [t.strip() for t in item_types_raw.split(",") if t.strip()]
        if item_types_raw
        else None
    )

    state: ConversationState = {
        "session_id": user.session_id,
        "user_id": user.id,
        "website_id": request.website_id,
        "name": user.name,
        "phone": user.phone,
        "gender": user.gender.value,
        "category": _pick(request.category, "category"),
        "item_types": item_types_list,
        "age": _pick(request.age, "age"),
        "height_cm": _pick(request.height_cm, "height_cm"),
        "weight_kg": _pick(request.weight_kg, "weight_kg"),
        "waist_in": _pick(request.waist_in, "waist_in"),
        "budget": _pick(request.budget, "budget"),
        "is_ready": False,
        "new_request": request.new_request,
        "user_message": request.message,
        "reply": None,
        "stage": "START",
        "errors": [],
    }
    # Normalize category enum values that may have come back as an Enum
    # object from the fallback (SQLAlchemy Enum columns deserialize as the
    # Python Enum, not a plain string).
    if state.get("category") is not None and hasattr(state["category"], "value"):
        state["category"] = state["category"].value

    result = app_graph.invoke(state)

    advances = 0
    while result.get("is_ready") and not result.get("reply") and advances < MAX_AUTO_ADVANCES:
        result = app_graph.invoke(result)
        advances += 1

    item_types_result = result.get("item_types")
    item_types_str = ",".join(item_types_result) if item_types_result else None

    return ChatResponse(
        reply=result.get("reply"),
        stage=result.get("stage", "UNKNOWN"),
        is_ready=result.get("is_ready", False),
        shirt_size=result.get("shirt_size"),
        pant_size=result.get("pant_size"),
        item_types=item_types_str,
    )
