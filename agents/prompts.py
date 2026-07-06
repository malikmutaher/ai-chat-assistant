"""
All prompt templates, kept in one place so they're easy to tune without
touching agent logic. Every prompt that needs a structured decision (not
just prose) asks for JSON explicitly and the calling node parses it
defensively (see agents/qualification_agent.py).
"""

# ---------------------------------------------------------------------------
# Qualification Agent — readiness judgment
# ---------------------------------------------------------------------------

READINESS_PROMPT = """You are checking whether a shopping assistant has enough information to make a clothing recommendation.

Known information:
- Category: {category}
- Age: {age}
- Height (cm): {height_cm}
- Weight (kg): {weight_kg}
- Waist (in): {waist_in}
- Budget: {budget}

First, briefly state what is present and what is missing.
Then, on a new line, output ONLY a JSON object in this exact format and nothing else:
{{"ready": true or false, "missing": ["field1", "field2"]}}

A recommendation can proceed once category, and enough measurements to compute a size (height, weight, waist), and a budget are all present. Age is optional.
"""

# ---------------------------------------------------------------------------
# Qualification Agent — detecting a mid-conversation change request
# ---------------------------------------------------------------------------

INTENT_CHANGE_PROMPT = """A user is talking to a clothing shopping assistant after already receiving a recommendation.

Their message: "{message}"

Does this message indicate they want something different (a new category, a different budget, or another outfit), as opposed to just a general comment or thank-you?

Output ONLY a JSON object in this exact format and nothing else:
{{"new_request": true or false, "updated_category": "category name or null", "updated_budget": number or null}}
"""

# ---------------------------------------------------------------------------
# Recommendation Agent — formatting the final answer
#
# NOTE: the item lines (name/price/size) and total are assembled in plain
# Python code in agents/recommendation_agent.py, NOT by the LLM — this
# guarantees prices/names are never altered or invented. The LLM is only
# asked for the short "why this fits" reasoning line below, using the
# already-confirmed selection as its only input.
# ---------------------------------------------------------------------------

REASON_PROMPT = """You are an AI Men's Fashion Shopping Assistant. The system has already selected these items for the user — do not suggest changing them or mention any other products:

Category: {category}
Budget: {budget}
Selected items: {selected_summary}
Missing items: {missing_summary}

In 1-2 short sentences, explain why this selection fits the user's category, size, and budget. If something is missing, briefly acknowledge it. Do not repeat the item list or prices, just give the reasoning.
"""

RECOMMENDATION_PROMPT = """(Legacy/reference only — see REASON_PROMPT. Kept here in case you want the LLM to
own full formatting again later; not used by recommendation_agent.py as written.)

You are an AI Men's Fashion Shopping Assistant.
Category: {category}
Budget: {budget}
Selected items:
{selected_items}
Missing items:
{missing_items}
Total price: {total_price}
"""
