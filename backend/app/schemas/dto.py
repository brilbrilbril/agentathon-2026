"""API DTOs — the contract Dev A and Dev B build against (DEV_C §1).

These never expose SQLAlchemy objects (C3).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

# ---------------- Errors ----------------

class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------------- Cases ----------------

class PartyDTO(BaseModel):
    entity_name: str
    party_side: str = "CLIENT_SIDE"
    entity_role: str | None = None
    entity_type: str | None = None
    location: str | None = None
    stated_designation: str | None = None
    is_gup: bool = False


class CaseSummaryDTO(BaseModel):
    case_id: str
    request_id: str | None = None
    service_offering: str | None = None
    location: str | None = None
    date_submitted: date | None = None
    party_count: int = 0
    has_golden: bool = False
    latest_screening_status: str | None = None


class CaseListDTO(BaseModel):
    items: list[CaseSummaryDTO]
    total: int


class CaseDetailDTO(BaseModel):
    case_id: str
    request_id: str | None = None
    request_type: str | None = None
    originator: str | None = None
    member_firm: str | None = None
    location: str | None = None
    office: str | None = None
    service_offering: str | None = None
    engagement_name: str | None = None
    engagement_details: str | None = None
    is_recurring: bool = False
    is_inbound_referral: bool = False
    has_iwrf: bool = False
    lead_partner: str | None = None
    lead_manager: str | None = None
    date_submitted: date | None = None
    parties: list[PartyDTO] = []


class CaseCreateDTO(BaseModel):
    request_id: str
    service_offering: str | None = None
    engagement_name: str | None = None
    engagement_details: str | None = None
    location: str | None = None
    member_firm: str | None = None
    office: str | None = None
    originator: str | None = None
    request_type: str | None = "Conflict Check Request"
    is_recurring: bool = False
    is_inbound_referral: bool = False
    has_iwrf: bool = False
    lead_partner: str | None = None
    lead_manager: str | None = None
    date_submitted: date | None = None
    parties: list[PartyDTO] = Field(default_factory=list)


# ---------------- Screening ----------------

class QCFlagDTO(BaseModel):
    severity: str
    message: str
    action: str | None = None
    rule_citation: str | None = None


class MatchRowDTO(BaseModel):
    entity_name: str | None = None
    source: str
    country: str | None = None
    designation_type: str | None = None
    gup_name: str | None = None
    lcsp_rp: str | None = None
    partner_name: str | None = None
    practice_office: str | None = None
    business_unit: str | None = None
    status: str | None = None
    entity_role: str | None = None
    match_date: str | None = None
    similarity: float | None = None
    exclusion_reason: str | None = None
    note: str | None = None
    rule_citation: str | None = None
    risk_tier: str | None = None
    risk_reason: str | None = None


class CrossBorderActionDTO(BaseModel):
    jurisdiction: str
    outcome: str
    reason: str | None = None
    rule_citation: str | None = None


class UncheckedSourceDTO(BaseModel):
    source: str
    reason: str


class ScreeningStartedDTO(BaseModel):
    screening_id: str
    status: str


class ScreeningResultDTO(BaseModel):
    screening_id: str
    case_id: str
    status: str
    final_result: str | None = None
    quality_check_flags: list[QCFlagDTO] = []
    summary_table: list[MatchRowDTO] = []
    risk_summary: dict[str, int] = {}
    possible_matches: list[MatchRowDTO] = []
    excluded_matches: list[MatchRowDTO] = []
    conditions: list[str] = []
    cross_border_actions: list[CrossBorderActionDTO] = []
    unchecked_sources: list[UncheckedSourceDTO] = []
    draft_response: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class DraftResponseDTO(BaseModel):
    draft_response: str | None = None
    format: str = "markdown"


# ---------------- Eval ----------------

class GoldenDTO(BaseModel):
    request_id: str
    final_result: str | None = None
    conditions: list[str] = []
    analyst_comments: list[str] = []
    cross_border: list[dict] = []


class EvalCheckDTO(BaseModel):
    name: str
    expected: str
    actual: str
    passed: bool


class EvalResultDTO(BaseModel):
    case_id: str
    screening_id: str
    score: str
    passed: int
    total: int
    checks: list[EvalCheckDTO]


# ---------------- Search / rules ----------------

class EntityMatchDTO(BaseModel):
    source: str
    matched_name: str
    query_name: str
    similarity: float
    country: str | None = None
    designation_type: str | None = None
    gup_name: str | None = None
    partner_name: str | None = None
    practice_office: str | None = None
    business_unit: str | None = None
    status: str | None = None
    entity_role: str | None = None
    match_date: date | None = None
    include_in_summary: bool = True
    exclusion_reason: str | None = None
    rule_citation: str | None = None


class EntitySearchDTO(BaseModel):
    query: str
    results: dict[str, list[EntityMatchDTO]]


class RuleChunkDTO(BaseModel):
    chunk_id: str
    slide_number: int
    title: str | None = None
    source_db: str
    chunk_type: str
    text: str
    score: float | None = None


class RuleSearchDTO(BaseModel):
    results: list[RuleChunkDTO]


# ---------------- Chat ----------------

class ChatRequestDTO(BaseModel):
    session_id: str | None = None
    case_id: str | None = None
    message: str


class AgentTraceDTO(BaseModel):
    agent: str
    summary: str | None = None
    tool_calls: list[dict] = []


class CitationDTO(BaseModel):
    slide_number: int
    title: str | None = None


class ChatReplyDTO(BaseModel):
    session_id: str
    reply: str
    agent_trace: list[AgentTraceDTO] = []
    citations: list[CitationDTO] = []


class SuggestedQuestionDTO(BaseModel):
    category: str
    question: str


class ChatMessageDTO(BaseModel):
    role: str
    content: str
    agent_name: str | None = None
    tool_calls: list[dict] = []
    created_at: datetime | None = None


# ---------------- Meta ----------------

class HealthDTO(BaseModel):
    status: str
    postgres: bool
    llm: bool


class StatsDTO(BaseModel):
    desc_entities: int
    wbs_engagements: int
    cot_requests: int
    dccs_search_results: int
    rule_chunks: int
    cases: int
    screenings: int
