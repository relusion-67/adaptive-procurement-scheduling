"""Read-only access to imported external/official reference data.

Deliberately exposes GET only. Reference data enters the system through
the controlled offline import path (``app/db/import_reference_data.py``),
never through a public write endpoint - see that module's docstring and
the README's data-provenance section for why.

Any authenticated user (any role) may read this data: it is non-sensitive
contextual/statistical information, not a farmer- or centre-scoped
resource, so there is no per-row authorization to enforce the way there is
for bookings or queue entries.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.repositories import reference as reference_repository
from app.schemas.reference import ReferenceDatasetResponse

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[ReferenceDatasetResponse])
async def list_reference_data(
    district: str | None = None,
    dataset_type: str | None = None,
    metric_name: str | None = None,
    session: Session = Depends(get_db),
) -> list[ReferenceDatasetResponse]:
    return reference_repository.list_reference_data(
        session,
        district=district,
        dataset_type=dataset_type,
        metric_name=metric_name,
    )


@router.get("/{reference_id}", response_model=ReferenceDatasetResponse)
async def get_reference_row(
    reference_id: int,
    session: Session = Depends(get_db),
) -> ReferenceDatasetResponse:
    row = reference_repository.get_reference_row(session, reference_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Reference dataset row not found")
    return row
