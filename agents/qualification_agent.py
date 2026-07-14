"""
Qualification Agent node.

Responsibilities per turn:
  0. Ask for category if not yet given.
  1. Ask for item types (shirt/pant/shoes/...) if category is given but
     item types haven't been selected yet — fetches the actual available
     types from the scraped product catalog and shows them to the user.
  2. If measurements (height/weight/waist) are present, compute shirt/pant
     size via sizing/size_calculator.py (deterministic, not LLM-based).
  3. Persist the current qualification round to the DB (a new
     UserPreference row per round, per the append-only design in
     database/models.py).
  4. Ask the LLM whether enough information exists to proceed to a
     recommendation, with a deterministic safety-net override in case the
     model's JSON is malformed or contradicts the data it was given.
"""

import json
import re
from typing import List, Optional

from langchain_ollama.llms import OllamaLLM

from config import settings
from database.db import SessionLocal
from database.models import Category, ALL_ITEM_TYPES
from database.crud import (
    create_preference,
    update_preference_sizes,
    mark_preference_ready,
    get_available_item_types,
    set_pending_item_types,
    get_pending_item_types,
    clear_pending_item_types,
    get_user_by_session,
)
from agents.state import ConversationState
from agents.prompts import READINESS_PROMPT
from sizing.size_calculator import calculate_size

llm = OllamaLLM(model=settings.OLLAMA_MODEL, base_url=settings.OLLAMA_BASE_URL)


def _parse_json_block(text: str) -> dict:
    """Extracts the first {...} block from an LLM response and parses it.
    Returns {} if nothing valid is found, so callers must handle that case
    rather than assuming the LLM always behaves."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


def _judge_readiness(category, age, height_cm, weight_kg, waist_in, budget) -> bool:
    prompt = READINESS_PROMPT.format(
        category=category or "not provided",
        age=age if age is not None else "not provided",
        height_cm=height_cm if height_cm is not None else "not provided",
        weight_kg=weight_kg if weight_kg is not None else "not provided",
        waist_in=waist_in if waist_in is not None else "not provided",
        budget=budget if budget is not None else "not provided",
    )
    raw = llm.invoke(prompt)
    parsed = _parse_json_block(raw)
    return bool(parsed.get("ready", False))


def _parse_item_types(user_text: str, available: List[str]) -> Optional[List[str]]:
    """
    Given the user's free-text reply (e.g. "shirt, pant and shoes" or
    "shirt, pant") and the list of available types from the DB, returns
    the subset that matched, or None if nothing matched.
    """
    lowered = user_text.lower()
    matched = []
    for t in available:
        if t.lower() in lowered:
            matched.append(t)
    return matched if matched else None


def qualification_node(state: ConversationState) -> dict:
    db = SessionLocal()
    try:
        category_str = state.get("category")
        item_types = state.get("item_types")
        budget = state.get("budget")
        age = state.get("age")
        height_cm = state.get("height_cm")
        weight_kg = state.get("weight_kg")
        waist_in = state.get("waist_in")
        user_message = state.get("user_message")

        # Step 0: Ask for category.
        if not category_str:
            return {
                "is_ready": False,
                "stage": "AWAITING_CATEGORY",
                "reply": "Which category are you shopping for — Casual, Formal, Smart Casual, Sportswear, or Party Wear?",
            }

        try:
            category = Category(category_str)
        except ValueError:
            return {
                "is_ready": False,
                "stage": "AWAITING_CATEGORY",
                "reply": f"I didn't recognize '{category_str}' as a category. Please choose Casual, Formal, Smart Casual, Sportswear, or Party Wear.",
            }

        # Step 1: Ask for item types (what products they want).
        website_id = state.get("website_id")
        available_types = get_available_item_types(db, website_id) if website_id else []

        # Also check pending_item_types on User (survives across turns)
        user = get_user_by_session(db, state["session_id"])
        pending_types_str = get_pending_item_types(db, user) if user else None

        if not item_types and pending_types_str:
            # Restore from DB (leftover from a previous turn)
            item_types = [t.strip() for t in pending_types_str.split(",") if t.strip()]

        if not item_types and available_types:
            # Try to parse from the user's message if they just replied
            if user_message:
                parsed = _parse_item_types(user_message, available_types)
                if parsed:
                    item_types = parsed
                    # Persist so it survives the next turn
                    if user:
                        set_pending_item_types(db, user, ",".join(item_types))

            if not item_types:
                type_list = ", ".join(available_types)
                return {
                    "is_ready": False,
                    "category": category_str,
                    "stage": "AWAITING_ITEM_TYPES",
                    "reply": f"Great! Available product types in this catalog: {type_list}. Which ones would you like? (e.g. 'shirt, pant, shoes')",
                }

        # Step 2: Ask for measurements/budget.
        if not (height_cm and weight_kg and waist_in and budget):
            return {
                "is_ready": False,
                "category": category_str,
                "item_types": item_types,
                "stage": "AWAITING_MEASUREMENTS",
                "reply": "Please share your age, height (cm), weight (kg), waist (inches), and budget so I can find your size.",
            }

        # Step 3: Compute size.
        try:
            size_result = calculate_size(
                height_cm=height_cm, weight_kg=weight_kg, waist_in=waist_in, age=age
            )
        except ValueError:
            return {
                "is_ready": False,
                "stage": "AWAITING_MEASUREMENTS",
                "reply": "Those measurements don't look quite right — could you double check your height, weight, and waist and resend them?",
            }

        # Step 4: Persist.
        item_types_str = ",".join(item_types) if item_types else None
        preference = create_preference(
            db,
            user_id=state["user_id"],
            category=category,
            budget=budget,
            item_types=item_types_str,
            age=age,
            height_cm=height_cm,
            weight_kg=weight_kg,
            waist_in=waist_in,
        )
        update_preference_sizes(db, preference.id, size_result.shirt_size, size_result.pant_size)

        # Clear pending item types now that they're committed
        if user:
            clear_pending_item_types(db, user)

        # Step 5: LLM readiness judgment.
        all_fields_present = all([category_str, budget, size_result.shirt_size, size_result.pant_size])
        try:
            llm_ready = _judge_readiness(category_str, age, height_cm, weight_kg, waist_in, budget)
        except Exception:
            llm_ready = all_fields_present

        is_ready = llm_ready and all_fields_present
        if all_fields_present and not llm_ready:
            is_ready = True

        mark_preference_ready(db, preference.id, ready=is_ready)

        return {
            "category": category_str,
            "item_types": item_types,
            "preference_id": preference.id,
            "shirt_size": size_result.shirt_size,
            "pant_size": size_result.pant_size,
            "is_ready": is_ready,
            "stage": "READY" if is_ready else "AWAITING_MEASUREMENTS",
        }

    finally:
        db.close()
