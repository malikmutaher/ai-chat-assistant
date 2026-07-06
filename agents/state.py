"""
Shared state passed between LangGraph nodes.

Rehydrated from the DB at the start of every /api/chat call (see
api/routes_chat.py) rather than kept in server memory, so a user can
resume a conversation across requests/restarts. Each node reads what it
needs from this dict and returns a partial update, which LangGraph merges
back in.
"""

from typing import List, Optional, TypedDict


class ConversationState(TypedDict, total=False):
    # Identity
    session_id: str
    user_id: int
    website_id: int

    # Profile (collected once, rarely changes)
    name: str
    phone: Optional[str]
    gender: str  # "Men" | "Women"

    # Current qualification round
    preference_id: Optional[int]
    category: Optional[str]
    age: Optional[int]
    height_cm: Optional[float]
    weight_kg: Optional[float]
    waist_in: Optional[float]
    budget: Optional[float]

    # Computed by sizing/size_calculator.py
    shirt_size: Optional[str]
    pant_size: Optional[str]

    # Control flow
    is_ready: bool          # Qualification Agent's readiness signal
    new_request: bool       # set when the user wants to change category/budget mid-conversation
    stage: str              # human-readable current stage, echoed back to the frontend

    # Turn input/output
    user_message: Optional[str]   # raw free text from the user this turn, if any
    reply: Optional[str]          # assistant's reply for this turn

    # Internal notes (e.g. sizing validation warnings), not shown to user directly
    errors: List[str]
