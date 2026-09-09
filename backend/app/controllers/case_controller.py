from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_session
from app.repositories import case_repository
from app.schemas.dto import CaseCreateDTO, CaseDetailDTO, CaseListDTO, CaseSummaryDTO, PartyDTO

router = APIRouter(prefix="/cases", tags=["cases"])


def _to_detail(case: dict, parties: list[dict]) -> CaseDetailDTO:
    return CaseDetailDTO(
        case_id=str(case["id"]),
        request_id=case.get("request_id"),
        request_type=case.get("request_type"),
        originator=case.get("originator"),
        member_firm=case.get("member_firm"),
        location=case.get("location"),
        office=case.get("office"),
        service_offering=case.get("service_offering"),
        engagement_name=case.get("engagement_name"),
        engagement_details=case.get("engagement_details"),
        is_recurring=bool(case.get("is_recurring")),
        is_inbound_referral=bool(case.get("is_inbound_referral")),
        has_iwrf=bool(case.get("has_iwrf")),
        lead_partner=case.get("lead_partner"),
        lead_manager=case.get("lead_manager"),
        date_submitted=case.get("date_submitted"),
        parties=[
            PartyDTO(
                entity_name=p["entity_name"],
                party_side=p.get("party_side") or "CLIENT_SIDE",
                entity_role=p.get("entity_role"),
                entity_type=p.get("entity_type"),
                location=p.get("location"),
                stated_designation=p.get("stated_designation"),
                is_gup=bool(p.get("is_gup")),
            )
            for p in parties
        ],
    )


@router.get("", response_model=CaseListDTO, summary="List all ingested and manually created cases")
def list_cases(session: Session = Depends(get_session)) -> CaseListDTO:
    cases = case_repository.list_cases(session)
    items = []
    for case in cases:
        case_id = str(case["id"])
        party_count = session.execute(
            text("SELECT COUNT(*) FROM case_parties WHERE case_id = :id"), {"id": case_id}
        ).scalar()
        has_golden = bool(
            session.execute(
                text("SELECT 1 FROM golden_cases WHERE case_id = :id LIMIT 1"), {"id": case_id}
            ).scalar()
        )
        latest_status = session.execute(
            text(
                "SELECT status FROM screenings WHERE case_id = :id ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": case_id},
        ).scalar()
        items.append(CaseSummaryDTO(
            case_id=case_id,
            request_id=case.get("request_id"),
            service_offering=case.get("service_offering"),
            location=case.get("location"),
            date_submitted=case.get("date_submitted"),
            party_count=party_count or 0,
            has_golden=has_golden,
            latest_screening_status=latest_status,
        ))
    return CaseListDTO(items=items, total=len(items))


@router.get("/{case_id}", response_model=CaseDetailDTO, summary="Get one case with its relevant parties")
def get_case(case_id: str, session: Session = Depends(get_session)) -> CaseDetailDTO:
    case = case_repository.get(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail={"code": "CASE_NOT_FOUND", "message": f"case {case_id} not found"})
    parties = case_repository.get_parties(session, case_id)
    return _to_detail(case, parties)


@router.post("", response_model=CaseDetailDTO, status_code=201, summary="Create a case manually")
def create_case(payload: CaseCreateDTO, session: Session = Depends(get_session)) -> CaseDetailDTO:
    data = payload.model_dump()
    parties = data.pop("parties", [])
    for party in parties:
        party.setdefault("abbreviated_names", None)
        party.setdefault("dgmf_id", None)
        party.setdefault("address", None)
    data["parties"] = parties
    case_id = case_repository.create_case_manual(session, data)
    case = case_repository.get(session, case_id)
    return _to_detail(case, case_repository.get_parties(session, case_id))


@router.delete("/{case_id}", status_code=204, summary="Delete a manually created case")
def delete_case(case_id: str, session: Session = Depends(get_session)) -> None:
    case = case_repository.get(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail={"code": "CASE_NOT_FOUND", "message": f"case {case_id} not found"})
    if (case.get("source_filename") or "") != "manual":
        raise HTTPException(
            status_code=400,
            detail={"code": "VALIDATION_ERROR", "message": "Only manually created cases can be deleted"},
        )
    session.execute(text("DELETE FROM cases WHERE id = :id"), {"id": case_id})
    session.commit()
