"""Unit tests against the saved text fixture — never re-run pdftotext on the
82MB source PDF in tests (DEV_A §3.2)."""

from app.ingestion.pdf_loader import parse_dccs_export


def test_parse_case_header(case_text):
    parsed = parse_dccs_export(case_text)
    assert parsed.request_id == "12246557"
    assert parsed.request_type == "Conflict Check Request"
    assert parsed.location == "Malaysia (MY)"
    assert parsed.service_offering == "Technology & Transformation \\ Human Capital \\ Organization & Work Transformation"
    assert "JO-9671950" in parsed.engagement_name
    assert "HR Transformation" in parsed.engagement_name


def test_parse_exactly_three_case_parties(case_text):
    parsed = parse_dccs_export(case_text)
    assert len(parsed.parties) == 3
    roles = {p["entity_role"] for p in parsed.parties}
    assert roles == {"Client", "Shareholder", "Global Ultimate Parent"}


def test_case_party_designations_match_ground_truth(case_text):
    parsed = parse_dccs_export(case_text)
    by_name = {p["entity_name"]: p for p in parsed.parties}
    assert by_name["KDDI (Thailand) Limited"]["stated_designation"] == "Do Not Know"
    assert by_name["KDDI Asia Pacific Pte Ltd"]["stated_designation"] == "Relationship"
    assert by_name["KDDI CORPORATION"]["stated_designation"] == "Restricted"
    assert by_name["KDDI CORPORATION"]["is_gup"] is True


def test_dccs_history_row_count_in_thousands(case_text):
    parsed = parse_dccs_export(case_text)
    assert len(parsed.dccs_rows) > 1000


def test_golden_case_matches_analyst_determination(case_text):
    parsed = parse_dccs_export(case_text)
    assert parsed.golden["final_result"] == "Approved with Conditions"
    assert parsed.golden["conditions"] == ["Relationship client in DESC"]
    assert "Listed in DESC" in parsed.golden["analyst_comments"]
    assert "Local WBS: Non-Assurance" in parsed.golden["analyst_comments"]
    cb = parsed.golden["cross_border"]
    assert len(cb) == 1
    assert cb[0]["jurisdiction"] == "Japan"
    assert cb[0]["outcome"] == "Request Not Required"
