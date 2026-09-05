from datetime import date

from app.models.domain import BusinessUnitNature, MatchStatus
from app.rules.rules_engine import (
    classify_wbs_business_unit,
    classify_wbs_status,
    compare_stated_vs_desc_designation,
    evaluate_cross_border,
    is_cot_match_acknowledged,
    is_dccs_match_relevant,
    parse_desc_designations,
)


def test_wbs_canary_non_assurance_not_audit():
    """The WBS row that separates a real rules engine from a plausible one
    (MASTER §9). L1 is A&A but L4 is ASV-Accounting & Reporting, not
    AUD-Large & Complex — must fall through to Non-Assurance."""
    nature, citation = classify_wbs_business_unit(
        "Audit & Assurance", "A&A: ASV-Accounting & Reporting", "KDDI - BCC ACCOUNTING ADVISORY"
    )
    assert nature == BusinessUnitNature.NON_ASSURANCE
    assert "slide 6" in citation


def test_wbs_audit_requires_large_complex_and_statutory_text():
    nature, _ = classify_wbs_business_unit(
        "Audit & Assurance", "A&A: AUD-Large & Complex", "Statutory audit for FY2025"
    )
    assert nature == BusinessUnitNature.AUDIT


def test_wbs_assurance_requires_large_complex_and_assurance_text():
    nature, _ = classify_wbs_business_unit(
        "Audit & Assurance", "A&A: AUD-Large & Complex", "ISAE 3402 attestation engagement"
    )
    assert nature == BusinessUnitNature.ASSURANCE


def test_wbs_tax_and_legal_is_non_assurance():
    nature, _ = classify_wbs_business_unit("Tax & Legal", "T&L: DT-Business Tax Advisory", "some text")
    assert nature == BusinessUnitNature.NON_ASSURANCE


def test_wbs_status_released_is_ongoing_and_included():
    status, include, reason, _ = classify_wbs_status("Released", None, None)
    assert status == MatchStatus.ONGOING
    assert include is True
    assert reason is None


def test_wbs_status_technically_completed_excluded_by_default():
    status, include, reason, _ = classify_wbs_status(
        "Technically Completed", date(2020, 1, 1), "Audit Team Restricted"
    )
    assert status == MatchStatus.COMPLETED
    assert include is False
    assert reason is not None


def test_wbs_status_technically_completed_included_if_recent_audit_and_restricted():
    status, include, reason, _ = classify_wbs_status(
        "Technically Completed", date.today(), "Audit Team Restricted"
    )
    assert include is True


def test_cot_cutoff_excludes_before_date():
    from datetime import datetime

    include, reason, citation = is_cot_match_acknowledged(datetime(2025, 6, 1))
    assert include is False
    assert "cutoff" in reason
    assert "slide 9" in citation


def test_cot_included_after_cutoff():
    from datetime import datetime

    include, reason, _ = is_cot_match_acknowledged(datetime(2025, 8, 1))
    assert include is True
    assert reason is None


def test_parse_desc_designations_comma_split():
    result = parse_desc_designations("Audit Team Restricted, Relationship")
    assert result == ["Audit Team Restricted", "Relationship"]


def test_parse_desc_designations_empty():
    assert parse_desc_designations(None) == []
    assert parse_desc_designations("") == []


def test_dccs_staleness_excludes_old_rows():
    include, reason, citation = is_dccs_match_relevant(date(2015, 1, 1), "Approved with Conditions", False)
    assert include is False
    assert "years" in reason
    assert "slide 10" in citation


def test_dccs_excludes_opportunity_lost_and_engagement_complete():
    include, _, _ = is_dccs_match_relevant(date.today(), "Opportunity Lost", False)
    assert include is False
    include2, _, _ = is_dccs_match_relevant(date.today(), "Engagement Complete", False)
    assert include2 is False


def test_dccs_dedupe_excludes_already_represented():
    include, reason, _ = is_dccs_match_relevant(date.today(), "Approved with Conditions", True)
    assert include is False
    assert "deduped" in reason.lower()


def test_dccs_relevant_match_included_as_pursuing():
    include, reason, _ = is_dccs_match_relevant(date.today(), "Approved with Conditions", False)
    assert include is True
    assert reason is None


def test_cross_border_japan_not_required_when_gup_in_desc():
    """Sanity check against the sample case (MASTER §9 / §5.13)."""
    decision = evaluate_cross_border(client_in_desc=True, gup_in_desc=True, client_is_gup=False, jurisdiction="Japan")
    assert decision.outcome == "Request Not Required"


def test_cross_border_required_when_neither_in_desc():
    decision = evaluate_cross_border(client_in_desc=False, gup_in_desc=False, client_is_gup=False, jurisdiction="Vietnam")
    assert decision.outcome == "Request Required"


def test_desc_contradiction_caught():
    """The sample case's canary: request says Restricted, DESC says
    Audit Team Restricted, Relationship."""
    flag = compare_stated_vs_desc_designation("Restricted", "Audit Team Restricted, Relationship")
    assert flag is not None
    assert flag.severity == "WARN"
    assert "SEAIndependence@deloitte.com" in flag.action
    assert "slide 4" in flag.rule_citation


def test_desc_no_flag_when_consistent():
    assert compare_stated_vs_desc_designation("Relationship", "Relationship") is None


def test_desc_no_flag_when_stated_is_subset_of_desc():
    assert compare_stated_vs_desc_designation("Relationship", "Audit Team Restricted, Relationship") is None
