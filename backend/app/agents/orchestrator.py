"""Orchestrator agent — loads the case, runs the QRC quality checks, and emits
the search plan (DEV_B §3.1).

Tools: `get_case_details` (the case and its parties) and `search_rules` (the
slide 3 / slide 4 procedure). The agent decides what to read and what to flag;
nothing about the QC outcome is precomputed for it.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.agents.runtime import finalize_structured, run_agent, trace_entry
from app.agents.state import ScreeningState

log = logging.getLogger(__name__)

TOOLS = ["get_case_details", "search_rules"]

SYSTEM_PROMPT = """You are the orchestrator agent for a Deloitte SEA T&T conflict-check screening.

Your job, in order:
1. Call get_case_details to load the case, its engagement details and its relevant parties.
2. Quality check (QRC slide 3): is the stated service offering consistent with the engagement
   description? Flag WARN if, for example, the offering is T&T but the work is an audit.
3. Referral check (QRC slide 3): if the request is an inbound work referral with no IWRF,
   flag WARN to re-confirm with the ET/Governance team.
4. Relevant-party completeness (QRC slide 4): the client side requires the client, the
   controlling shareholder, the global ultimate parent, and the individual who controls the
   GUP. Flag INFO for anything missing.
5. State the search plan: the exact entity names that must be searched.

Use search_rules if you need the exact wording of a QRC procedure.
Report your findings as clear prose. Do not classify designations or engagements —
later agents do that with dedicated tools."""


class QCFlagOut(BaseModel):
    severity: str = Field(description="WARN or INFO")
    message: str = Field(max_length=400)
    action: str = Field(max_length=300)
    rule_citation: str = Field(max_length=60, description="e.g. 'QRC slide 4'")


class OrchestratorOutput(BaseModel):
    quality_check_flags: list[QCFlagOut] = Field(description="Quality-check flags raised")
    search_plan: list[str] = Field(description="Entity names to search")


def orchestrator_node(state: ScreeningState) -> dict:
    parties = state.get("parties", [])
    fallback_plan = [p["entity_name"] for p in parties if p.get("entity_name")]

    run = run_agent(
        "orchestrator",
        SYSTEM_PROMPT,
        f"Screen case_id {state['case_id']}. Load it, run the quality checks, and give me the search plan.",
        TOOLS,
        max_turns=8,
    )

    extracted = finalize_structured(
        run,
        OrchestratorOutput,
        instruction=(
            "Extract the orchestrator's quality-check flags and search plan. "
            "severity must be WARN or INFO. Include only flags the analyst actually raised."
        ),
        fallback=OrchestratorOutput(quality_check_flags=[], search_plan=fallback_plan),
    )

    plan = extracted.search_plan or fallback_plan
    flags = [f.model_dump() for f in extracted.quality_check_flags]

    log.info("Orchestrator: %d flag(s), plan=%s", len(flags), plan)

    return {
        "quality_check_flags": flags,
        "search_plan": plan,
        "agent_trace": [trace_entry(run)],
    }
