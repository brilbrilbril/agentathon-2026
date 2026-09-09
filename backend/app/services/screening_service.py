"""ScreeningService — the three functions Dev C calls (DEV_B §0)."""

from __future__ import annotations

import logging

from app.agents.graph import get_graph
from app.config import settings
from app.database import SessionLocal
from app.repositories import case_repository, screening_repository

log = logging.getLogger(__name__)


def _state_from_case(case: dict, parties: list[dict]) -> dict:
    return {
        "case_id": str(case["id"]),
        "request_id": case.get("request_id"),
        "service_offering": case.get("service_offering"),
        "engagement_details": case.get("engagement_details"),
        "location": case.get("location"),
        "is_inbound_referral": bool(case.get("is_inbound_referral")),
        "has_iwrf": bool(case.get("has_iwrf")),
        "parties": [
            {
                "entity_name": p["entity_name"],
                "entity_role": p.get("entity_role"),
                "entity_type": p.get("entity_type"),
                "location": p.get("location"),
                "stated_designation": p.get("stated_designation"),
                "is_gup": bool(p.get("is_gup")),
                "party_side": p.get("party_side") or "CLIENT_SIDE",
            }
            for p in parties
        ],
        "quality_check_flags": [],
        "raw_matches": [],
        "applicable_rules": [],
        "agent_trace": [],
    }


def _match_rows(state: dict) -> list[dict]:
    rows = []
    for m in state.get("classified_matches", []) or []:
        rows.append({
            "source": m.source,
            "query_name": m.query_name,
            "matched_name": m.entity_name,
            "similarity": m.similarity,
            "country": m.country,
            "designation_type": m.designation_type,
            "gup_name": m.gup_name,
            "partner_name": m.partner_name,
            "practice_office": m.practice_office,
            "business_unit": m.business_unit.value if m.business_unit else None,
            "status": m.status.value if m.status else None,
            "entity_role": m.entity_role,
            "match_date": m.match_date,
            "include_in_summary": m.include_in_summary,
            "exclusion_reason": m.exclusion_reason,
            "rule_citation": m.rule_citation,
            "risk_tier": m.risk_tier,
            "risk_reason": m.risk_reason,
            "raw": {},
        })
    for m in state.get("possible_matches", []) or []:
        rows.append({
            "source": m.source.value if hasattr(m.source, "value") else str(m.source),
            "query_name": m.query_name,
            "matched_name": m.matched_name,
            "similarity": m.similarity,
            "country": m.country,
            "designation_type": m.designation_type,
            "gup_name": m.gup_name,
            "partner_name": m.partner_name,
            "practice_office": m.practice_office,
            "business_unit": m.business_unit.value if m.business_unit else None,
            "status": m.status.value if m.status else None,
            "entity_role": m.entity_role,
            "match_date": m.match_date,
            "include_in_summary": False,
            # The rules agent may have annotated this with the model's
            # same-legal-entity verdict — keep it rather than overwriting.
            "exclusion_reason": m.exclusion_reason or "Below auto-include threshold — analyst review required",
            "rule_citation": m.rule_citation,
            "risk_tier": None,
            "risk_reason": None,
            "raw": {},
        })
    return rows


def run_screening(case_id: str, screening_id: str | None = None) -> str:
    """Runs the graph on a case. Returns the screening id.

    Failure sets status FAILED with a message rather than raising (B15)."""
    session = SessionLocal()
    try:
        case = case_repository.get(session, case_id)
        if case is None:
            raise ValueError(f"case {case_id} not found")
        parties = case_repository.get_parties(session, case_id)

        if screening_id is None:
            screening_id = screening_repository.create_pending(session, case_id)
        screening_repository.update_status(session, screening_id, "RUNNING")

        try:
            graph = get_graph()
            state = graph.invoke(
                _state_from_case(case, parties),
                config={"recursion_limit": settings.GRAPH_RECURSION_LIMIT},
            )
        except Exception as exc:
            log.exception("Screening %s failed", screening_id)
            screening_repository.update_status(session, screening_id, "FAILED", error=str(exc))
            return screening_id

        screening_repository.save_matches(session, screening_id, _match_rows(state))
        screening_repository.finalize(session, screening_id, {
            "final_result": state.get("final_result"),
            "conditions": state.get("conditions") or [],
            "cross_border_actions": state.get("cross_border") or [],
            "quality_check_flags": state.get("quality_check_flags") or [],
            "unchecked_sources": state.get("unchecked_sources") or [],
            "draft_response": state.get("draft_response"),
        })
        log.info("Screening %s complete: %s", screening_id, state.get("final_result"))
        return screening_id
    finally:
        session.close()


def get_screening_result(session, screening_id: str) -> dict | None:
    """Assembles the full result payload from persisted rows."""
    screening = screening_repository.get(session, screening_id)
    if screening is None:
        return None

    matches = screening_repository.get_matches(session, screening_id)
    summary_table, possible_matches, excluded_matches = [], [], []

    for m in matches:
        row = {
            "entity_name": m["matched_name"],
            "source": m["source"],
            "country": m["country"],
            "designation_type": m["designation_type"],
            "gup_name": m["gup_name"],
            "lcsp_rp": m["partner_name"] if m["source"] == "DESC" else None,
            "partner_name": m["partner_name"],
            "practice_office": m["practice_office"],
            "business_unit": m["business_unit"],
            "status": m["status"],
            "entity_role": m["entity_role"],
            "match_date": str(m["match_date"]) if m["match_date"] else None,
            "similarity": round(m["similarity"], 4) if m["similarity"] is not None else None,
            "exclusion_reason": m["exclusion_reason"],
            "rule_citation": m["rule_citation"],
            "risk_tier": m["risk_tier"],
            "risk_reason": m["risk_reason"],
        }
        if m["include_in_summary"]:
            summary_table.append(row)
        elif "below auto-include threshold" in (m["exclusion_reason"] or "").lower():
            row["note"] = m["exclusion_reason"]
            possible_matches.append(row)
        else:
            excluded_matches.append(row)

    # Highest risk first — this is the worklist ordering a reviewer wants.
    tier_order = {"High": 0, "Medium": 1, "Low": 2}
    summary_table.sort(
        key=lambda r: (tier_order.get(r.get("risk_tier"), 3), r["source"], r["entity_name"] or "")
    )
    triage: dict[str, int] = {}
    for row in summary_table:
        if row.get("risk_tier"):
            triage[row["risk_tier"]] = triage.get(row["risk_tier"], 0) + 1

    return {
        "screening_id": str(screening["id"]),
        "case_id": str(screening["case_id"]),
        "status": screening["status"],
        "final_result": screening["final_result"],
        "quality_check_flags": screening["quality_check_flags"] or [],
        "summary_table": summary_table,
        "risk_summary": triage,
        "possible_matches": possible_matches,
        "excluded_matches": excluded_matches,
        "conditions": screening["conditions"] or [],
        "cross_border_actions": screening["cross_border_actions"] or [],
        "unchecked_sources": screening["unchecked_sources"] or [],
        "draft_response": screening["draft_response"],
        "error": screening["error"],
        "created_at": screening["created_at"],
        "completed_at": screening["completed_at"],
    }


# Chat is a real tool-using agent; it lives in its own module.
from app.services.chat_agent import chat  # noqa: F401
