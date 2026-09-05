from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def get(session: Session, case_id: str) -> dict | None:
    row = session.execute(
        text("SELECT * FROM golden_cases WHERE case_id = :case_id"), {"case_id": case_id}
    ).mappings().first()
    return dict(row) if row else None


def get_by_request_id(session: Session, request_id: str) -> dict | None:
    row = session.execute(
        text("SELECT * FROM golden_cases WHERE request_id = :rid"), {"rid": request_id}
    ).mappings().first()
    return dict(row) if row else None
