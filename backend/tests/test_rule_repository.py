from app.repositories import rule_repository


def test_get_rules_by_source_wbs_returns_two_chunks(db_session):
    chunks = rule_repository.get_rules_by_source(db_session, "WBS")
    assert len(chunks) == 2


def test_footer_is_present_and_contains_dpm_1420(db_session):
    footer = rule_repository.get_footer_text(db_session)
    assert "DPM 1420" in footer
    assert "Personal Conflicts" in footer
    assert not footer.startswith("[Slide")


def test_cross_border_table_is_decision_table(db_session):
    chunk = rule_repository.get_cross_border_table(db_session)
    assert chunk is not None
    assert chunk.chunk_type == "decision_table"


def test_search_rules_fts(db_session):
    results = rule_repository.search_rules(db_session, "cross border cross-border check")
    assert len(results) > 0
