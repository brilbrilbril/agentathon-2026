"""Integration tests against the ingested Postgres data (run_ingestion.py
must have been run first)."""

from app.repositories.entity_search import normalise_name, search_all, search_desc


def test_search_all_hits_all_four_sources(db_session):
    results = search_all(db_session, "KDDI Corporation")
    assert len(results["DESC"]) > 0
    assert len(results["WBS"]) > 0
    assert len(results["COT"]) > 0
    assert len(results["DCCS_HISTORY"]) > 0


def test_desc_designation_parsing(db_session):
    matches = search_desc(db_session, "KDDI Corporation", threshold=0.5)
    hit = next(m for m in matches if m.matched_name == "KDDI CORPORATION")
    assert "Audit Team Restricted" in hit.designation_type
    assert "Relationship" in hit.designation_type


def test_fuzzy_name_bridging_kddi_thailand(db_session):
    """The request's 'KDDI (Thailand) Limited' must match DESC's
    'KDDI (THAILAND) COMPANY LIMITED' above the review threshold —
    required for the demo case to work (DEV_A §4.1)."""
    matches = search_desc(db_session, "KDDI (Thailand) Limited", threshold=0.0)
    assert matches, "no DESC candidates returned at all"
    best = max(matches, key=lambda m: m.similarity)
    assert best.matched_name == "KDDI (THAILAND) COMPANY LIMITED"
    assert best.similarity >= 0.65


def test_normalise_name_strips_legal_suffixes():
    assert "LIMITED" not in normalise_name("Something Limited")
    assert "CORPORATION" not in normalise_name("KDDI Corporation")
