from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.repositories import throughput as throughput_repository
from app.schemas.auth import AdminUserCreate, UserResponse
from app.schemas.throughput import ThroughputSnapshotResponse
from app.services import auth as auth_service
from app.services import throughput as throughput_service

# Router-level dependency: every route under /admin requires an
# authenticated ADMIN. This is deliberately enforced once, at the router,
# rather than per-route, so a new admin route can never be added here
# without protection by construction. This is also what makes
# POST /admin/users a safe home for privileged account provisioning:
# CENTRE_STAFF and ADMIN accounts can only ever be created by a caller who
# has already been authenticated as ADMIN.
router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/")
async def admin_placeholder() -> dict[str, str]:
    return {"status": "admin module foundation ready"}


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreate,
    session: Session = Depends(get_db),
) -> UserResponse:
    """ADMIN-only account provisioning for FARMER, CENTRE_STAFF, or ADMIN.

    This is the *only* legitimate way to create a CENTRE_STAFF or ADMIN
    account; POST /auth/register (public, unauthenticated) only permits
    FARMER. Reuses the same validation/service logic as public
    registration (see `auth_service`) so the role/resource invariant is
    enforced identically regardless of entry point.
    """
    try:
        return auth_service.provision_user(session, payload)
    except auth_service.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.get(
    "/throughput/{centre_id}",
    response_model=ThroughputSnapshotResponse,
)
async def get_latest_throughput(
    centre_id: int,
    session: Session = Depends(get_db),
) -> ThroughputSnapshotResponse:
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
) -> ThroughputSnapshotResponse:
    try:
        return throughput_service.recalculate_throughput_for_centre(session, centre_id)
    except throughput_service.ThroughputError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
