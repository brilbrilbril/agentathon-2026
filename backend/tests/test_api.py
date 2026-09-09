"""Dev C — FastAPI contract smoke tests."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
PREFIX = "/api/v1"


@pytest.fixture(scope="module")
def case_id() -> str:
    resp = client.get(f"{PREFIX}/cases")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items, "run scripts/run_ingestion.py first"
    return items[0]["case_id"]


def test_health():
    body = client.get(f"{PREFIX}/health").json()
    assert body["status"] == "ok"
    assert body["postgres"] is True


def test_stats_reports_all_four_sources():
    body = client.get(f"{PREFIX}/stats").json()
    assert body["desc_entities"] > 0
    assert body["wbs_engagements"] > 0
    assert body["cot_requests"] > 0
    assert body["dccs_search_results"] > 1000
    assert body["rule_chunks"] >= 10


def test_case_detail_has_three_parties(case_id):
    body = client.get(f"{PREFIX}/cases/{case_id}").json()
    assert body["request_id"] == "12246557"
    assert len(body["parties"]) == 3
    roles = {p["entity_role"] for p in body["parties"]}
    assert roles == {"Client", "Shareholder", "Global Ultimate Parent"}


def test_case_not_found_uses_error_envelope():
    resp = client.get(f"{PREFIX}/cases/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "CASE_NOT_FOUND"
    assert "message" in body["error"]


def test_golden_endpoint(case_id):
    body = client.get(f"{PREFIX}/cases/{case_id}/golden").json()
    assert body["final_result"] == "Approved with Conditions"
    assert body["conditions"] == ["Relationship client in DESC"]


def test_entity_search_hits_all_sources():
    body = client.get(f"{PREFIX}/search/entities", params={"q": "KDDI Corporation", "threshold": 0.8}).json()
    assert len(body["results"]["DESC"]) > 0
    assert len(body["results"]["WBS"]) > 0
    assert len(body["results"]["COT"]) > 0
    assert len(body["results"]["DCCS_HISTORY"]) > 0


def test_rules_listing_and_search():
    all_rules = client.get(f"{PREFIX}/rules").json()["results"]
    assert len(all_rules) >= 10

    hits = client.get(f"{PREFIX}/rules/search", params={"q": "cross border check", "top_k": 2}).json()["results"]
    assert hits
    assert hits[0]["slide_number"] in (11, 12)


def test_chat_returns_a_trace():
    """Chat is a single tool-using agent. Without a reachable inference server
    it degrades to a stated fallback rather than failing."""
    body = client.post(f"{PREFIX}/chat", json={"message": "Why was that DCCS match excluded?"}).json()
    assert body["session_id"]
    assert body["reply"]
    assert body["agent_trace"]
    assert body["agent_trace"][0]["agent"] == "conflict_assistant"


def test_no_upload_endpoint_exists():
    """C11 / MASTER §11 — there must be no file-upload route anywhere."""
    paths = app.openapi()["paths"].keys()
    assert not any("upload" in p for p in paths)


def test_openapi_documents_every_route():
    spec = app.openapi()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            assert op.get("summary"), f"{method.upper()} {path} has no summary"


def test_chat_suggestions_are_operational_questions():
    """The suggested prompts should be the job ('can we take this on?'), not
    questions about the rulebook."""
    body = client.get(f"{PREFIX}/chat/suggestions").json()
    assert len(body) >= 8
    categories = {q["category"] for q in body}
    assert "Screening" in categories
    assert "Engagement team" in categories
    for q in body:
        assert q["question"].strip().endswith("?")


def test_chat_stream_emits_sse_frames():
    """Streaming exists because a screening question takes 40-120s. Verify the
    endpoint speaks SSE and terminates with a done event."""
    with client.stream(
        "POST", f"{PREFIX}/chat/stream",
        json={"message": "A COT match was submitted on 1 June 2025. Do I acknowledge it?"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        types = []
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            import json as _j
            types.append(_j.loads(line[6:])["type"])
            if types[-1] in ("done", "error"):
                break

    assert types, "no SSE frames received"
    assert types[0] == "session"
    assert types[-1] in ("done", "error")


def test_chat_history_persists_and_is_retrievable():
    """Rows were always written; nothing read them back, so a refresh looked
    like the conversation had been lost."""
    first = client.post(f"{PREFIX}/chat", json={"message": "Is KDDI Corporation listed in DESC?"}).json()
    session_id = first["session_id"]

    history = client.get(f"{PREFIX}/chat/{session_id}/messages").json()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[1]["agent_name"] == "conflict_assistant"


def test_chat_history_feeds_the_next_turn():
    """A follow-up naming no entity ("what designation does it carry?") is only
    answerable if prior turns reach the prompt."""
    from app.database import SessionLocal
    from app.repositories import chat_repository
    from app.services.chat_agent import _history_context

    session = SessionLocal()
    try:
        session_id = chat_repository.create_session(session, None)
        chat_repository.add_message(session, session_id, "user", "Is KDDI Corporation in DESC?")
        chat_repository.add_message(session, session_id, "assistant", "Yes, designation Relationship.")
        chat_repository.add_message(session, session_id, "user", "And what designation does it carry?")

        context = _history_context(session, session_id)
        assert "KDDI Corporation" in context
        assert "Relationship" in context
        # the question being answered must not be replayed as history
        assert context.count("And what designation") == 0
    finally:
        session.close()


def test_history_context_is_empty_for_a_new_session():
    from app.database import SessionLocal
    from app.repositories import chat_repository
    from app.services.chat_agent import _history_context

    session = SessionLocal()
    try:
        session_id = chat_repository.create_session(session, None)
        chat_repository.add_message(session, session_id, "user", "first question")
        assert _history_context(session, session_id) == ""
    finally:
        session.close()
