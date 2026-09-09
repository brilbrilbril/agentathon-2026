"""The tool registry — real, callable tools exposed to the model.

Every entry here is an OpenAI-style function definition plus a Python
implementation. The agent decides *which* tool to call and *with what*; this
module only executes and returns results.

Determinism lives inside tools, never in the orchestration. `rules_engine`
still owns every mechanical QRC verdict (MASTER §7) — but an agent has to
choose to call it, and the call and its result are recorded in the trace.

Results are deliberately compact. The model has a small context and the
sources are large (3,480 DCCS rows), so search tools return a truncated,
flattened view plus a total count rather than raw rows.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.repositories import case_repository, rule_repository
from app.repositories.entity_search import (
    search_cot,
    search_dccs_history,
    search_desc,
    search_wbs,
)
from app.rules.rules_engine import (
    assess_risk_tier,
    classify_wbs_business_unit,
    classify_wbs_status,
    compare_stated_vs_desc_designation,
    evaluate_cross_border,
    is_cot_match_acknowledged,
    is_dccs_match_relevant,
    parse_desc_designations,
)

log = logging.getLogger(__name__)

MAX_ROWS_RETURNED = 8

# Search tools hand the model a compact digest, but the full match objects
# still have to reach the database and the result screen. Rather than run a
# second, parallel pipeline to recompute them, each search records what it
# actually returned here — so the persisted table is tool output, not a
# separate deterministic pass the agent never saw.
_collected: list = []


def reset_collected() -> None:
    _collected.clear()
    _classified.clear()
    _contradicted_entities.clear()


def collected_matches() -> list:
    return list(_collected)


def _compact(match) -> dict:
    """One match, flattened to the fields an analyst would actually weigh."""
    out = {
        "name": match.matched_name,
        "similarity": round(match.similarity, 2),
    }
    for key, value in (
        ("country", match.country),
        ("designation", match.designation_type),
        ("gup", match.gup_name),
        ("partner", match.partner_name),
        ("office", match.practice_office),
        ("business_unit", match.business_unit.value if match.business_unit else None),
        ("status", match.status.value if match.status else None),
        ("entity_role", match.entity_role),
        ("date", str(match.match_date) if match.match_date else None),
        ("rule", match.rule_citation),
    ):
        if value:
            out[key] = value
    return out


def _search(fn, entity_name: str, source: str) -> dict:
    session = SessionLocal()
    try:
        hits = fn(session, entity_name, threshold=settings.MATCH_THRESHOLD_REVIEW, limit=200)
        _collected.extend(hits)
        auto = [h for h in hits if h.similarity >= settings.MATCH_THRESHOLD_AUTO_INCLUDE]
        review = [h for h in hits if h.similarity < settings.MATCH_THRESHOLD_AUTO_INCLUDE]
        return {
            "source": source,
            "query": entity_name,
            "total_matches": len(hits),
            "confident_matches": len(auto),
            "needs_review": len(review),
            "results": [_compact(h) for h in auto[:MAX_ROWS_RETURNED]],
            "review_candidates": [_compact(h) for h in review[:MAX_ROWS_RETURNED]],
            "truncated": len(auto) > MAX_ROWS_RETURNED,
        }
    finally:
        session.close()


# ---------------------------------------------------------------- search tools

def tool_search_desc_entities(entity_name: str) -> dict:
    return _search(search_desc, entity_name, "DESC")


def tool_search_wbs_engagements(entity_name: str) -> dict:
    return _search(search_wbs, entity_name, "WBS")


def tool_search_cot_requests(entity_name: str) -> dict:
    return _search(search_cot, entity_name, "COT")


def tool_search_dccs_history(entity_name: str) -> dict:
    return _search(search_dccs_history, entity_name, "DCCS_HISTORY")


def tool_search_one_window(entity_name: str) -> dict:
    """Stub — no data provided (MASTER §12)."""
    return {
        "source": "ONE_WINDOW",
        "query": entity_name,
        "total_matches": 0,
        "results": [],
        "unchecked": True,
        "reason": "Strategic Client / Directorship / Sanctions / Open Opportunities data not provided",
    }


def tool_search_engagements_by_partner(partner_name: str) -> dict:
    """Which clients a named partner or manager is already engaged with.

    The entity-side searches answer "is this client conflicted?". This answers
    the engagement-team side: whether putting a specific person on a job
    creates an issue — the Audit Team Restricted designation (slide 5) and
    Personal Conflicts (slide 14) both turn on who is staffed.
    """
    session = SessionLocal()
    try:
        rows = session.execute(
            text(
                """
                SELECT 'WBS' AS source, client_name_full AS client, em_partner_name AS person,
                       'Engagement partner' AS role, wbs_text AS detail, geo AS location
                FROM wbs_engagements
                WHERE em_partner_name ILIKE '%' || :q || '%'
                   OR em_manager_name ILIKE '%' || :q || '%'
                   OR client_lcsp_name ILIKE '%' || :q || '%'
                UNION ALL
                SELECT 'COT', client_name, partner, 'Onboarding partner', service_line, requesting_country
                FROM cot_requests
                WHERE partner ILIKE '%' || :q || '%' OR manager ILIKE '%' || :q || '%'
                UNION ALL
                SELECT 'DCCS_HISTORY', entity_name, lead_partner, 'Lead partner', service_type, NULL
                FROM dccs_search_results
                WHERE lead_partner ILIKE '%' || :q || '%'
                LIMIT 200
                """
            ),
            {"q": partner_name.strip()},
        ).mappings().all()

        by_source: dict[str, int] = {}
        for row in rows:
            by_source[row["source"]] = by_source.get(row["source"], 0) + 1

        return {
            "partner": partner_name,
            "total_engagements": len(rows),
            "by_source": by_source,
            "engagements": [
                {
                    "source": r["source"],
                    "client": r["client"],
                    "person": r["person"],
                    "role": r["role"],
                    "detail": r["detail"],
                    "location": r["location"],
                }
                for r in rows[:MAX_ROWS_RETURNED]
            ],
            "truncated": len(rows) > MAX_ROWS_RETURNED,
            "note": (
                "Deloitte personnel records are not available in this build — this reflects "
                "engagement records only, not HR data, directorships or personal holdings."
            ),
        }
    finally:
        session.close()


def tool_get_desc_responsible_party(entity_name: str) -> dict:
    """The DESC LCSP / Responsible Party for an entity (QRC slide 5).

    The person to clear a relationship with before staffing or proceeding.
    """
    session = SessionLocal()
    try:
        hits = search_desc(session, entity_name, threshold=settings.MATCH_THRESHOLD_REVIEW, limit=5)
        return {
            "query": entity_name,
            "matches": [
                {
                    "entity": h.matched_name,
                    "responsible_party": h.partner_name,
                    "country": h.country,
                    "designation": h.designation_type,
                    "gup": h.gup_name,
                }
                for h in hits
            ],
            "rule_citation": "QRC slide 5",
        }
    finally:
        session.close()


# ----------------------------------------------------------------- rule tools

def tool_get_rules_by_source(source_db: str) -> dict:
    session = SessionLocal()
    try:
        chunks = rule_repository.get_rules_by_source(session, source_db.upper())
        return {
            "source_db": source_db.upper(),
            "rules": [
                {"slide": c.slide_number, "title": c.title, "text": c.text[:1200]} for c in chunks
            ],
        }
    finally:
        session.close()


def tool_search_rules(query: str) -> dict:
    session = SessionLocal()
    try:
        chunks = rule_repository.search_rules(session, query, top_k=3)
        return {
            "query": query,
            "rules": [
                {"slide": c.slide_number, "title": c.title, "text": c.text[:1200]} for c in chunks
            ],
        }
    finally:
        session.close()


def tool_get_footer_text() -> dict:
    """Slide-14 footer, verbatim. Must be appended to the draft response
    without alteration (B11)."""
    session = SessionLocal()
    try:
        return {"footer": rule_repository.get_footer_text(session), "verbatim": True}
    finally:
        session.close()


# ------------------------------------------------------- deterministic verdicts

def tool_classify_wbs_business_unit(market_offering_l1: str, market_offering_l4: str, wbs_text: str) -> dict:
    nature, citation = classify_wbs_business_unit(market_offering_l1, market_offering_l4, wbs_text)
    return {"business_unit": nature.value, "rule_citation": citation}


def tool_classify_wbs_status(status: str, wbs_complete_date: str | None = None, desc_designation: str | None = None) -> dict:
    from app.ingestion.utils import safe_date

    match_status, include, reason, citation = classify_wbs_status(
        status, safe_date(wbs_complete_date), desc_designation
    )
    return {
        "status": match_status.value,
        "include_in_summary": include,
        "exclusion_reason": reason,
        "rule_citation": citation,
    }


_DATE_HELP = (
    "Could not parse '{value}' as a date. Supply a full date as YYYY-MM-DD or DD/MM/YYYY "
    "(a year alone is not enough to apply the rule)."
)


def tool_is_cot_match_acknowledged(submission_time: str) -> dict:
    from app.ingestion.utils import safe_datetime

    parsed = safe_datetime(submission_time)
    if parsed is None:
        # Never answer with a test silently skipped — make the model fix the input.
        return {"error": _DATE_HELP.format(value=submission_time), "rule_citation": "QRC slide 9"}

    include, reason, citation = is_cot_match_acknowledged(parsed)
    return {"acknowledged": include, "exclusion_reason": reason, "rule_citation": citation}


def tool_is_dccs_match_relevant(request_date: str, status: str, already_in_other_source: bool = False) -> dict:
    from app.ingestion.utils import safe_date

    parsed = safe_date(request_date)
    if parsed is None:
        # A missing date would skip the 2-year staleness test and wrongly
        # report the match as relevant. Refuse rather than half-apply slide 10.
        return {"error": _DATE_HELP.format(value=request_date), "rule_citation": "QRC slide 10"}

    include, reason, citation = is_dccs_match_relevant(parsed, status, already_in_other_source)
    return {"relevant": include, "exclusion_reason": reason, "rule_citation": citation}


def tool_assess_risk_tier(
    source: str,
    designation_type: str = "",
    business_unit: str = "",
    status: str = "",
    has_desc_contradiction: bool = False,
) -> dict:
    from app.rules.rules_engine import assess_risk_tier

    tier, reason, citation = assess_risk_tier(
        source=source.upper(),
        designation_type=designation_type or None,
        business_unit=business_unit or None,
        status=status or None,
        has_desc_contradiction=has_desc_contradiction,
    )
    return {"risk_tier": tier, "reason": reason, "rule_citation": citation}


def tool_adjudicate_same_entity(
    query_name: str,
    candidate_name: str,
    query_country: str = "",
    candidate_country: str = "",
    candidate_gup: str = "",
) -> dict:
    """Structure a borderline match for the agent to judge.

    Deliberately NOT a verdict: whether two records are the same legal entity
    is a judgement call (MASTER §7), so this returns the comparable facts and
    the test to apply. The agent decides.
    """
    from app.repositories.entity_search import normalise_name

    q_norm = normalise_name(query_name)
    c_norm = normalise_name(candidate_name)
    return {
        "query": {"name": query_name, "normalised": q_norm, "country": query_country or None},
        "candidate": {
            "name": candidate_name,
            "normalised": c_norm,
            "country": candidate_country or None,
            "gup": candidate_gup or None,
        },
        "names_match_after_stripping_legal_suffixes": q_norm == c_norm,
        "countries_match": bool(query_country and candidate_country)
        and query_country.strip().lower() == candidate_country.strip().lower(),
        "guidance": (
            "Same legal entity requires more than a similar name. Weigh country/domicile and "
            "global ultimate parent. Name differences that are only legal-form suffixes "
            "(Limited, Company Limited, Pte Ltd, KK) do not make them different entities. "
            "Different operating subsidiaries of one group ARE different entities."
        ),
    }


def tool_parse_desc_designations(designation_type: str) -> dict:
    return {
        "designations": parse_desc_designations(designation_type),
        "rule_citation": "QRC slide 5",
    }


def tool_compare_stated_vs_desc_designation(
    stated_designation: str, desc_designation: str, entity_name: str = ""
) -> dict:
    flag = compare_stated_vs_desc_designation(stated_designation, desc_designation)
    if flag is None:
        return {"contradiction": False, "rule_citation": "QRC slide 4"}
    # Remember it so triage can escalate this entity's matches to High.
    note_contradiction(entity_name)
    return {
        "contradiction": True,
        "severity": flag.severity,
        "message": flag.message,
        "action": flag.action,
        "rule_citation": flag.rule_citation,
    }


def tool_evaluate_cross_border(jurisdiction: str, client_in_desc: bool, gup_in_desc: bool, client_is_gup: bool = False) -> dict:
    return evaluate_cross_border(
        client_in_desc=client_in_desc,
        gup_in_desc=gup_in_desc,
        client_is_gup=client_is_gup,
        jurisdiction=jurisdiction,
    ).to_dict()


_classified: list = []

# Entities where DESC contradicted the request. Recorded when the agent calls
# compare_stated_vs_desc_designation, and read back during triage so a
# contradicted entity is escalated to High.
_contradicted_entities: set = set()


def classified_matches() -> list:
    return list(_classified)


def note_contradiction(entity_name: str) -> None:
    if entity_name:
        _contradicted_entities.add(entity_name.strip().lower())


def tool_apply_qrc_rules_to_all_matches() -> dict:
    """Apply the QRC classification rules to every match retrieved so far.

    This is a bulk tool because the volume is real — thousands of DCCS rows
    reach this point. Each row is decided by `rules_engine` (slides 5, 6, 9
    and 10), never by judgement, and every verdict carries its slide citation.
    The agent gets the aggregate plus a sample to reason about.
    """
    from app.agents.state import ClassifiedMatch
    from app.models.domain import BusinessUnitNature, MatchSource, MatchStatus

    _classified.clear()

    matches = [m for m in _collected if m.similarity >= settings.MATCH_THRESHOLD_AUTO_INCLUDE]
    covered = {
        ((m.matched_name or "").lower(), (m.partner_name or "").lower())
        for m in matches
        if m.source in (MatchSource.WBS, MatchSource.COT)
    }

    seen: set = set()
    for match in matches:
        source = match.source.value if hasattr(match.source, "value") else str(match.source)
        key = (source, match.matched_name, match.raw.get("id") if isinstance(match.raw, dict) else None)
        if key in seen:
            continue
        seen.add(key)

        if source == "DESC":
            designations = parse_desc_designations(match.designation_type)
            classified = ClassifiedMatch.from_entity_match(
                match,
                include_in_summary=bool(designations),
                exclusion_reason=None if designations else
                "No DESC designation — caveat raised in Conditions instead of the summary table",
                rule_citation="QRC slide 5",
            )
        elif source == "COT":
            include, reason, citation = is_cot_match_acknowledged(match.raw.get("submission_time"))
            classified = ClassifiedMatch.from_entity_match(
                match,
                business_unit=BusinessUnitNature.NON_ASSURANCE if include else None,
                status=MatchStatus.ONGOING if include else None,
                include_in_summary=include,
                exclusion_reason=reason,
                rule_citation=citation,
            )
        elif source == "DCCS_HISTORY":
            raw = match.raw or {}
            dedupe_key = ((match.matched_name or "").lower(), (raw.get("lead_partner") or "").lower())
            include, reason, citation = is_dccs_match_relevant(
                match.match_date, raw.get("status"), dedupe_key in covered
            )
            classified = ClassifiedMatch.from_entity_match(
                match,
                status=MatchStatus.PURSUING if include else None,
                include_in_summary=include,
                exclusion_reason=reason,
                rule_citation=citation,
            )
        else:
            # WBS verdicts were already produced by slides 6 during retrieval.
            classified = ClassifiedMatch.from_entity_match(match)

        # Triage every included match so the reviewer gets a worklist, not a
        # flat list. Deterministic, derived from the verdicts just produced.
        if classified.include_in_summary:
            tier, reason, _ = assess_risk_tier(
                source=source,
                designation_type=classified.designation_type,
                business_unit=classified.business_unit.value if classified.business_unit else None,
                status=classified.status.value if classified.status else None,
                has_desc_contradiction=(
                    source == "DESC" and _contradicted_entities
                    and (classified.entity_name or "").strip().lower() in _contradicted_entities
                ),
            )
            classified.risk_tier = tier
            classified.risk_reason = reason

        _classified.append(classified)

    included = [c for c in _classified if c.include_in_summary]
    excluded = [c for c in _classified if not c.include_in_summary]

    by_source: dict[str, dict] = {}
    for c in _classified:
        entry = by_source.setdefault(c.source, {"included": 0, "excluded": 0})
        entry["included" if c.include_in_summary else "excluded"] += 1

    wbs_units: dict[str, int] = {}
    for c in included:
        if c.source == "WBS" and c.business_unit:
            wbs_units[c.business_unit.value] = wbs_units.get(c.business_unit.value, 0) + 1

    reasons: dict[str, int] = {}
    for c in excluded:
        if c.exclusion_reason:
            key = c.exclusion_reason.split("(")[0].strip()[:80]
            reasons[key] = reasons.get(key, 0) + 1

    tiers: dict[str, int] = {}
    for c in included:
        if c.risk_tier:
            tiers[c.risk_tier] = tiers.get(c.risk_tier, 0) + 1

    return {
        "total_classified": len(_classified),
        "included_in_summary": len(included),
        "excluded": len(excluded),
        "risk_tiers": tiers,
        "needs_reviewer_attention": tiers.get("High", 0) + tiers.get("Medium", 0),
        "by_source": by_source,
        "wbs_business_units": wbs_units,
        "desc_designations": sorted({c.designation_type for c in included if c.source == "DESC" and c.designation_type}),
        "exclusion_reasons": reasons,
        "sample_included": [_compact_classified(c) for c in included[:6]],
        "rule_citations": ["QRC slide 5", "QRC slide 6", "QRC slide 9", "QRC slide 10"],
    }


def _compact_classified(c) -> dict:
    out = {"name": c.entity_name, "source": c.source, "rule": c.rule_citation}
    if c.risk_tier:
        out["risk_tier"] = c.risk_tier
    if c.designation_type:
        out["designation"] = c.designation_type
    if c.business_unit:
        out["business_unit"] = c.business_unit.value
    if c.status:
        out["status"] = c.status.value
    return out


# ----------------------------------------------------------------- case tools

def tool_get_case_details(case_id: str) -> dict:
    import uuid as _uuid

    # The model reaches for this with an entity name when it wants a lookup.
    # Postgres then raises on the UUID cast and the raw traceback goes back to
    # the model, which is both noisy and unhelpful. Redirect it instead.
    try:
        _uuid.UUID(str(case_id).strip())
    except (ValueError, AttributeError, TypeError):
        return {
            "error": f"'{case_id}' is not a case id. This tool takes the UUID of a "
                     "conflict-check case.",
            "hint": "To look up a company, use search_desc_entities / search_wbs_engagements "
                    "/ search_cot_requests / search_dccs_history instead.",
        }

    session = SessionLocal()
    try:
        case = case_repository.get(session, case_id)
        if case is None:
            return {"error": f"case {case_id} not found"}
        parties = case_repository.get_parties(session, case_id)
        return {
            "request_id": case.get("request_id"),
            "service_offering": case.get("service_offering"),
            "engagement_name": case.get("engagement_name"),
            "engagement_details": case.get("engagement_details"),
            "location": case.get("location"),
            "is_inbound_referral": bool(case.get("is_inbound_referral")),
            "has_iwrf": bool(case.get("has_iwrf")),
            "lead_partner": case.get("lead_partner"),
            "lead_manager": case.get("lead_manager"),
            "parties": [
                {
                    "entity_name": p["entity_name"],
                    "entity_role": p.get("entity_role"),
                    "location": p.get("location"),
                    "stated_designation": p.get("stated_designation"),
                    "is_gup": bool(p.get("is_gup")),
                }
                for p in parties
            ],
        }
    finally:
        session.close()


# ------------------------------------------------------------------- registry

def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}

TOOLS: dict[str, tuple[dict, Callable[..., Any]]] = {
    "search_desc_entities": (
        _schema(
            "search_desc_entities",
            "Search DESC (the authoritative entity master) for an entity by name. "
            "Returns legal name, designation type, domicile and GUP. DESC overrides "
            "whatever the request claims.",
            {"entity_name": _STR}, ["entity_name"],
        ),
        tool_search_desc_entities,
    ),
    "search_wbs_engagements": (
        _schema(
            "search_wbs_engagements",
            "Search the WBS engagement listing (actual chargeable work) for a client name. "
            "Returns engagements with business unit, partner, office and status.",
            {"entity_name": _STR}, ["entity_name"],
        ),
        tool_search_wbs_engagements,
    ),
    "search_cot_requests": (
        _schema(
            "search_cot_requests",
            "Search the Client Onboarding Tool for in-flight onboarding requests for a client name.",
            {"entity_name": _STR}, ["entity_name"],
        ),
        tool_search_cot_requests,
    ),
    "search_dccs_history": (
        _schema(
            "search_dccs_history",
            "Search prior DCCS conflict-check and cross-border requests involving an entity.",
            {"entity_name": _STR}, ["entity_name"],
        ),
        tool_search_dccs_history,
    ),
    "search_one_window": (
        _schema(
            "search_one_window",
            "Search One Window (Strategic Client, Directorship, Sanctions, Open Opportunities). "
            "Currently a stub with no data — call it to record the source as unchecked.",
            {"entity_name": _STR}, ["entity_name"],
        ),
        tool_search_one_window,
    ),
    "get_rules_by_source": (
        _schema(
            "get_rules_by_source",
            "Retrieve the QRC rules governing one database. "
            "source_db is one of DESC, WBS, COT, DCCS_SEARCH, ONE_WINDOW, CROSS_BORDER, GENERAL, FOOTER.",
            {"source_db": _STR}, ["source_db"],
        ),
        tool_get_rules_by_source,
    ),
    "search_rules": (
        _schema(
            "search_rules",
            "Full-text search the QRC rulebook for a procedural question. Use this to answer "
            "'how do I...' or 'when should I...' questions with a slide citation.",
            {"query": _STR}, ["query"],
        ),
        tool_search_rules,
    ),
    "get_footer_text": (
        _schema(
            "get_footer_text",
            "Return the QRC slide-14 footer (DPM 1420 + Personal Conflicts). Append it to a draft "
            "response VERBATIM. Never paraphrase or summarise it.",
            {}, [],
        ),
        tool_get_footer_text,
    ),
    "classify_wbs_business_unit": (
        _schema(
            "classify_wbs_business_unit",
            "Apply QRC slide 6 to decide whether a WBS engagement is Audit, Assurance or "
            "Non-Assurance. Always use this instead of judging it yourself.",
            {"market_offering_l1": _STR, "market_offering_l4": _STR, "wbs_text": _STR},
            ["market_offering_l1", "market_offering_l4", "wbs_text"],
        ),
        tool_classify_wbs_business_unit,
    ),
    "classify_wbs_status": (
        _schema(
            "classify_wbs_status",
            "Apply QRC slide 6 status rules to a WBS engagement (Released / Technically Completed).",
            {"status": _STR, "wbs_complete_date": _STR, "desc_designation": _STR}, ["status"],
        ),
        tool_classify_wbs_status,
    ),
    "is_cot_match_acknowledged": (
        _schema(
            "is_cot_match_acknowledged",
            "Apply the QRC slide 9 cutoff: COT matches submitted before 15 Jul 2025 are not acknowledged.",
            {"submission_time": _STR}, ["submission_time"],
        ),
        tool_is_cot_match_acknowledged,
    ),
    "is_dccs_match_relevant": (
        _schema(
            "is_dccs_match_relevant",
            "Apply QRC slide 10 relevance tests to a DCCS history row: 2-year staleness, "
            "excluded statuses, and the WBS/COT dedupe test.",
            {"request_date": _STR, "status": _STR, "already_in_other_source": _BOOL},
            ["request_date", "status"],
        ),
        tool_is_dccs_match_relevant,
    ),
    "parse_desc_designations": (
        _schema(
            "parse_desc_designations",
            "Split a DESC designation string into individual recognised designations (QRC slide 5).",
            {"designation_type": _STR}, ["designation_type"],
        ),
        tool_parse_desc_designations,
    ),
    "compare_stated_vs_desc_designation": (
        _schema(
            "compare_stated_vs_desc_designation",
            "Apply QRC slide 4: compare what the request claims an entity's designation is against "
            "what DESC records. DESC is authoritative. Returns a WARN flag and escalation path if they "
            "differ. Pass entity_name so the contradiction can be escalated in risk triage.",
            {"stated_designation": _STR, "desc_designation": _STR, "entity_name": _STR},
            ["stated_designation", "desc_designation"],
        ),
        tool_compare_stated_vs_desc_designation,
    ),
    "evaluate_cross_border": (
        _schema(
            "evaluate_cross_border",
            "Apply the QRC slide 11 cross-border matrix for one foreign jurisdiction.",
            {
                "jurisdiction": _STR,
                "client_in_desc": _BOOL,
                "gup_in_desc": _BOOL,
                "client_is_gup": _BOOL,
            },
            ["jurisdiction", "client_in_desc", "gup_in_desc"],
        ),
        tool_evaluate_cross_border,
    ),
    "search_engagements_by_partner": (
        _schema(
            "search_engagements_by_partner",
            "Find which clients a named Deloitte partner or manager is already engaged with, "
            "across WBS, COT and DCCS history. Use this for engagement-team questions: whether "
            "staffing a specific person creates a conflict, who already serves a client, or "
            "who is on the audit team for a Restricted entity.",
            {"partner_name": _STR}, ["partner_name"],
        ),
        tool_search_engagements_by_partner,
    ),
    "get_desc_responsible_party": (
        _schema(
            "get_desc_responsible_party",
            "Get the DESC LCSP / Responsible Party for an entity — the person to clear a "
            "relationship with before proceeding (QRC slide 5).",
            {"entity_name": _STR}, ["entity_name"],
        ),
        tool_get_desc_responsible_party,
    ),
    "assess_risk_tier": (
        _schema(
            "assess_risk_tier",
            "Triage one match into High / Medium / Low reviewer priority. High means an "
            "independence risk (Restricted designation, Audit engagement, or DESC contradicting "
            "the request). Medium means a condition is likely. Low means record-only. Use this "
            "so the reviewer gets a worklist rather than a flat list.",
            {
                "source": _STR,
                "designation_type": _STR,
                "business_unit": _STR,
                "status": _STR,
                "has_desc_contradiction": _BOOL,
            },
            ["source"],
        ),
        tool_assess_risk_tier,
    ),
    "adjudicate_same_entity": (
        _schema(
            "adjudicate_same_entity",
            "Compare a borderline fuzzy match against the entity being screened. Returns the "
            "comparable facts (normalised names, country, GUP) and the test to apply. It does "
            "NOT return a verdict — you decide whether they are the same legal entity, because "
            "that is a judgement call. Use this to weed out false positives.",
            {
                "query_name": _STR,
                "candidate_name": _STR,
                "query_country": _STR,
                "candidate_country": _STR,
                "candidate_gup": _STR,
            },
            ["query_name", "candidate_name"],
        ),
        tool_adjudicate_same_entity,
    ),
    "apply_qrc_rules_to_all_matches": (
        _schema(
            "apply_qrc_rules_to_all_matches",
            "Apply the QRC classification rules (slides 5, 6, 9, 10) to every match retrieved so "
            "far. Use this after searching. Returns how many matches were included vs excluded, "
            "the WBS business-unit breakdown, DESC designations found, and why matches were "
            "excluded. Each verdict carries its slide citation.",
            {}, [],
        ),
        tool_apply_qrc_rules_to_all_matches,
    ),
    "get_case_details": (
        _schema(
            "get_case_details",
            "Load a conflict-check case: engagement details and the relevant parties with their "
            "stated roles and designations.",
            {"case_id": _STR}, ["case_id"],
        ),
        tool_get_case_details,
    ),
}


def specs(names: list[str] | None = None) -> list[dict]:
    """OpenAI tool specs, optionally filtered to a named subset."""
    if names is None:
        return [spec for spec, _ in TOOLS.values()]
    return [TOOLS[n][0] for n in names if n in TOOLS]


def execute(name: str, arguments: dict) -> dict:
    """Run one tool. Errors are returned to the model, not raised, so it can
    recover (e.g. by fixing an argument) rather than aborting the run."""
    entry = TOOLS.get(name)
    if entry is None:
        return {"error": f"unknown tool '{name}'", "available": sorted(TOOLS)}
    _, fn = entry
    try:
        return fn(**arguments)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:
        log.exception("Tool %s failed", name)
        return {"error": f"{name} failed: {exc}"}


def serialise(result: dict, limit: int = 4000) -> str:
    text = json.dumps(result, default=str, ensure_ascii=False)
    if len(text) > limit:
        text = text[:limit] + '..."TRUNCATED"'
    return text
