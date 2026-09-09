"""Graph wiring — exactly four agent nodes, search and rules in parallel
(DEV_B §2, B1, B2)."""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.agents.orchestrator import orchestrator_node
from app.agents.rules_agent import rules_node
from app.agents.search_agent import search_node
from app.agents.state import ScreeningState
from app.agents.synthesis_agent import synthesis_node

log = logging.getLogger(__name__)

_compiled = None


def build_graph():
    builder = StateGraph(ScreeningState)

    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("search", search_node)
    builder.add_node("rules", rules_node)
    builder.add_node("synthesis", synthesis_node)

    builder.add_edge(START, "orchestrator")
    # fan-out: two edges from the orchestrator; LangGraph merges when both
    # feed synthesis
    builder.add_edge("orchestrator", "search")
    builder.add_edge("search", "rules")
    builder.add_edge("rules", "synthesis")
    builder.add_edge("synthesis", END)

    return builder.compile()


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled
