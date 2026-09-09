from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_session
from app.repositories import chat_repository
from app.schemas.dto import ChatMessageDTO, ChatReplyDTO, ChatRequestDTO, SuggestedQuestionDTO
from app.services.chat_agent import SUGGESTED_QUESTIONS, stream_chat
from app.services.screening_service import chat as chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatReplyDTO, summary="Ask a question; returns a reply plus the agent trace")
def post_chat(payload: ChatRequestDTO) -> ChatReplyDTO:
    result = chat_service(payload.session_id, payload.case_id, payload.message)
    return ChatReplyDTO(**result)


@router.post(
    "/stream",
    summary="Ask a question, streamed as server-sent events (tool calls, then answer tokens)",
)
def post_chat_stream(payload: ChatRequestDTO) -> StreamingResponse:
    """A screening question takes 40-120s on a local model. Streaming shows the
    tools running and then the answer arriving, instead of a blank wait."""
    return StreamingResponse(
        stream_chat(payload.session_id, payload.case_id, payload.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # don't let a proxy buffer the stream
        },
    )


@router.get(
    "/suggestions",
    response_model=list[SuggestedQuestionDTO],
    summary="Example questions an analyst would actually ask",
)
def get_suggestions() -> list[SuggestedQuestionDTO]:
    return [SuggestedQuestionDTO(**q) for q in SUGGESTED_QUESTIONS]


@router.get("/{session_id}/messages", response_model=list[ChatMessageDTO], summary="Chat history for a session")
def get_messages(session_id: str, session: Session = Depends(get_session)) -> list[ChatMessageDTO]:
    rows = chat_repository.get_messages(session, session_id)
    return [
        ChatMessageDTO(
            role=r["role"],
            content=r["content"],
            agent_name=r["agent_name"],
            tool_calls=r["tool_calls"] or [],
            created_at=r["created_at"],
        )
        for r in rows
    ]
