from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def create_session(session: Session, case_id: str | None) -> str:
    session_id = str(uuid.uuid4())
    session.execute(
        text("INSERT INTO chat_sessions (id, case_id) VALUES (:id, :case_id)"),
        {"id": session_id, "case_id": case_id},
    )
    session.commit()
    return session_id


def add_message(
    session: Session,
    session_id: str,
    role: str,
    content: str,
    agent_name: str | None = None,
    tool_calls: list[dict] | None = None,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO chat_messages (session_id, role, content, agent_name, tool_calls)
            VALUES (:session_id, :role, :content, :agent_name, CAST(:tool_calls AS JSONB))
            """
        ),
        {
            "session_id": session_id,
            "role": role,
            "content": content,
            "agent_name": agent_name,
            "tool_calls": json.dumps(tool_calls or []),
        },
    )
    session.commit()


def get_messages(session: Session, session_id: str) -> list[dict]:
    rows = session.execute(
        text("SELECT * FROM chat_messages WHERE session_id = :id ORDER BY created_at"), {"id": session_id}
    ).mappings().all()
    return [dict(r) for r in rows]
