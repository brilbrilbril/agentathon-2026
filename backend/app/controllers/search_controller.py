from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_session
from app.models.domain import MatchSource
from app.repositories import rule_repository
from app.repositories.entity_search import (
    search_cot,
    search_dccs_history,
    search_desc,
    search_wbs,
)
from app.schemas.dto import EntityMatchDTO, EntitySearchDTO, RuleChunkDTO, RuleSearchDTO

router = APIRouter(tags=["search"])

_SEARCHERS = {
    MatchSource.DESC.value: search_desc,
    MatchSource.WBS.value: search_wbs,
    MatchSource.COT.value: search_cot,
    MatchSource.DCCS_HISTORY.value: search_dccs_history,
}


def _to_dto(m) -> EntityMatchDTO:
    return EntityMatchDTO(
        source=m.source.value,
        matched_name=m.matched_name,
        query_name=m.query_name,
        similarity=round(m.similarity, 4),
        country=m.country,
        designation_type=m.designation_type,
        gup_name=m.gup_name,
        partner_name=m.partner_name,
        practice_office=m.practice_office,
        business_unit=m.business_unit.value if m.business_unit else None,
        status=m.status.value if m.status else None,
        entity_role=m.entity_role,
        match_date=m.match_date,
        include_in_summary=m.include_in_summary,
        exclusion_reason=m.exclusion_reason,
        rule_citation=m.rule_citation,
    )


@router.get(
    "/search/entities",
    response_model=EntitySearchDTO,
    summary="Fuzzy entity lookup across DESC / WBS / COT / DCCS history",
)
def search_entities(
    q: str = Query(..., description="Entity name to search for"),
    sources: str = Query("DESC,WBS,COT,DCCS_HISTORY", description="Comma-separated source list"),
    threshold: float = Query(0.8, ge=0.0, le=1.0),
    session: Session = Depends(get_session),
) -> EntitySearchDTO:
    wanted = [s.strip().upper() for s in sources.split(",") if s.strip()]
    results: dict[str, list[EntityMatchDTO]] = {}
    for source in wanted:
        fn = _SEARCHERS.get(source)
        if fn is None:
            results[source] = []
            continue
        results[source] = [_to_dto(m) for m in fn(session, q, threshold=threshold)]
    return EntitySearchDTO(query=q, results=results)


@router.get("/rules/search", response_model=RuleSearchDTO, summary="Full-text search over the QRC rule chunks")
def search_rules(
    q: str = Query(..., description="Procedural question"),
    source_db: str | None = Query(None),
    top_k: int = Query(3, ge=1, le=20),
    session: Session = Depends(get_session),
) -> RuleSearchDTO:
    chunks = rule_repository.search_rules(session, q, source_db=source_db, top_k=top_k)
    return RuleSearchDTO(results=[RuleChunkDTO(**c.model_dump()) for c in chunks])


@router.get("/rules", response_model=RuleSearchDTO, summary="All QRC rule chunks, for the Guide tab")
def list_rules(session: Session = Depends(get_session)) -> RuleSearchDTO:
    chunks = rule_repository.load_cache(session)
    return RuleSearchDTO(results=[RuleChunkDTO(**c.model_dump()) for c in chunks])
