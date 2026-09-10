from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    ensure_centre_scope,
    require_admin,
    require_centre_staff_or_admin,
)
from app.db.session import get_db
from app.models import User
from app.repositories import throughput as throughput_repository
from app.schemas.auth import AdminUserCreate, UserResponse
from app.schemas.throughput import ThroughputSnapshotResponse
from app.services import auth as auth_service
from app.services import throughput as throughput_service

router = APIRouter()


@router.get("/", dependencies=[Depends(require_admin)])
async def admin_placeholder() -> dict[str, str]:
    return {"status": "admin module foundation ready"}


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_user(
    payload: AdminUserCreate,
    session: Session = Depends(get_db),
) -> UserResponse:
    """ADMIN-only account provisioning for FARMER, CENTRE_STAFF, or ADMIN."""
    try:
        return auth_service.provision_user(session, payload)
    except auth_service.AuthError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@router.get(
    "/throughput/{centre_id}",
    response_model=ThroughputSnapshotResponse,
)
async def get_latest_throughput(
    centre_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_centre_staff_or_admin),
) -> ThroughputSnapshotResponse:
    ensure_centre_scope(current_user, centre_id)

    snapshot = throughput_repository.get_latest_snapshot(session, centre_id)

    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No throughput snapshot is available for this centre yet",
        )

    return snapshot


@router.post(
    "/throughput/{centre_id}/recalculate",
    response_model=ThroughputSnapshotResponse,
)
async def recalculate_throughput(
    centre_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ThroughputSnapshotResponse:
    ensure_centre_scope(current_user, centre_id)

    try:
        return throughput_service.recalculate_throughput_for_centre(
            session,
            centre_id,
        )
    except throughput_service.ThroughputError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error