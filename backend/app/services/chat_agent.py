"""Chat — a real tool-using agent (DEV_B §5).

The model decides which tools to call. Mechanical verdicts still come from
`rules_engine` behind those tools, so an answer about a rule reports what the
rule actually returned rather than what the model remembers about it.
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text

from app.agents.runtime import run_agent, trace_entry
from app.database import SessionLocal
from app.repositories import chat_repository

log = logging.getLogger(__name__)

CHAT_TOOLS = [
    "search_rules",
    "get_rules_by_source",
    "search_desc_entities",
    "search_wbs_engagements",
    "search_cot_requests",
    "search_dccs_history",
    "search_one_window",
    "search_engagements_by_partner",
    "get_desc_responsible_party",
    "get_case_details",
    "classify_wbs_business_unit",
    "classify_wbs_status",
    "is_dccs_match_relevant",
    "is_cot_match_acknowledged",
    "compare_stated_vs_desc_designation",
    "evaluate_cross_border",
    "parse_desc_designations",
]

SYSTEM_PROMPT = """You are a conflict-check assistant for Deloitte SEA Tax & Transformation analysts.
You answer questions using tools. You never guess and you never rely on memory for a rule.

How to answer:

**A screening question — "can we take this on?", "will this conflict?", "is anything
blocking work with X?"** This is the main job. Do the work, don't describe the process:
  1. Search the entity across DESC, WBS, COT and DCCS history (and One Window, which is a
     stub, so the source is recorded as unchecked).
  2. For each material match, call assess_risk_tier to decide how much attention it needs.
  3. Call the rule tools for anything mechanical (business unit, staleness, cutoff,
     cross-border).
  4. Answer with: can they proceed, what conditions apply, and what needs a human decision.
     Lead with the High-risk findings. Do not list every match — that is what triage is for.

**An engagement-team question — "can we staff X on this?", "who already serves this
client?", "what does Audit Team Restricted mean for our team?"** -> call
search_engagements_by_partner for the person, and get_desc_responsible_party for the
client's DESC contact. Say plainly that only engagement records are available: there is no
HR, directorship or personal-holdings data, so Personal Conflicts (slide 14) still needs
the Engagement Partner's own enquiry.

**Is this the same company?** -> call adjudicate_same_entity, then decide yourself using the
country and GUP it returns. A similar name is not a match.

**How risky is this match?** -> call assess_risk_tier. Never guess a tier.

**A rule outcome — "would a 2021 DCCS match still count?"** -> call the matching rule tool
(is_dccs_match_relevant, classify_wbs_business_unit, is_cot_match_acknowledged,
compare_stated_vs_desc_designation, evaluate_cross_border) and report what it returned.
Never decide a mechanical rule yourself.

**A procedural question — "when do I send a cross-border check?"** -> call search_rules or
get_rules_by_source and answer citing the QRC slide.

**A question about a specific case** -> call get_case_details.

Terminology — use these exactly, never expand an acronym differently:
  DESC = the entity master (legal names, designations, GUP). Authoritative.
  GUP  = Global Ultimate Parent (never "Global Unique Partner").
  WBS  = engagement listing, actual chargeable work.
  COT  = Client Onboarding Tool, in-flight onboarding requests.
  DCCS = Deloitte Conflict Check System, where requests originate.
  LCSP / RP = Lead Client Service Partner / Responsible Party.
  "Audit Team Restricted" restricts who may be staffed, not whether the client may be served.

Cite the QRC slide number behind every classification. Be concise and practical.
If the tools return nothing relevant, say so plainly rather than speculating.
This is a drafting aid — the analyst decides."""


MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 700


def _history_context(session, session_id: str) -> str:
    """Prior turns, so a follow-up like "and what about the shareholder?" has
    something to refer to.

    Only the last few turns are included, and assistant answers are truncated:
    a full screening answer is ~2,000 characters and the model has a small
    context window, so replaying several verbatim would crowd out the tools.
    The message just added for this turn is excluded — it is the question
    being answered.
    """
    rows = chat_repository.get_messages(session, session_id)
    if len(rows) <= 1:
        return ""

    recent = rows[:-1][-(MAX_HISTORY_TURNS * 2):]
    if not recent:
        return ""

    lines = []
    for row in recent:
        speaker = "Analyst" if row["role"] == "user" else "You"
        content = (row["content"] or "").strip().replace("\n", " ")
        if len(content) > MAX_HISTORY_CHARS:
            content = content[:MAX_HISTORY_CHARS] + " …(truncated)"
        lines.append(f"{speaker}: {content}")

    return (
        "\n\nEarlier in this conversation:\n"
        + "\n".join(lines)
        + "\n\nUse this only to resolve what the analyst is referring to. Re-run the tools "
          "for any facts — do not rely on what was said before."
    )


def _case_context(session, case_id: str) -> str:
    from app.services.screening_service import get_screening_result

    context = f"\n\nThe analyst is looking at case_id {case_id}."
    latest = session.execute(
        text(
            "SELECT id FROM screenings WHERE case_id = :cid AND status = 'COMPLETE' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"cid": case_id},
    ).scalar()
    if latest:
        result = get_screening_result(session, str(latest))
        context += (
            f"\nIts last completed screening returned {result['final_result']} with "
            f"{len(result['summary_table'])} matches included and "
            f"{len(result['excluded_matches'])} excluded."
        )
    return context


def _citations(run, reply: str) -> list[dict]:
    """Slides the tools actually returned, plus any the answer cites."""
    citations: list[dict] = []
    for record in run.results:
        result = record["result"]
        if not isinstance(result, dict):
            continue
        for rule in result.get("rules", []):
            citations.append({"slide_number": rule["slide"], "title": rule.get("title")})

    for slide in re.findall(r"[Ss]lide\s+(\d{1,2})", reply):
        citations.append({"slide_number": int(slide), "title": None})

    deduped, seen = [], set()
    for c in citations:
        if c["slide_number"] in seen:
            continue
        seen.add(c["slide_number"])
        deduped.append(c)
    return deduped


SUGGESTED_QUESTIONS = [
    {
        "category": "Screening",
        "question": "We've been asked to do an HR transformation project for KDDI (Thailand) "
                    "Limited, requested from Malaysia. Are there any conflicts, and what "
                    "conditions would apply?",
    },
    {
        "category": "Screening",
        "question": "A partner wants to pitch new tax advisory work to KDDI Corporation. "
                    "Is there anything that would block it?",
    },
    {
        "category": "Screening",
        "question": "We're considering taking on a statutory audit for KDDI Corporation. "
                    "Is that allowed?",
    },
    {
        "category": "Screening",
        "question": "Of everything that came back for KDDI Corporation, what actually needs "
                    "my attention?",
    },
    {
        "category": "Engagement team",
        "question": "We want to staff Soon Bee Koh as engagement partner on a new KDDI job. "
                    "Does that create a conflict?",
    },
    {
        "category": "Engagement team",
        "question": "KDDI Corporation is Audit Team Restricted. What does that mean for who "
                    "we can put on this engagement?",
    },
    {
        "category": "Engagement team",
        "question": "Who do I need to clear this relationship with before we proceed on "
                    "KDDI Corporation?",
    },
    {
        "category": "Disambiguation",
        "question": "Search brought back 'Motto Auction Thailand Company Limited' for my "
                    "client 'KDDI (Thailand) Limited'. Is that actually the same company?",
    },
    {
        "category": "Rule application",
        "question": "I found a conflict check for this client dated 15 March 2021, status "
                    "Approved with Conditions. Does it still count?",
    },
    {
        "category": "Rule application",
        "question": "The requestor says this entity is Restricted, but DESC says Relationship. "
                    "Which do I go with?",
    },
    {
        "category": "Cross-border",
        "question": "Our client's ultimate parent is in Japan. Do I need to send a request to "
                    "the Japan member firm before we start?",
    },
    {
        "category": "Scope",
        "question": "What hasn't this tool checked that I still need to do myself?",
    },
]


SSE_FRAME_END = "\n\n"


def _sse(payload: dict) -> str:
    """One server-sent event. SSE frames are terminated by a blank line."""
    return "data: " + json.dumps(payload) + SSE_FRAME_END


def stream_chat(session_id: str | None, case_id: str | None, message: str):
    """Server-sent-event generator for the chat agent.

    Yields the same events `streaming.stream_agent` produces, then persists the
    finished turn exactly as the blocking `chat()` does — so a streamed
    conversation and a blocking one leave identical history.
    """
    from app.agents.streaming import stream_agent

    session = SessionLocal()
    try:
        if session_id is None:
            session_id = chat_repository.create_session(session, case_id)
        chat_repository.add_message(session, session_id, "user", message)

        context = f"Question: {message}"
        if case_id:
            context += _case_context(session, case_id)
        context += _history_context(session, session_id)

        yield _sse({'type': 'session', 'session_id': str(session_id)})
        run = None
        for event in stream_agent("conflict_assistant", SYSTEM_PROMPT, context, CHAT_TOOLS, max_turns=12):
            if event["type"] == "done":
                run = event["run"]
                continue
            yield _sse(event)
            if event["type"] == "error":
                return

        if run is None:
            return

        reply = run.content or "I could not find an answer to that in the QRC rulebook or the databases."
        agent_trace = [trace_entry(run)]
        chat_repository.add_message(
            session, session_id, "assistant", reply,
            agent_name="conflict_assistant", tool_calls=agent_trace,
        )

        payload = {
            "type": "done",
            "session_id": str(session_id),
            "reply": reply,
            "agent_trace": agent_trace,
            "citations": _citations(run, reply),
            "seconds": round(run.seconds, 1),
        }
        yield _sse(payload)
    finally:
        session.close()


def chat(session_id: str | None, case_id: str | None, message: str) -> dict:
    session = SessionLocal()
    try:
        if session_id is None:
            session_id = chat_repository.create_session(session, case_id)
        chat_repository.add_message(session, session_id, "user", message)

        context = f"Question: {message}"
        if case_id:
            context += _case_context(session, case_id)
        context += _history_context(session, session_id)

        run = run_agent("conflict_assistant", SYSTEM_PROMPT, context, CHAT_TOOLS, max_turns=8)

        if run.degraded:
            reply = (
                "The inference server is unreachable, so I cannot answer this. "
                "Screening and the deterministic QRC rules still work — only chat needs the model."
            )
        else:
            reply = run.content or "I could not find an answer to that in the QRC rulebook or the databases."

        agent_trace = [trace_entry(run)]
        chat_repository.add_message(
            session, session_id, "assistant", reply,
            agent_name="conflict_assistant", tool_calls=agent_trace,
        )

        return {
            "session_id": str(session_id),
            "reply": reply,
            "agent_trace": agent_trace,
            "citations": _citations(run, reply),
        }
    finally:
        session.close()
