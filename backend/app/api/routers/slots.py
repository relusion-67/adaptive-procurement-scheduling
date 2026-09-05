from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import procurement as procurement_repository
from app.schemas.procurement import ProcurementSlotResponse

router = APIRouter()


@router.get("/")
async def list_slots_placeholder() -> dict[str, str]:
    return {"status": "slots module foundation ready"}


@router.get("/{slot_id}", response_model=ProcurementSlotResponse)
async def get_slot(
    slot_id: int,
    session: Session = Depends(get_db),
) -> ProcurementSlotResponse:
    """Direct lookup for a single slot, regardless of remaining capacity.

    Unlike list_usable_slots() (used for discovering NEW bookable slots),
    this intentionally returns full slots too, so that an existing booking
    can still retrieve its own slot's date/time metadata after the slot's
    capacity reaches 0.
    """
    slot = procurement_repository.get_slot(session, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Procurement slot not found")
    return slot
