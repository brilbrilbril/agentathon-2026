"""Deterministic QRC rule lookups. Never LLM reasoning here — see MASTER §7.

Every function returns its result plus the QRC slide citation that governs it.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.config import settings
from app.models.domain import BusinessUnitNature, MatchStatus, QCFlag

# The designations seen in the sample data. This list is a *reference*, not a
# gate: a different dataset will carry designations that are not here, so
# nothing may depend on membership. Recognition is by meaning (does the label
# say "restricted"?) and anything unrecognised is escalated, never dropped.
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

# Substrings that mark a designation as carrying independence risk. Matching on
# the word rather than the full label means a new dataset's
# "Sanctions Restricted" or "PIE Restricted" is still caught.
_RESTRICTED_MARKERS = ("restricted", "prohibited", "banned")

# Designations that need a condition but are not independence-restrictions.
_CONDITION_MARKERS = ("relationship", "watchlist", "loan rule", "monitor")


def is_known_designation(designation: str) -> bool:
    """Whether a designation label was seen in the reference vocabulary.

    Used only to decide whether to *flag* something as unfamiliar — never to
    decide whether it matters.
    """
    normalised = designation.strip().lower()
    return any(normalised == known.lower() for known in _KNOWN_DESIGNATIONS)


def _squash(value: str | None) -> str:
    """Lowercase and collapse whitespace, so label formatting differences
    between datasets don't change a verdict."""
    return re.sub(r"\s+", " ", (value or "").strip().lower())


# Service lines slide 6 explicitly routes to Non-Assurance.
_NON_ASSURANCE_L1_MARKERS = ("t&l", "tax", "sr&t", "t&t", "technology", "consulting", "legal")


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
    l1_norm = _squash(l1)
    l4_norm = _squash(l4)
    text_norm = (wbs_text or "").lower()

    if not l1_norm.startswith("audit") and "a&a" not in l1_norm:
        if l1 and not any(k in l1_norm for k in _NON_ASSURANCE_L1_MARKERS):
            # Slide 6 enumerates T&L / SR&T / T&T and A&A. A service line
            # outside those is not covered by the rule, so say the verdict is
            # an assumption rather than presenting it as the rulebook's.
            return (
                BusinessUnitNature.NON_ASSURANCE,
                f"{citation} (assumed — service line '{l1}' is not covered by slide 6)",
            )
        return BusinessUnitNature.NON_ASSURANCE, citation

    # Matched on content rather than an exact label so a dataset that writes
    # 'A&A: AUD - Large & Complex' or reorders the prefix still classifies.
    is_large_complex = "aud" in l4_norm and "large" in l4_norm and "complex" in l4_norm
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
    """True when any designation carries an independence restriction.

    Matches on the marker word, so a designation this codebase has never seen
    ('Sanctions Restricted') is still treated as restricted.
    """
    if not designation_type:
        return False
    text = designation_type.lower()
    return any(marker in text for marker in _RESTRICTED_MARKERS)


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


def assess_risk_tier(
    source: str,
    designation_type: str | None = None,
    business_unit: str | None = None,
    status: str | None = None,
    has_desc_contradiction: bool = False,
) -> tuple[str, str, str]:
    """Triage a match by how much reviewer attention it warrants.

    Returns (tier, reason, citation).

    This is the difference between handing a reviewer a flat list and handing
    them a worklist. It is deliberately deterministic and derived only from
    verdicts other QRC rules already produced, so a tier can always be
    explained and never drifts between runs.

        HIGH   — independence risk: a Restricted designation in DESC (slide 5),
                 an Audit engagement (slide 6), or DESC contradicting the
                 request (slide 4).
        MEDIUM — a condition is likely: Relationship / Watchlist / Loan Rule
                 designations, or an Assurance engagement.
        LOW    — record it, but it does not by itself change the outcome:
                 ongoing Non-Assurance work and prior DCCS activity.
    """
    citation = "QRC slides 4, 5, 6 (risk triage)"

    if has_desc_contradiction:
        return (
            "High",
            "DESC contradicts the designation stated on the request — DESC is authoritative (slide 4)",
            citation,
        )

    if _has_restricted_designation(designation_type):
        restricted = [
            d for d in parse_desc_designations(designation_type)
            if any(m in d.lower() for m in _RESTRICTED_MARKERS)
        ]
        return (
            "High",
            f"DESC records a Restricted designation ({', '.join(restricted)}) — independence risk (slide 5)",
            citation,
        )

    if business_unit == BusinessUnitNature.AUDIT.value:
        return "High", "Audit engagement — independence risk (slide 6)", citation

    designations = parse_desc_designations(designation_type)
    if any(any(m in d.lower() for m in _CONDITION_MARKERS) for d in designations):
        return (
            "Medium",
            f"DESC designation '{', '.join(designations)}' requires a condition (slide 5)",
            citation,
        )

    # A designation this build has never seen must not be quietly treated as
    # harmless — a new dataset will carry labels that are not in the reference
    # vocabulary, and under-triaging one is a compliance failure. Escalate and
    # say why, so a reviewer decides rather than the parser.
    unfamiliar = [d for d in designations if not is_known_designation(d)]
    if unfamiliar:
        return (
            "Medium",
            (
                f"Unrecognised DESC designation '{', '.join(unfamiliar)}' — not in the known "
                "vocabulary, so it has not been risk-assessed. Reviewer to confirm (slide 5)"
            ),
            citation,
        )

    if business_unit == BusinessUnitNature.ASSURANCE.value:
        return "Medium", "Assurance engagement — confirm scope (slide 6)", citation

    # Same reasoning for an unfamiliar business unit.
    known_units = {u.value for u in BusinessUnitNature}
    if business_unit and business_unit not in known_units:
        return (
            "Medium",
            (
                f"Unrecognised business unit '{business_unit}' — could not be classified "
                "against slide 6. Reviewer to confirm"
            ),
            citation,
        )

    if source == "DCCS_HISTORY":
        return "Low", "Prior DCCS activity — contextual, no designation attached (slide 10)", citation

    if business_unit == BusinessUnitNature.NON_ASSURANCE.value:
        label = status or "engagement"
        return "Low", f"Non-Assurance {label.lower()} — record only (slide 6)", citation

    return "Low", "No designation or engagement signal that raises risk", citation


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
