from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def get(session: Session, case_id: str) -> dict | None:
    row = session.execute(text("SELECT * FROM cases WHERE id = :id"), {"id": case_id}).mappings().first()
    return dict(row) if row else None


def get_by_request_id(session: Session, request_id: str) -> dict | None:
    row = session.execute(text("SELECT * FROM cases WHERE request_id = :rid"), {"rid": request_id}).mappings().first()
    return dict(row) if row else None


def get_parties(session: Session, case_id: str) -> list[dict]:
    rows = session.execute(text("SELECT * FROM case_parties WHERE case_id = :id"), {"id": case_id}).mappings().all()
    return [dict(r) for r in rows]


def list_cases(session: Session, limit: int = 50) -> list[dict]:
    rows = session.execute(text("SELECT * FROM cases ORDER BY created_at DESC LIMIT :limit"), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def create_case_manual(session: Session, case: dict) -> str:
    """UI form path — a manually entered case (no ingested PDF)."""
    case_id = str(uuid.uuid4())
    session.execute(
        text(
            """
            INSERT INTO cases (id, request_id, request_type, originator, member_firm, location,
                office, service_offering, engagement_name, engagement_details, is_recurring,
                is_inbound_referral, has_iwrf, lead_partner, lead_manager, date_submitted,
                source_filename)
            VALUES (:id, :request_id, :request_type, :originator, :member_firm, :location,
                :office, :service_offering, :engagement_name, :engagement_details, :is_recurring,
                :is_inbound_referral, :has_iwrf, :lead_partner, :lead_manager, :date_submitted,
                'manual')
            """
        ),
        {"id": case_id, **case},
    )
    for party in case.get("parties", []):
        session.execute(
            text(
                """
                INSERT INTO case_parties (case_id, entity_name, party_side, entity_role, entity_type,
                    abbreviated_names, dgmf_id, address, location, stated_designation, is_gup)
                VALUES (:case_id, :entity_name, :party_side, :entity_role, :entity_type,
                    :abbreviated_names, :dgmf_id, :address, :location, :stated_designation, :is_gup)
                """
            ),
            {"case_id": case_id, **party},
        )
    session.commit()
    return case_id
