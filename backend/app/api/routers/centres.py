from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import procurement as procurement_repository
from app.schemas.procurement import ProcurementCentreResponse, ProcurementSlotResponse

router = APIRouter()


@router.get("/", response_model=list[ProcurementCentreResponse])
async def list_centres(
    session: Session = Depends(get_db),
) -> list[ProcurementCentreResponse]:
    return procurement_repository.list_active_centres(session)


@router.get("/{centre_id}/slots", response_model=list[ProcurementSlotResponse])
async def list_centre_slots(
    centre_id: int,
    session: Session = Depends(get_db),
) -> list[ProcurementSlotResponse]:
    centre = procurement_repository.get_centre(session, centre_id)
    if centre is None:
        raise HTTPException(status_code=404, detail="Procurement centre not found")
    if not centre.active:
        raise HTTPException(status_code=409, detail="Procurement centre is inactive")
    return procurement_repository.list_usable_slots(session, centre_id)
