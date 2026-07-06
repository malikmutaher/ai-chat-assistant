"""
Orchestration Agent.

Per our design discussion: a lightweight deterministic ROUTER rather than
an LLM-reasoning node, since llama3.2's tool-calling/routing judgment was
flagged as unreliable for small local models. It reads state and decides
which sub-agent (tool) to invoke next — Qualification or Recommendation —
treating them as callable tools rather than letting them hand off to each
other directly.
"""

from agents.state import ConversationState


def orchestrator_node(state: ConversationState) -> dict:
    """Pass-through node — exists so the graph has a single, visible entry
    point before routing. Doesn't mutate state itself; `route_conversation`
    (used as the conditional edge function) makes the actual decision."""
    return {}


def route_conversation(state: ConversationState) -> str:
    """
    Returns the name of the next node: "qualification", "recommendation",
    or "end".

    Rules (checked in order):
      1. An explicit new_request flag (set when the user asks for a
         different category/budget after already getting a recommendation)
         always sends the conversation back to Qualification.
      2. If the Qualification Agent hasn't marked this round ready, stay
         in Qualification (covers the multi-turn case: category asked,
         then measurements asked, before enough info exists).
      3. If ready but no reply has been generated yet this turn, move to
         Recommendation.
      4. Otherwise, the turn is complete — end.
    """
    if state.get("new_request"):
        return "qualification"

    if not state.get("is_ready"):
        return "qualification"

    if state.get("is_ready") and not state.get("reply"):
        return "recommendation"

    return "end"
