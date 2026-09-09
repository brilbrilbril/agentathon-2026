from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def create_pending(session: Session, case_id: str) -> str:
    screening_id = str(uuid.uuid4())
    session.execute(
        text("INSERT INTO screenings (id, case_id, status) VALUES (:id, :case_id, 'PENDING')"),
        {"id": screening_id, "case_id": case_id},
    )
    session.commit()
    return screening_id


def update_status(session: Session, screening_id: str, status: str, error: str | None = None) -> None:
    session.execute(
        text("UPDATE screenings SET status = :status, error = :error WHERE id = :id"),
        {"id": screening_id, "status": status, "error": error},
    )
    session.commit()


def save_matches(session: Session, screening_id: str, matches: list[dict]) -> None:
    for m in matches:
        row = dict(m)
        row["screening_id"] = screening_id
        row["raw"] = json.dumps(row.get("raw", {}), default=str)
        session.execute(
            text(
                """
                INSERT INTO matches (screening_id, source, query_name, matched_name, similarity,
                    country, designation_type, gup_name, partner_name, practice_office, business_unit,
                    status, entity_role, match_date, include_in_summary, exclusion_reason,
                    rule_citation, risk_tier, risk_reason, raw)
                VALUES (:screening_id, :source, :query_name, :matched_name, :similarity,
                    :country, :designation_type, :gup_name, :partner_name, :practice_office, :business_unit,
                    :status, :entity_role, :match_date, :include_in_summary, :exclusion_reason,
                    :rule_citation, :risk_tier, :risk_reason, CAST(:raw AS JSONB))
                """
            ),
            row,
        )
    session.commit()


def finalize(session: Session, screening_id: str, result: dict) -> None:
    payload = dict(result)
    for key in ("conditions", "cross_border_actions", "quality_check_flags", "unchecked_sources"):
        if key in payload:
            payload[key] = json.dumps(payload[key], default=str)
    payload["id"] = screening_id
    session.execute(
        text(
            """
            UPDATE screenings SET
                status = 'COMPLETE',
                final_result = :final_result,
                conditions = CAST(:conditions AS JSONB),
                cross_border_actions = CAST(:cross_border_actions AS JSONB),
                quality_check_flags = CAST(:quality_check_flags AS JSONB),
                unchecked_sources = CAST(:unchecked_sources AS JSONB),
                draft_response = :draft_response,
                completed_at = now()
            WHERE id = :id
            """
        ),
        payload,
    )
    session.commit()


def get(session: Session, screening_id: str) -> dict | None:
    row = session.execute(text("SELECT * FROM screenings WHERE id = :id"), {"id": screening_id}).mappings().first()
    return dict(row) if row else None


def get_matches(session: Session, screening_id: str) -> list[dict]:
    rows = session.execute(
        text("SELECT * FROM matches WHERE screening_id = :id"), {"id": screening_id}
    ).mappings().all()
    return [dict(r) for r in rows]
