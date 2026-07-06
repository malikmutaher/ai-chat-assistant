"""
Recommendation Agent node.

Deliberately splits into two parts:
  1. `find_best_combo()` — pure Python, no LLM. Picks the cheapest
     available shirt/pant/shoes combo that fits the budget, dropping the
     single most expensive item if the full combo doesn't fit. This is
     the part that must never hallucinate, so it doesn't touch the LLM.
  2. `recommendation_node()` — wraps (1) with DB access, then asks the LLM
     for ONLY a short reasoning sentence using the already-confirmed
     selection (see agents/prompts.py::REASON_PROMPT for why).
"""

from typing import Dict, List, Optional, Tuple

from langchain_ollama.llms import OllamaLLM

from config import settings
from database.db import SessionLocal
from database.models import Category

from database.crud import filter_products, save_recommendation
from agents.state import ConversationState
from agents.prompts import REASON_PROMPT

llm = OllamaLLM(model=settings.OLLAMA_MODEL, base_url=settings.OLLAMA_BASE_URL)

ITEM_LABELS = {"shirt": "👕 Shirt", "pant": "👖 Pant", "shoes": "👟 Shoes"}


def find_best_combo(
    grouped: Dict[str, List], budget: float
) -> Tuple[Dict[str, Optional[object]], List[str], float, Optional[str]]:
    """
    `grouped` maps item_type -> list of product-like objects (must have
    `.price`), each list already sorted cheapest-first by the caller.

    Returns (selected, missing, total, note):
      - selected: item_type -> chosen product (or None if unavailable)
      - missing: list of item_types with no selection
      - total: sum of selected item prices
      - note: explanation if something was dropped to fit budget, else None
    """
    selected: Dict[str, Optional[object]] = {
        item_type: (products[0] if products else None)
        for item_type, products in grouped.items()
    }
    missing = [item_type for item_type, p in selected.items() if p is None]
    total = sum(p.price for p in selected.values() if p is not None)
    note = None

    if total > budget:
        priced = [(t, p) for t, p in selected.items() if p is not None]
        if priced:
            priciest_type, priciest_item = max(priced, key=lambda tp: tp[1].price)
            reduced_total = total - priciest_item.price
            if reduced_total <= budget:
                note = f"Dropped {priciest_type} (Rs. {priciest_item.price:.0f}) to stay within your budget."
                selected[priciest_type] = None
                missing.append(priciest_type)
                total = reduced_total
            else:
                note = "Even the cheapest available combination is slightly over your budget."

    return selected, missing, total, note


def _format_selected_lines(selected: Dict[str, Optional[object]]) -> str:
    lines = []
    for item_type, label in ITEM_LABELS.items():
        product = selected.get(item_type)
        if product is not None:
            deal = f" [{product.deal_info}]" if getattr(product, "deal_info", None) else ""
            lines.append(f"{label}: {product.name} - Rs. {product.price:.0f}{deal}")
        else:
            lines.append(f"{label}: Not available in your size/budget")
    return "\n".join(lines)


def recommendation_node(state: ConversationState) -> dict:
    db = SessionLocal()
    try:
        category = Category(state["category"])
        budget = state["budget"]

        grouped = filter_products(
            db,
            website_id=state["website_id"],
            category=category,
            shirt_size=state.get("shirt_size"),
            pant_size=state.get("pant_size"),
        )

        selected, missing, total, note = find_best_combo(grouped, budget)

        item_lines = _format_selected_lines(selected)

        selected_summary = ", ".join(
            f"{t}: {p.name} (Rs. {p.price:.0f})" for t, p in selected.items() if p is not None
        ) or "none"
        missing_summary = ", ".join(missing) if missing else "none"

        try:
            reason = llm.invoke(
                REASON_PROMPT.format(
                    category=state["category"],
                    budget=budget,
                    selected_summary=selected_summary,
                    missing_summary=missing_summary,
                )
            ).strip()
        except Exception:
            # LLM unreachable — fall back to a plain templated reason rather
            # than failing the whole recommendation.
            reason = (
                f"These items match your {state['category']} category and fit within Rs. {budget:.0f}."
                if not missing
                else f"Some items were unavailable in your size/budget for {state['category']}."
            )

        reply_parts = [item_lines, f"💰 Total: Rs. {total:.0f}"]
        if note:
            reply_parts.append(f"ℹ️ {note}")
        reply_parts.append(f"📝 Reason: {reason}")
        reply = "\n".join(reply_parts)

        product_ids = [p.id for p in selected.values() if p is not None]
        save_recommendation(
            db,
            user_id=state["user_id"],
            preference_id=state.get("preference_id"),
            product_ids=product_ids,
            generated_text=reply,
            total_price=total,
        )

        return {
            "reply": reply,
            "stage": "RECOMMENDED",
            "new_request": False,
        }

    finally:
        db.close()
