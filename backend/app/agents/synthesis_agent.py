"""Synthesis agent — produce the analyst-facing deliverable (DEV_B §3.4, QRC slide 13).

Tools: `get_footer_text`. The agent decides the final result and the conditions
from what the earlier agents found, and writes the draft response.

The one thing it is not allowed to author is the slide-14 footer: it must call
the tool and append the returned text verbatim (B11). We enforce that after the
fact rather than trusting the prompt — the footer is re-appended from the tool
result if the agent altered or omitted it.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.agents.runtime import finalize_structured, run_agent, trace_entry
from app.agents.state import ScreeningState
from app.database import SessionLocal
from app.models.domain import BusinessUnitNature
from app.repositories import rule_repository

log = logging.getLogger(__name__)

TOOLS = ["get_footer_text"]

NO_CONFLICTS = "NO_CONFLICTS_IDENTIFIED"
APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"

SYSTEM_PROMPT = """You are the synthesis agent for a Deloitte SEA T&T conflict check.
You produce the analyst-facing response per QRC slide 13.

Decide:
1. The conditions to be satisfied, derived from what was actually found. Every match listed
   as needing reviewer attention must produce a condition — if the triage reason says a
   designation "requires a condition", write that condition. State the designation and that
   it comes from DESC, e.g. "Relationship client in DESC". Also note any source not checked.
2. The final result. Choose NO_CONFLICTS_IDENTIFIED only when nothing was found and there
   are no conditions. Otherwise choose APPROVED_WITH_CONDITIONS.
3. The draft response: opening (request, client, service offering, requesting location),
   the relationships identified grouped by source, the conditions, the cross-border actions,
   and the sources not checked.

You MUST call get_footer_text and append the returned text at the end of your draft,
word for word. Never rewrite, summarise or shorten it.

This is a drafting aid, not an approval. Cite the QRC slide behind every classification."""


class SynthesisOutput(BaseModel):
    final_result: str = Field(description="APPROVED_WITH_CONDITIONS or NO_CONFLICTS_IDENTIFIED")
    conditions: list[str] = Field(description="Conditions to be satisfied")


def _summary_table(state: ScreeningState) -> list[dict]:
    rows = []
    for m in state.get("classified_matches", []) or []:
        if not m.include_in_summary:
            continue
        rows.append({
            "entity_name": m.entity_name,
            "source": m.source,
            "country": m.country,
            "designation_type": m.designation_type,
            "gup_name": m.gup_name,
            "lcsp_rp": m.partner_name if m.source == "DESC" else None,
            "partner_name": m.partner_name,
            "practice_office": m.practice_office,
            "business_unit": m.business_unit.value if m.business_unit else None,
            "status": m.status.value if m.status else None,
            "entity_role": m.entity_role,
            "match_date": str(m.match_date) if m.match_date else None,
            "similarity": round(m.similarity, 4),
            "rule_citation": m.rule_citation,
            "risk_tier": m.risk_tier,
            "risk_reason": m.risk_reason,
        })
    # Highest risk first, so the brief leads with what needs attention.
    tier_order = {"High": 0, "Medium": 1, "Low": 2}
    rows.sort(key=lambda r: (tier_order.get(r.get("risk_tier"), 3), r["source"], r["entity_name"] or ""))
    return rows


def _brief(state: ScreeningState, summary_table: list[dict]) -> str:
    counts: dict[str, int] = {}
    designations: set[str] = set()
    wbs_units: set[str] = set()
    for row in summary_table:
        counts[row["source"]] = counts.get(row["source"], 0) + 1
        if row["source"] == "DESC" and row["designation_type"]:
            designations.add(row["designation_type"])
        if row["source"] == "WBS" and row["business_unit"]:
            wbs_units.add(row["business_unit"])

    # Surface the triage verdicts. Several of these say in so many words that
    # a condition is required (slide 5) — without them in the brief the agent
    # has to remember to re-derive that, and a run missed the analyst's actual
    # condition because of it.
    flagged = [r for r in summary_table if r.get("risk_tier") in ("High", "Medium")]
    if flagged:
        worklist = "\n".join(
            f"  [{r['risk_tier']}] {r['entity_name']} ({r['source']}) — {r.get('risk_reason')}"
            for r in flagged
        )
        worklist_block = f"Matches needing reviewer attention:\n{worklist}"
    else:
        worklist_block = "Matches needing reviewer attention: none"

    lines = [
        f"Request: {state.get('request_id')}",
        f"Service offering: {state.get('service_offering')}",
        f"Requesting location: {state.get('location')}",
        "",
        "Relationships identified: "
        + (", ".join(f"{n} in {src}" for src, n in sorted(counts.items())) or "none"),
        f"DESC designations found: {', '.join(sorted(designations)) or 'none'}",
        f"WBS business units: {', '.join(sorted(wbs_units)) or 'none'}",
        "",
        worklist_block,
        "",
        "Cross-border decisions: "
        + (
            "; ".join(
                f"{a['jurisdiction']} -> {a['outcome']} ({a.get('reason', '')})"
                for a in state.get("cross_border") or []
            )
            or "none"
        ),
        "",
        "Quality-check flags raised:",
    ]
    for flag in state.get("quality_check_flags") or []:
        lines.append(f"  [{flag['severity']}] {flag['message']}")
    lines.append("")
    lines.append("Sources not checked:")
    for note in state.get("unchecked_sources") or []:
        lines.append(f"  {note['source']}: {note['reason']}")
    if state.get("rules_findings"):
        lines += ["", "Rules agent findings:", state["rules_findings"][:1500]]
    return "\n".join(lines)


def _similar(a: str, b: str) -> bool:
    """Rough duplicate check so the agent restating a derived condition in its
    own words doesn't produce two entries saying the same thing."""
    tokens_a = {w for w in a.lower().split() if len(w) > 3}
    tokens_b = {w for w in b.lower().split() if len(w) > 3}
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))
    return overlap > 0.6


def _conditions_from_verdicts(summary_table: list[dict]) -> list[str]:
    """Conditions implied by the QRC verdicts already attached to matches.

    A DESC designation is the analyst's stated condition on the worked case
    ('Relationship client in DESC'), so it is stated in that form.
    """
    conditions: list[str] = []
    designations: set[str] = set()

    for row in summary_table:
        if row["source"] == "DESC" and row.get("designation_type"):
            for part in row["designation_type"].split(","):
                if part.strip():
                    designations.add(part.strip())
        if row["source"] == "WBS" and row.get("business_unit") == BusinessUnitNature.AUDIT.value:
            audit_condition = "Audit client — audit engagement identified in WBS"
            if audit_condition not in conditions:
                conditions.append(audit_condition)

    for designation in sorted(designations):
        lowered = designation.lower()
        if "relationship" in lowered:
            conditions.append(f"{designation} client in DESC")
        else:
            conditions.append(f"{designation} in DESC")

    return conditions


def synthesis_node(state: ScreeningState) -> dict:
    summary_table = _summary_table(state)

    run = run_agent(
        "synthesis_agent",
        SYSTEM_PROMPT,
        _brief(state, summary_table) + "\n\nWrite the conflict check response.",
        TOOLS,
        max_turns=6,
    )

    extracted = finalize_structured(
        run,
        SynthesisOutput,
        instruction=(
            "Extract the final result and the conditions to be satisfied. "
            "final_result must be exactly APPROVED_WITH_CONDITIONS or NO_CONFLICTS_IDENTIFIED."
        ),
        fallback=SynthesisOutput(
            final_result=NO_CONFLICTS if not summary_table else APPROVED_WITH_CONDITIONS,
            conditions=[],
        ),
    )

    # Conditions that follow directly from a rule verdict are taken from that
    # verdict, not from the agent's recollection of it — the same principle
    # applied to flags and cross-border. A DESC designation whose triage
    # reason says "requires a condition" must produce one; two runs wrote a
    # sensible narrative and silently dropped the analyst's actual condition.
    # The agent's own conditions are kept and merged on top.
    derived = _conditions_from_verdicts(summary_table)
    merged = list(derived)
    for condition in extracted.conditions:
        if not any(_similar(condition, existing) for existing in merged):
            merged.append(condition)
    extracted = extracted.model_copy(update={"conditions": merged})

    final_result = extracted.final_result.strip().upper()
    if final_result not in (NO_CONFLICTS, APPROVED_WITH_CONDITIONS):
        final_result = APPROVED_WITH_CONDITIONS
    # A result of "no conflicts" is only defensible with an empty table.
    if summary_table and final_result == NO_CONFLICTS:
        log.warning("Synthesis proposed NO_CONFLICTS with %d matches — overriding", len(summary_table))
        final_result = APPROVED_WITH_CONDITIONS

    draft = run.content or ""

    # B11: the footer is not the agent's to write. Whatever it produced, the
    # response must end with the tool's exact bytes.
    session = SessionLocal()
    try:
        footer = rule_repository.get_footer_text(session)
    finally:
        session.close()

    if not draft.endswith(footer):
        idx = draft.find(footer[:60]) if len(footer) > 60 else -1
        if idx != -1:
            draft = draft[:idx].rstrip()
        draft = f"{draft}\n\n── Reminders ──\n\n{footer}"

    log.info(
        "Synthesis: %s, %d summary rows, %d condition(s), %d tool call(s)",
        final_result, len(summary_table), len(extracted.conditions), len(run.tool_calls),
    )

    return {
        "final_result": final_result,
        "conditions": extracted.conditions,
        "summary_table": summary_table,
        "draft_response": draft,
        "agent_trace": [trace_entry(run)],
    }
