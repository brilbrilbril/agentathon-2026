"""Rules & compliance agent — apply the QRC to what search found (DEV_B §3.3).

Tools: rule retrieval, the bulk classifier, and the individual slide
lookups (slide 4 designation comparison, slide 11 cross-border matrix).

Every verdict still comes from `rules_engine` (MASTER §7) — but the agent
decides which rules apply, calls them, and reasons about the results. It does
not receive a precomputed classification.
"""

from __future__ import annotations

import logging

from app.agents import tools as tool_registry
from app.agents.runtime import run_agent, trace_entry
from app.agents.state import ScreeningState

log = logging.getLogger(__name__)

TOOLS = [
    "get_rules_by_source",
    "apply_qrc_rules_to_all_matches",
    "compare_stated_vs_desc_designation",
    "evaluate_cross_border",
    "parse_desc_designations",
    "classify_wbs_business_unit",
    "classify_wbs_status",
    "is_cot_match_acknowledged",
    "is_dccs_match_relevant",
    "assess_risk_tier",
    "adjudicate_same_entity",
]

SYSTEM_PROMPT = """You are the rules and compliance agent for a Deloitte SEA T&T conflict check.

You must never decide a mechanical rule yourself — always call the tool for it.

Work in this order:
1. Call apply_qrc_rules_to_all_matches to classify everything search retrieved.
   Read the aggregate: what was included, what was excluded and why, the WBS
   business-unit breakdown, and which DESC designations were found.
2. For EACH party, call compare_stated_vs_desc_designation with the designation the
   request claims, the designation DESC actually holds, and the entity_name. DESC is
   authoritative (QRC slide 4). Report any contradiction and the escalation path.
2b. For each borderline match listed below as needing review, call adjudicate_same_entity
   and then decide: is it genuinely the same legal entity, or a false positive? Weed out
   the false positives — a similar name is not a match.
3. For each foreign jurisdiction among the parties (a location different from the
   requesting location), call evaluate_cross_border. Pass client_in_desc and
   gup_in_desc based on whether those entities were actually found in DESC.
4. Call get_rules_by_source if you need the governing wording for a source.

Report: the classification outcome, the risk-tier breakdown, any DESC contradiction,
which borderline matches you rejected as false positives, and the cross-border
decisions — each with its QRC slide citation."""


def rules_node(state: ScreeningState) -> dict:
    parties = state.get("parties", [])
    roster = "\n".join(
        f"- {p.get('entity_name')} | role: {p.get('entity_role')} | location: {p.get('location')} "
        f"| designation stated on the request: {p.get('stated_designation')} | is_gup: {p.get('is_gup')}"
        for p in parties
    )

    # Hand the agent the borderline matches by name so step 2b has something
    # concrete to adjudicate — these are the false positives to weed out.
    borderline = state.get("possible_matches", []) or []
    borderline_block = ""
    if borderline:
        listed = "\n".join(
            f"- '{m.matched_name}' (country: {m.country}, GUP: {m.gup_name}, "
            f"similarity {m.similarity:.2f}) matched against '{m.query_name}'"
            for m in sorted(borderline, key=lambda m: m.similarity, reverse=True)[:6]
        )
        borderline_block = f"\n\nBorderline matches needing review (step 2b):\n{listed}"

    run = run_agent(
        "rules_agent",
        SYSTEM_PROMPT,
        f"Requesting location: {state.get('location')}\n\n"
        f"Relevant parties:\n{roster}\n\n"
        f"What search found:\n{state.get('search_findings') or '(see the classifier tool)'}"
        f"{borderline_block}\n\n"
        "Classify everything, check each party's designation against DESC, adjudicate the "
        "borderline matches, and decide cross-border.",
        TOOLS,
        max_turns=18,
    )

    classified = tool_registry.classified_matches()

    # Findings come from what the agent's tool calls actually returned, not
    # from re-parsing its prose. The agent chose the tool and the arguments;
    # the tool returned the verdict. Reading that back is faithful and it does
    # not depend on a second LLM round trip — one run lost a correct DESC
    # contradiction because the extraction step emitted malformed JSON.
    flags, cross_border = _harvest(run, state)

    included = sum(1 for c in classified if c.include_in_summary)
    log.info(
        "Rules: agent made %d tool call(s); %d matches classified (%d included), "
        "%d flag(s), %d cross-border action(s)",
        len(run.tool_calls), len(classified), included, len(flags), len(cross_border),
    )

    return {
        "classified_matches": classified,
        "quality_check_flags": flags,
        "cross_border": cross_border,
        "rules_findings": run.content,
        "agent_trace": [trace_entry(run)],
    }


def _harvest(run, state: ScreeningState) -> tuple[list[dict], list[dict]]:
    """Read verdicts straight out of the tool results the agent produced."""
    parties = state.get("parties", [])
    flags: list[dict] = []
    cross_border: list[dict] = []
    seen_jurisdictions: set[str] = set()

    for record in run.results:
        result = record["result"]
        if not isinstance(result, dict) or "error" in result:
            continue
        args = record["args"]

        if record["tool"] == "compare_stated_vs_desc_designation" and result.get("contradiction"):
            stated = str(args.get("stated_designation", ""))
            # Name the entity the agent was asking about, so the flag is actionable.
            entity = next(
                (
                    p["entity_name"] for p in parties
                    if (p.get("stated_designation") or "").strip().lower() == stated.strip().lower()
                ),
                None,
            )
            message = result["message"]
            if entity:
                message = message.replace("Request states designation", f"Request states {entity} designation", 1)
            flags.append({
                "severity": result.get("severity", "WARN"),
                "message": message,
                "action": result.get("action"),
                "rule_citation": result.get("rule_citation", "QRC slide 4"),
            })

        elif record["tool"] == "evaluate_cross_border":
            jurisdiction = result.get("jurisdiction") or args.get("jurisdiction")
            if not jurisdiction or jurisdiction.lower() in seen_jurisdictions:
                continue
            seen_jurisdictions.add(jurisdiction.lower())
            cross_border.append({
                "jurisdiction": jurisdiction,
                "outcome": result.get("outcome"),
                "reason": result.get("reason"),
                "rule_citation": result.get("rule_citation", "QRC slide 11"),
            })

    return flags, cross_border
