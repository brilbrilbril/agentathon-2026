"""Two-stage entity matching: pg_trgm prefilter -> rapidfuzz rerank (A5).

No embeddings, no vector DB — see MASTER §3. This is string similarity.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.domain import BusinessUnitNature, EntityMatch, MatchSource, MatchStatus

# Legal-form suffixes stripped before comparing names. SEA forms first, then
# common international ones — a dataset covering new regions should have its
# forms added here rather than silently matching worse.
_LEGAL_SUFFIXES = [
    # SEA
    "CO., LTD", "CO LTD", "COMPANY LIMITED", "LIMITED", "LTD", "CORPORATION",
    "CORP", "PTE LTD", "PTE. LTD.", "SDN BHD", "BHD", "TBK", "PT", "PLC",
    "K.K.", "KK", "CO., LTD.", "PUBLIC COMPANY LIMITED",
    # International
    "INC", "INCORPORATED", "LLC", "L.L.C.", "L.P.", "LP", "LLP", "GMBH",
    "AG", "SA", "S.A.", "SAS", "BV", "B.V.", "NV", "N.V.", "AB", "AS",
    "OY", "SPA", "S.P.A.", "SRL", "S.R.L.", "PTY LTD", "PTY", "GROUP",
    "HOLDINGS", "HOLDING",
]

_PUNCT_RE = re.compile(r"[.,()\-]")
_WS_RE = re.compile(r"\s+")


def normalise_name(name: str) -> str:
    """Uppercase; strip legal suffixes; collapse punctuation and whitespace.
    Does NOT strip non-ASCII — aliases include non-Latin scripts (A6)."""
    if not name:
        return ""
    text_ = name.upper()
    text_ = _PUNCT_RE.sub(" ", text_)
    text_ = _WS_RE.sub(" ", text_).strip()
    for suffix in _LEGAL_SUFFIXES:
        pattern = rf"\b{re.escape(suffix)}\b$"
        text_ = re.sub(pattern, "", text_).strip()
    return _WS_RE.sub(" ", text_).strip()


def _score(query: str, candidate: str) -> float:
    """token_set_ratio handles word-order/subset differences that plain ratio
    misses, e.g. 'KDDI (THAILAND) COMPANY LIMITED' vs 'KDDI (Thailand) Limited'."""
    return fuzz.token_set_ratio(normalise_name(query), normalise_name(candidate)) / 100.0


def search_desc(session: Session, name: str, threshold: float | None = None, limit: int = 10) -> list[EntityMatch]:
    threshold = threshold if threshold is not None else settings.MATCH_THRESHOLD_REVIEW
    session.execute(text(f"SET pg_trgm.similarity_threshold = {settings.PGTRGM_PREFILTER_THRESHOLD}"))
    rows = session.execute(
        text(
            """
            SELECT * FROM desc_entities
            WHERE legal_name % :q OR alias % :q
               OR legal_name ILIKE '%' || :q || '%'
               OR alias ILIKE '%' || :q || '%'
            LIMIT 200
            """
        ),
        {"q": name},
    ).mappings().all()

    matches = []
    for row in rows:
        score_legal = _score(name, row["legal_name"] or "")
        score_alias = _score(name, row["alias"] or "") if row["alias"] else 0.0
        similarity = max(score_legal, score_alias)
        if similarity < threshold:
            continue
        matches.append(EntityMatch(
            source=MatchSource.DESC,
            matched_name=row["legal_name"],
            query_name=name,
            similarity=similarity,
            country=row["domicile_country"] or row["legal_country"],
            designation_type=row["designation_type"],
            gup_name=row["gup_name"],
            partner_name=row["contact_person"],
            practice_office=row["city"],
            raw=dict(row),
        ))
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:limit]


def search_wbs(session: Session, name: str, threshold: float | None = None, limit: int = 20) -> list[EntityMatch]:
    from app.rules.rules_engine import classify_wbs_business_unit, classify_wbs_status

    threshold = threshold if threshold is not None else settings.MATCH_THRESHOLD_REVIEW
    session.execute(text(f"SET pg_trgm.similarity_threshold = {settings.PGTRGM_PREFILTER_THRESHOLD}"))
    rows = session.execute(
        text(
            """
            SELECT * FROM wbs_engagements
            WHERE client_name_full % :q OR client_name_full ILIKE '%' || :q || '%'
            LIMIT 200
            """
        ),
        {"q": name},
    ).mappings().all()

    matches = []
    for row in rows:
        similarity = _score(name, row["client_name_full"] or "")
        if similarity < threshold:
            continue
        nature, bu_citation = classify_wbs_business_unit(row["market_offering_l1"], row["market_offering_l4"], row["wbs_text"])
        status, include, exclusion_reason, status_citation = classify_wbs_status(
            row["status"], row["wbs_complete_date"], None
        )
        matches.append(EntityMatch(
            source=MatchSource.WBS,
            matched_name=row["client_name_full"],
            query_name=name,
            similarity=similarity,
            country=row["geo"],
            partner_name=row["em_partner_name"],
            practice_office=row["sales_office_text"],
            business_unit=nature,
            status=status,
            match_date=row["wbs_complete_date"] or row["wbs_start_date"],
            include_in_summary=include,
            exclusion_reason=exclusion_reason,
            rule_citation=f"{bu_citation}; {status_citation}",
            raw=dict(row),
        ))
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:limit]


def search_cot(session: Session, name: str, threshold: float | None = None, limit: int = 20) -> list[EntityMatch]:
    from app.rules.rules_engine import is_cot_match_acknowledged

    threshold = threshold if threshold is not None else settings.MATCH_THRESHOLD_REVIEW
    session.execute(text(f"SET pg_trgm.similarity_threshold = {settings.PGTRGM_PREFILTER_THRESHOLD}"))
    rows = session.execute(
        text(
            """
            SELECT * FROM cot_requests
            WHERE client_name % :q OR client_name ILIKE '%' || :q || '%'
            LIMIT 200
            """
        ),
        {"q": name},
    ).mappings().all()

    matches = []
    for row in rows:
        similarity = _score(name, row["client_name"] or "")
        if similarity < threshold:
            continue
        include, exclusion_reason, citation = is_cot_match_acknowledged(row["submission_time"])
        matches.append(EntityMatch(
            source=MatchSource.COT,
            matched_name=row["client_name"],
            query_name=name,
            similarity=similarity,
            country=row["requesting_country"],
            partner_name=row["partner"],
            business_unit=BusinessUnitNature.NON_ASSURANCE if include else None,
            status=MatchStatus.ONGOING if include else None,
            match_date=row["submission_time"].date() if row["submission_time"] else None,
            include_in_summary=include,
            exclusion_reason=exclusion_reason,
            rule_citation=citation,
            raw=dict(row),
        ))
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:limit]


def search_dccs_history(session: Session, name: str, threshold: float | None = None, limit: int = 50) -> list[EntityMatch]:
    threshold = threshold if threshold is not None else settings.MATCH_THRESHOLD_REVIEW
    session.execute(text(f"SET pg_trgm.similarity_threshold = {settings.PGTRGM_PREFILTER_THRESHOLD}"))
    rows = session.execute(
        text(
            """
            SELECT * FROM dccs_search_results
            WHERE entity_name % :q OR entity_name ILIKE '%' || :q || '%'
            LIMIT 500
            """
        ),
        {"q": name},
    ).mappings().all()

    matches = []
    for row in rows:
        similarity = _score(name, row["entity_name"] or "")
        if similarity < threshold:
            continue
        matches.append(EntityMatch(
            source=MatchSource.DCCS_HISTORY,
            matched_name=row["entity_name"],
            query_name=name,
            similarity=similarity,
            entity_role=row["entity_role"],
            partner_name=row["lead_partner"],
            status=None,
            match_date=row["request_date"],
            raw=dict(row),
        ))
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:limit]


def search_one_window(name: str) -> list[EntityMatch]:
    """Stub — no data provided (MASTER §2, §12)."""
    return []


def search_all(session: Session, name: str) -> dict[str, list[EntityMatch]]:
    return {
        MatchSource.DESC.value: search_desc(session, name),
        MatchSource.WBS.value: search_wbs(session, name),
        MatchSource.COT.value: search_cot(session, name),
        MatchSource.DCCS_HISTORY.value: search_dccs_history(session, name),
        MatchSource.ONE_WINDOW.value: search_one_window(name),
    }
