"""Shared graph state (DEV_B §2)."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel

from app.models.domain import BusinessUnitNature, EntityMatch, MatchStatus


class Party(BaseModel):
    entity_name: str
    entity_role: str | None = None
    location: str | None = None
    stated_designation: str | None = None
    is_gup: bool = False
    party_side: str = "CLIENT_SIDE"


class ClassifiedMatch(BaseModel):
    """An EntityMatch after the rules agent has attached a verdict."""

    source: str
    entity_name: str
    query_name: str
    similarity: float
    country: str | None = None
    designation_type: str | None = None
    gup_name: str | None = None
    partner_name: str | None = None
    practice_office: str | None = None
    business_unit: BusinessUnitNature | None = None
    status: MatchStatus | None = None
    entity_role: str | None = None
    match_date: object = None
    include_in_summary: bool = True
    exclusion_reason: str | None = None
    rule_citation: str | None = None
    risk_tier: str | None = None
    risk_reason: str | None = None
    raw: dict = {}

    @classmethod
    def from_entity_match(cls, m: EntityMatch, **overrides) -> ClassifiedMatch:
        data = {
            "source": m.source.value if hasattr(m.source, "value") else str(m.source),
            "entity_name": m.matched_name,
            "query_name": m.query_name,
            "similarity": m.similarity,
            "country": m.country,
            "designation_type": m.designation_type,
            "gup_name": m.gup_name,
            "partner_name": m.partner_name,
            "practice_office": m.practice_office,
            "business_unit": m.business_unit,
            "status": m.status,
            "entity_role": m.entity_role,
            "match_date": m.match_date,
            "include_in_summary": m.include_in_summary,
            "exclusion_reason": m.exclusion_reason,
            "rule_citation": m.rule_citation,
            "risk_tier": None,
            "risk_reason": None,
            "raw": {},
        }
        data.update(overrides)
        return cls(**data)


class ScreeningState(TypedDict, total=False):
    case_id: str
    request_id: str | None
    service_offering: str | None
    engagement_details: str | None
    location: str | None
    is_inbound_referral: bool
    has_iwrf: bool
    parties: list[dict]

    quality_check_flags: Annotated[list, operator.add]
    raw_matches: Annotated[list, operator.add]
    applicable_rules: Annotated[list, operator.add]

    classified_matches: list
    possible_matches: list
    cross_border: list
    unchecked_sources: list
    conditions: list
    summary_table: list
    final_result: str | None
    draft_response: str | None
    search_plan: list
    search_findings: str | None
    rules_findings: str | None
    agent_trace: Annotated[list, operator.add]
