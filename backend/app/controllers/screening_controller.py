from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_session
from app.repositories import case_repository, screening_repository
from app.schemas.dto import DraftResponseDTO, ScreeningResultDTO, ScreeningStartedDTO
from app.services.screening_service import get_screening_result, run_screening

router = APIRouter(tags=["screening"])


@router.post(
    "/cases/{case_id}/screen",
    response_model=ScreeningStartedDTO,
    status_code=202,
    summary="Start a screening run (executes in the background)",
)
def start_screening(
    case_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> ScreeningStartedDTO:
    case = case_repository.get(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail={"code": "CASE_NOT_FOUND", "message": f"case {case_id} not found"})

    screening_id = screening_repository.create_pending(session, case_id)
    background_tasks.add_task(run_screening, case_id, screening_id)
    return ScreeningStartedDTO(screening_id=screening_id, status="PENDING")


@router.get(
    "/screenings/{screening_id}",
    response_model=ScreeningResultDTO,
    summary="Poll a screening; returns the full result once COMPLETE",
)
def get_screening(screening_id: str, session: Session = Depends(get_session)) -> ScreeningResultDTO:
    result = get_screening_result(session, screening_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SCREENING_NOT_FOUND", "message": f"screening {screening_id} not found"},
        )
    return ScreeningResultDTO(**result)


@router.get(
    "/cases/{case_id}/screenings",
    response_model=list[ScreeningResultDTO],
    summary="List every screening run for a case",
)
def list_screenings(case_id: str, session: Session = Depends(get_session)) -> list[ScreeningResultDTO]:
    ids = session.execute(
        text("SELECT id FROM screenings WHERE case_id = :id ORDER BY created_at DESC"), {"id": case_id}
    ).scalars().all()
    return [ScreeningResultDTO(**get_screening_result(session, str(i))) for i in ids]


@router.get(
    "/screenings/{screening_id}/draft-response",
    response_model=DraftResponseDTO,
    summary="The composed draft response, ending with the verbatim slide-14 footer",
)
def get_draft_response(screening_id: str, session: Session = Depends(get_session)) -> DraftResponseDTO:
    screening = screening_repository.get(session, screening_id)
    if screening is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SCREENING_NOT_FOUND", "message": f"screening {screening_id} not found"},
        )
    return DraftResponseDTO(draft_response=screening["draft_response"], format="markdown")
