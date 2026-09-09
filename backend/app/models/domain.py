from datetime import date
from enum import Enum

from pydantic import BaseModel


class MatchSource(str, Enum):
    DESC = "DESC"
    WBS = "WBS"
    COT = "COT"
    DCCS_HISTORY = "DCCS_HISTORY"
    ONE_WINDOW = "ONE_WINDOW"  # stub only


class BusinessUnitNature(str, Enum):
    AUDIT = "Audit"
    ASSURANCE = "Assurance"
    NON_ASSURANCE = "Non-Assurance"


class MatchStatus(str, Enum):
    ONGOING = "Ongoing"
    COMPLETED = "Completed"
    PURSUING = "Pursuing"


class RiskTier(str, Enum):
    """How much reviewer attention a match warrants.

    The point of triage is that a reviewer reads HIGH first and may never need
    to read LOW at all — see `rules_engine.assess_risk_tier`.
    """

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class EntityMatch(BaseModel):
    source: MatchSource
    matched_name: str
    query_name: str
    similarity: float  # 0.0 - 1.0
    country: str | None = None
    designation_type: str | None = None  # DESC
    gup_name: str | None = None  # DESC
    partner_name: str | None = None  # WBS / COT / DCCS
    practice_office: str | None = None
    business_unit: BusinessUnitNature | None = None
    status: MatchStatus | None = None
    entity_role: str | None = None  # DCCS history: Client, GUP, Intermediate Parent...
    match_date: date | None = None
    include_in_summary: bool = True
    exclusion_reason: str | None = None
    rule_citation: str | None = None
    raw: dict = {}


class RuleChunk(BaseModel):
    chunk_id: str
    slide_number: int
    title: str
    source_db: str  # DESC | WBS | COT | ONE_WINDOW | DCCS_SEARCH | CROSS_BORDER | GENERAL | FOOTER
    chunk_type: str  # narrative | decision_table
    text: str
    score: float | None = None


class QCFlag(BaseModel):
    severity: str  # WARN | INFO
    message: str
    action: str | None = None
    rule_citation: str | None = None


class CrossBorderAction(BaseModel):
    jurisdiction: str
    outcome: str
    reason: str | None = None
    rule_citation: str | None = None


class CasePartyDTO(BaseModel):
    entity_name: str
    party_side: str  # CLIENT_SIDE | OTHER_SIDE
    entity_role: str | None = None
    entity_type: str | None = None
    abbreviated_names: str | None = None
    dgmf_id: str | None = None
    address: str | None = None
    location: str | None = None
    stated_designation: str | None = None
    is_gup: bool = False


class GoldenCaseDTO(BaseModel):
    case_id: str
    request_id: str
    final_result: str | None = None
    conditions: list[str] = []
    analyst_comments: list[str] = []
    cross_border: list[dict] = []
