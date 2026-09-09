from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.llm import llm_available
from app.database import get_session
from app.schemas.dto import HealthDTO, StatsDTO

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthDTO, summary="Liveness plus Postgres and LLM availability")
def health(session: Session = Depends(get_session)) -> HealthDTO:
    try:
        session.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception:  # noqa: BLE001 - health check must never raise
        # Roll back so a failed probe doesn't leave the pooled connection in
        # an aborted transaction for the next request.
        session.rollback()
        postgres_ok = False
    return HealthDTO(status="ok" if postgres_ok else "degraded", postgres=postgres_ok, llm=llm_available())


@router.get("/stats", response_model=StatsDTO, summary="Row counts per ingested source")
def stats(session: Session = Depends(get_session)) -> StatsDTO:
    def count(table: str) -> int:
        return session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0

    return StatsDTO(
        desc_entities=count("desc_entities"),
        wbs_engagements=count("wbs_engagements"),
        cot_requests=count("cot_requests"),
        dccs_search_results=count("dccs_search_results"),
        rule_chunks=count("rule_chunks"),
        cases=count("cases"),
        screenings=count("screenings"),
    )
