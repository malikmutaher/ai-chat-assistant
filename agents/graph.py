"""
Builds the LangGraph StateGraph.

Design note on cycles: earlier in the design discussion we talked about
LangGraph's native support for cyclic graphs handling the "user changes
their mind" loop. In practice here, that loop happens ACROSS separate
/api/chat calls (each one rehydrates state from the DB and re-invokes the
graph from the Orchestrator), rather than as an internal cycle within a
single graph.invoke(). That keeps each invocation to at most one
sub-agent call per turn — simpler and safer for a stateless HTTP API,
while still giving the same conversational effect: the DB-persisted
`is_ready` / `new_request` flags are what make the "graph" cyclic across
turns.

    Turn 1: orchestrator -> qualification (asks for category)      -> END
    Turn 2: orchestrator -> qualification (asks for measurements)  -> END
    Turn 3: orchestrator -> qualification (ready!)  -> orchestrator would
            route to recommendation on the NEXT invocation, OR (see
            routes_chat.py) we immediately re-invoke once more in the same
            HTTP request so the user gets the recommendation without an
            extra round trip. See api/routes_chat.py for that one-retry.
"""

from langgraph.graph import StateGraph, END

from agents.state import ConversationState
from agents.orchestrator import orchestrator_node, route_conversation
from agents.qualification_agent import qualification_node
from agents.recommendation_agent import recommendation_node


def build_graph():
    graph = StateGraph(ConversationState)

    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("qualification", qualification_node)
    graph.add_node("recommendation", recommendation_node)

    graph.set_entry_point("orchestrator")

    graph.add_conditional_edges(
        "orchestrator",
        route_conversation,
        {
            "qualification": "qualification",
            "recommendation": "recommendation",
            "end": END,
        },
    )

    # One sub-agent call per invocation (see module docstring) — both
    # terminate the graph run once they've produced their result.
    graph.add_edge("qualification", END)
    graph.add_edge("recommendation", END)

    return graph.compile()


# Compiled once at import time and reused across requests.
app_graph = build_graph()
