"""Search agent — find every candidate across the five sources (DEV_B §3.2).

Tools: the five search tools. The agent decides which entities to search and
where; DESC-first behaviour and one-level GUP expansion are things it is
instructed to do and does by calling tools, not steps a pipeline performs
around it.

The full match objects the tools returned are collected for persistence, so
the result screen shows what the agent actually retrieved.
"""

from __future__ import annotations

import logging

from app.agents import tools as tool_registry
from app.agents.runtime import run_agent, trace_entry
from app.agents.state import ScreeningState
from app.config import settings

log = logging.getLogger(__name__)

TOOLS = [
    "search_desc_entities",
    "search_wbs_engagements",
    "search_cot_requests",
    "search_dccs_history",
    "search_one_window",
]

ONE_WINDOW_NOTE = {
    "source": "ONE_WINDOW",
    "reason": "Strategic Client / Directorship / Sanctions / Open Opportunities data not provided",
}

SYSTEM_PROMPT = """You are the search agent for a Deloitte SEA T&T conflict-check screening.

Retrieval only — you do not classify matches; the rules agent does that.

For EVERY entity name you are given:
  - search_desc_entities   (DESC is authoritative and must be searched first)
  - search_wbs_engagements
  - search_cot_requests
  - search_dccs_history
  - search_one_window      (a stub; call it so the source is recorded as unchecked)

Then:
  - If DESC reports a GUP that is not already among the entities you were given,
    search that GUP too — ONE level only, never recursively.
  - Report, per entity and per source, how many matches were found and name the
    notable ones (especially any DESC designation and DESC GUP).

Rules of engagement:
  - Finish all five sources for one entity before moving to the next.
  - Search ONLY the entity names you were given, plus a GUP that DESC itself named.
    Do not go looking for company officers, directors or individuals by name — these
    databases hold legal entities, and guessing at people's names wastes the budget.
  - Do not repeat a search you have already run. Never invent a match."""


def _missing_coverage(names: list[str], tool_calls: list[dict]) -> list[tuple[str, str]]:
    """Which (entity, source) pairs the agent never actually searched."""
    done = {
        (str(call["args"].get("entity_name", "")).strip().lower(), call["tool"])
        for call in tool_calls
        if call["tool"] in TOOLS
    }
    return [
        (name, tool)
        for name in names
        for tool in TOOLS
        if (name.strip().lower(), tool) not in done
    ]


def search_node(state: ScreeningState) -> dict:
    names = state.get("search_plan") or [
        p["entity_name"] for p in state.get("parties", []) if p.get("entity_name")
    ]

    tool_registry.reset_collected()

    checklist = "\n".join(f"- {n}" for n in names)
    run = run_agent(
        "search_agent",
        SYSTEM_PROMPT,
        f"Search all five conflict databases for each of these entities:\n{checklist}\n\n"
        f"That is {len(names)} entities x 5 sources = {len(names) * 5} searches to complete.",
        TOOLS,
        max_turns=26,
    )

    # Coverage check. The agent decides how to search, but it does not get to
    # leave a source unsearched — one run spent its whole budget hunting for a
    # company officer by name and never touched WBS, COT or DCCS. If anything
    # is still missing we hand back the gap list and let it finish the job.
    missing = _missing_coverage(names, run.tool_calls)
    if missing:
        log.warning("Search agent left %d (entity, source) pair(s) unsearched — re-prompting", len(missing))
        gap_list = "\n".join(f"- {tool}(entity_name='{name}')" for name, tool in missing)
        follow_up = run_agent(
            "search_agent",
            SYSTEM_PROMPT,
            "These required searches have NOT been run yet. Run each one now, then stop:\n"
            f"{gap_list}",
            TOOLS,
            max_turns=len(missing) + 6,
        )
        run.tool_calls.extend(follow_up.tool_calls)
        run.results.extend(follow_up.results)
        run.reasoning.extend(follow_up.reasoning)
        run.seconds += follow_up.seconds
        run.turns += follow_up.turns
        if follow_up.content:
            run.content = f"{run.content}\n\n{follow_up.content}".strip()

    matches = tool_registry.collected_matches()

    # Deduplicate: the agent may search the same name twice, or reach one
    # entity via both the request and DESC's GUP field.
    seen = set()
    unique = []
    for m in matches:
        key = (
            m.source.value if hasattr(m.source, "value") else str(m.source),
            m.matched_name,
            m.raw.get("id") if isinstance(m.raw, dict) else None,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)

    auto = settings.MATCH_THRESHOLD_AUTO_INCLUDE
    raw_matches = [m for m in unique if m.similarity >= auto]
    possible = [m for m in unique if m.similarity < auto]

    log.info(
        "Search: agent made %d tool call(s); %d unique matches (%d confident, %d for review)",
        len(run.tool_calls), len(unique), len(raw_matches), len(possible),
    )

    searched_one_window = any(c["tool"] == "search_one_window" for c in run.tool_calls)

    return {
        "raw_matches": raw_matches,
        "possible_matches": possible,
        "search_findings": run.content,
        "unchecked_sources": [ONE_WINDOW_NOTE] if searched_one_window else [],
        "agent_trace": [trace_entry(run)],
    }
