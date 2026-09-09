from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_session
from app.eval.run_eval import evaluate
from app.repositories import golden_repository
from app.schemas.dto import EvalResultDTO, GoldenDTO

router = APIRouter(prefix="/cases", tags=["eval"])


@router.get(
    "/{case_id}/golden",
    response_model=GoldenDTO,
    summary="The analyst's stored determination for a closed case",
)
def get_golden(case_id: str, session: Session = Depends(get_session)) -> GoldenDTO:
    golden = golden_repository.get(session, case_id)
    if golden is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "GOLDEN_NOT_FOUND", "message": f"no golden answer for case {case_id}"},
        )
    return GoldenDTO(
        request_id=golden["request_id"],
        final_result=golden.get("final_result"),
        conditions=golden.get("conditions") or [],
        analyst_comments=golden.get("analyst_comments") or [],
        cross_border=golden.get("cross_border") or [],
    )


@router.post(
    "/{case_id}/evaluate",
    response_model=EvalResultDTO,
    summary="Run the pipeline and score it against the analyst's determination",
)
def run_evaluation(case_id: str, session: Session = Depends(get_session)) -> EvalResultDTO:
    if golden_repository.get(session, case_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "GOLDEN_NOT_FOUND", "message": f"no golden answer for case {case_id}"},
        )
    return EvalResultDTO(**evaluate(case_id))
