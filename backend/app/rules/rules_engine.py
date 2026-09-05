"""Deterministic QRC rule lookups. Never LLM reasoning here — see MASTER §7.

Every function returns its result plus the QRC slide citation that governs it.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.config import settings
from app.models.domain import BusinessUnitNature, MatchStatus, QCFlag

_KNOWN_DESIGNATIONS = [
    "Relationship",
    "DTT Restricted",
    "SEC Restricted",
    "EUPIE Restricted",
    "Reverse Restricted",
    "Watchlist",
    "Loan Rule",
    "Business Relationship Restricted",
    "Audit Team Restricted",
]

_RESTRICTED_KEYWORDS = (
    "DTT Restricted",
    "SEC Restricted",
    "EUPIE Restricted",
    "Reverse Restricted",
    "Business Relationship Restricted",
    "Audit Team Restricted",
)


def classify_wbs_business_unit(l1: str | None, l4: str | None, wbs_text: str | None) -> tuple[BusinessUnitNature, str]:
    """QRC slide 6.

    T&L / SR&T / T&T                                     -> NON_ASSURANCE
    A&A + l4 == 'A&A: AUD-Large & Complex' and wbs_text
        contains 'Statutory' or 'Financial Statement'    -> AUDIT
    A&A + same l4 and wbs_text contains
        'Assurance' | 'Attestation' | 'ISAE'              -> ASSURANCE
    any other A&A                                         -> NON_ASSURANCE
    """
    citation = "QRC slide 6"
    l1_norm = (l1 or "").strip().lower()
    l4_norm = (l4 or "").strip().lower()
    text_norm = (wbs_text or "").lower()

    if not l1_norm.startswith("audit") and "a&a" not in l1_norm:
        return BusinessUnitNature.NON_ASSURANCE, citation

    is_large_complex = l4_norm == "a&a: aud-large & complex"
    if is_large_complex and any(k in text_norm for k in ("statutory", "financial statement")):
        return BusinessUnitNature.AUDIT, citation
    if is_large_complex and any(k in text_norm for k in ("assurance", "attestation", "isae")):
        return BusinessUnitNature.ASSURANCE, citation

    return BusinessUnitNature.NON_ASSURANCE, citation


def classify_wbs_status(
    status: str | None,
    complete_date: date | None,
    desc_designation: str | None,
) -> tuple[MatchStatus, bool, str | None, str]:
    """QRC slide 6. Returns (status, include, exclusion_reason, citation)."""
    citation = "QRC slide 6"
    status_norm = (status or "").strip().lower()

    if status_norm == "released":
        return MatchStatus.ONGOING, True, None, citation

    if status_norm == "technically completed":
        is_recent = (
            complete_date is not None
            and (date.today() - complete_date) <= timedelta(days=settings.WBS_RECENT_COMPLETION_DAYS)
        )
        is_still_restricted = _has_restricted_designation(desc_designation)
        if is_recent and is_still_restricted:
            return MatchStatus.COMPLETED, True, None, citation
        return (
            MatchStatus.COMPLETED,
            False,
            "Technically Completed and not a recent audit engagement on a still-Restricted entity",
            citation,
        )

    return MatchStatus.COMPLETED, False, f"Unrecognised WBS status '{status}'", citation


def is_cot_match_acknowledged(submission_time) -> tuple[bool, str | None, str]:
    """QRC slide 9. Before COT_CUTOFF_DATE -> excluded.

    Acknowledged COT matches are always ONGOING and NON_ASSURANCE (Tax BU).
    """
    citation = "QRC slide 9"
    if submission_time is None:
        return False, "No submission time recorded for COT request", citation

    submission_date = submission_time.date() if hasattr(submission_time, "date") else submission_time
    if submission_date < settings.COT_CUTOFF_DATE:
        return False, f"COT submission ({submission_date}) predates cutoff {settings.COT_CUTOFF_DATE}", citation

    return True, None, citation


def parse_desc_designations(designation_type: str | None) -> list[str]:
    """Comma-split, matching against the known designation vocabulary.

    Recognised: Relationship, DTT Restricted, SEC Restricted, EUPIE Restricted,
    Reverse Restricted, Watchlist, Loan Rule, Business Relationship Restricted,
    Audit Team Restricted.
    """
    if not designation_type:
        return []
    parts = [p.strip() for p in designation_type.split(",") if p.strip()]
    return parts


def _has_restricted_designation(designation_type: str | None) -> bool:
    if not designation_type:
        return False
    text = designation_type.lower()
    return any(k.lower() in text for k in _RESTRICTED_KEYWORDS)


def is_dccs_match_relevant(
    request_date: date | None,
    status: str | None,
    already_in_other_source: bool,
) -> tuple[bool, str | None, str]:
    """QRC slide 10.

    older than DCCS_STALENESS_YEARS                       -> exclude
    status in ('Engagement Complete','Opportunity Lost')   -> exclude
    already captured in WBS/One Window                    -> exclude (dedupe)
    otherwise                                              -> include as PURSUING
    """
    citation = "QRC slide 10"

    if already_in_other_source:
        return False, "Already represented in a WBS or COT match (deduped)", citation

    status_norm = (status or "").strip().lower()
    if status_norm in ("engagement complete", "opportunity lost"):
        return False, f"DCCS status '{status}' is excluded per slide 10", citation

    if request_date is not None:
        cutoff = date(date.today().year - settings.DCCS_STALENESS_YEARS, date.today().month, date.today().day)
        if request_date < cutoff:
            return False, f"DCCS request dated {request_date} is older than {settings.DCCS_STALENESS_YEARS} years", citation

    return True, None, citation


class CrossBorderDecision:
    def __init__(self, jurisdiction: str, outcome: str, reason: str, citation: str):
        self.jurisdiction = jurisdiction
        self.outcome = outcome
        self.reason = reason
        self.rule_citation = citation

    def to_dict(self) -> dict:
        return {
            "jurisdiction": self.jurisdiction,
            "outcome": self.outcome,
            "reason": self.reason,
            "rule_citation": self.rule_citation,
        }


def evaluate_cross_border(
    client_in_desc: bool,
    gup_in_desc: bool,
    client_is_gup: bool,
    jurisdiction: str = "",
) -> CrossBorderDecision:
    """QRC slide 11 matrix, transcribed.

    If the client or GUP is listed in DESC, no additional cross-border steps
    are required (the receiving member firm already has visibility via DESC).
    Otherwise a cross-border / logging request must be sent. A Logging Request
    is used specifically when the client entity is listed in DESC as
    Relationship or Restricted.
    """
    citation = "QRC slide 11"

    if gup_in_desc or client_in_desc or client_is_gup:
        return CrossBorderDecision(
            jurisdiction=jurisdiction,
            outcome="Request Not Required",
            reason="GUP/Client already listed in DESC" if (gup_in_desc or client_in_desc) else "Client is the GUP",
            citation=citation,
        )

    return CrossBorderDecision(
        jurisdiction=jurisdiction,
        outcome="Request Required",
        reason="Neither client nor GUP is listed in DESC — cross-border check required",
        citation=citation,
    )


def compare_stated_vs_desc_designation(stated: str | None, desc_designation: str | None) -> QCFlag | None:
    """QRC slide 4. DESC is authoritative.

    If the request's stated designation differs from what DESC records,
    return a WARN flag naming the escalation path.
    """
    citation = "QRC slide 4"
    stated_norm = (stated or "").strip().lower()
    desc_norm = (desc_designation or "").strip().lower()

    if not stated_norm or not desc_norm:
        return None
    if stated_norm == desc_norm:
        return None
    if stated_norm in [d.strip().lower() for d in desc_norm.split(",")]:
        return None

    return QCFlag(
        severity="WARN",
        message=(
            f"Request states designation as '{stated}'; DESC shows '{desc_designation}'. "
            "DESC is authoritative."
        ),
        action=(
            "Contact requestor to clarify; if the requestor confirms the submitted value, "
            "escalate to SEAIndependence@deloitte.com copying the assigned Senior Analysts "
            "from the Conflicts and DESC teams"
        ),
        rule_citation=citation,
    )
