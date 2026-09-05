from sqlalchemy import text


def test_ingestion_counts(db_session):
    counts = {}
    for table in ("desc_entities", "wbs_engagements", "cot_requests", "dccs_search_results", "case_parties", "rule_chunks"):
        counts[table] = db_session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

    assert counts["desc_entities"] > 0
    assert counts["wbs_engagements"] > 0
    assert counts["cot_requests"] > 0
    assert counts["dccs_search_results"] > 1000, "DCCS history should be in the thousands (MASTER §2.3)"
    assert counts["case_parties"] == 3
    assert counts["rule_chunks"] >= 10


def test_dependency_hygiene():
    """No Qdrant, no sentence-transformers, no torch anywhere (MASTER §3)."""
    import importlib.metadata as md

    banned = {"torch", "qdrant-client", "sentence-transformers", "chromadb", "faiss", "faiss-cpu"}
    installed = {d.metadata["Name"].lower() for d in md.distributions()}
    hits = banned & installed
    assert not hits, f"banned dependencies present: {hits}"
