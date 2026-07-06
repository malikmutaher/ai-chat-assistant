"""
Qualification Agent node.

Responsibilities per turn:
  1. If measurements (height/weight/waist) are present, compute shirt/pant
     size via sizing/size_calculator.py (deterministic, not LLM-based).
  2. Persist the current qualification round to the DB (a new
     UserPreference row per round, per the append-only design in
     database/models.py).
  3. Ask the LLM whether enough information exists to proceed to a
     recommendation, with a deterministic safety-net override in case the
     model's JSON is malformed or contradicts the data it was given.

Assumes the frontend resends the full set of currently-known fields
(category, age, height, weight, waist, budget) together in the same
/api/chat call that submits the measurement form — matching how
shopping_assistant_frontend.html already collects them together in
`submitMeasurements()` before making a single request.
"""

import json
import re

from langchain_ollama.llms import OllamaLLM

from config import settings
from database.db import SessionLocal
from database.models import Category
from database.crud import create_preference, update_preference_sizes, mark_preference_ready
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


def qualification_node(state: ConversationState) -> dict:
    db = SessionLocal()
    try:
        category_str = state.get("category")
        budget = state.get("budget")
        age = state.get("age")
        height_cm = state.get("height_cm")
        weight_kg = state.get("weight_kg")
        waist_in = state.get("waist_in")

        # Not enough to even attempt qualification yet — ask for category.
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

        # Have category but not measurements/budget yet.
        if not (height_cm and weight_kg and waist_in and budget):
            return {
                "is_ready": False,
                "category": category_str,
                "stage": "AWAITING_MEASUREMENTS",
                "reply": "Great choice! Please share your age, height (cm), weight (kg), waist (inches), and budget so I can find your size.",
            }

        # Compute size — deterministic, not an LLM call.
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

        # Persist this qualification round.
        preference = create_preference(
            db,
            user_id=state["user_id"],
            category=category,
            budget=budget,
            age=age,
            height_cm=height_cm,
            weight_kg=weight_kg,
            waist_in=waist_in,
        )
        update_preference_sizes(db, preference.id, size_result.shirt_size, size_result.pant_size)

        # LLM readiness judgment, with a deterministic safety net: if we
        # already have everything required, we don't let a flaky/empty LLM
        # response block progress; if the LLM says ready but something
        # required is actually missing, we don't trust it either.
        all_fields_present = all([category_str, budget, size_result.shirt_size, size_result.pant_size])
        try:
            llm_ready = _judge_readiness(category_str, age, height_cm, weight_kg, waist_in, budget)
        except Exception:
            llm_ready = all_fields_present  # LLM unreachable — fall back to the deterministic check

        is_ready = llm_ready and all_fields_present
        if all_fields_present and not llm_ready:
            # We have everything needed; don't let an overly-cautious LLM
            # response stall a user who already gave complete information.
            is_ready = True

        mark_preference_ready(db, preference.id, ready=is_ready)

        return {
            "category": category_str,
            "preference_id": preference.id,
            "shirt_size": size_result.shirt_size,
            "pant_size": size_result.pant_size,
            "is_ready": is_ready,
            "stage": "READY" if is_ready else "AWAITING_MEASUREMENTS",
        }

    finally:
        db.close()
