"""Dedicated security tests for the production-hardening milestone.

Covers: authentication (missing/malformed/expired/forged/valid tokens),
role-based authorization, resource-ownership/IDOR enforcement, admin
endpoint protection, centre-scoping for staff, configuration/secret
handling, and OpenAPI security-scheme exposure.

Uses its own SQLite database (independent of the other test files' demo
data) so these tests can freely create users of every role without
interfering with other suites.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import INSECURE_DEFAULT_JWT_SECRET_KEY, Settings, settings
from app.core.security import TOKEN_TYPE
from app.db.seed import seed_demo_data
from app.db.session import get_db
from app.main import app
from app.models import Booking, Farmer, ProcurementCentre
from tests._auth_helpers import (
    auth_headers,
    create_admin,
    create_farmer_user,
    create_staff_user,
    create_user,
)


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'security.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_demo_data(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        command.downgrade(alembic_cfg, "base")


@pytest.fixture
async def raw_client(db_session: Session) -> AsyncClient:
    """A client with no default Authorization header - each test attaches
    whatever headers it needs (or none, for unauthenticated checks).
    """

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def farmer(session: Session, phone: str = "9000000001") -> Farmer:
    result = session.scalar(select(Farmer).where(Farmer.phone == phone))
    assert result is not None
    return result


def centre(session: Session, code: str = "TNJ-CENTRAL-01") -> ProcurementCentre:
    result = session.scalar(select(ProcurementCentre).where(ProcurementCentre.code == code))
    assert result is not None
    return result


def booking_for(session: Session, farmer_phone: str) -> Booking:
    f = farmer(session, farmer_phone)
    result = session.scalar(select(Booking).where(Booking.farmer_id == f.id))
    assert result is not None
    return result


def _forged_token(user_id: int, role: str) -> str:
    """A syntactically valid JWT signed with a *different* key than the
    app uses - simulates a forged/tampered token.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=60),
    }
    return jwt.encode(payload, "not-the-real-secret", algorithm=settings.jwt_algorithm)


def _expired_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": TOKEN_TYPE,
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# ---------------------------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_token_is_rejected(raw_client: AsyncClient) -> None:
    response = await raw_client.get("/api/admin/")
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


@pytest.mark.anyio
async def test_malformed_token_is_rejected(raw_client: AsyncClient) -> None:
    response = await raw_client.get(
        "/api/admin/", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_expired_token_is_rejected(raw_client: AsyncClient, db_session: Session) -> None:
    admin = create_admin(db_session)
    token = _expired_token(admin.id, admin.role.value)
    response = await raw_client.get(
        "/api/admin/", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_invalid_signature_is_rejected(raw_client: AsyncClient, db_session: Session) -> None:
    admin = create_admin(db_session)
    token = _forged_token(admin.id, admin.role.value)
    response = await raw_client.get(
        "/api/admin/", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_valid_token_is_accepted_where_permitted(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    response = await raw_client.get("/api/admin/", headers=auth_headers(admin))
    assert response.status_code == 200
    assert response.json() == {"status": "admin module foundation ready"}


@pytest.mark.anyio
async def test_token_for_deleted_user_is_rejected(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    headers = auth_headers(admin)
    db_session.delete(admin)
    db_session.commit()

    response = await raw_client.get("/api/admin/", headers=headers)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# AUTHORIZATION / RBAC
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_farmer_cannot_access_admin(raw_client: AsyncClient, db_session: Session) -> None:
    farmer_user = create_farmer_user(db_session, farmer(db_session))
    response = await raw_client.get("/api/admin/", headers=auth_headers(farmer_user))
    assert response.status_code == 403


@pytest.mark.anyio
async def test_staff_cannot_access_admin_only_operation(
    raw_client: AsyncClient, db_session: Session
) -> None:
    staff = create_staff_user(db_session, centre(db_session))
    response = await raw_client.post(
        f"/api/admin/throughput/{centre(db_session).id}/recalculate",
        headers=auth_headers(staff),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_can_access_admin_endpoint(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    response = await raw_client.get("/api/admin/", headers=auth_headers(admin))
    assert response.status_code == 200


@pytest.mark.anyio
async def test_staff_cannot_create_bookings(raw_client: AsyncClient, db_session: Session) -> None:
    staff = create_staff_user(db_session, centre(db_session))
    f = farmer(db_session)
    response = await raw_client.post(
        "/api/bookings/",
        headers=auth_headers(staff),
        json={
            "farmer_id": f.id,
            "centre_id": centre(db_session).id,
            "slot_id": 1,
            "crop_type": "Paddy",
            "quantity_kg": 10,
        },
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# RESOURCE OWNERSHIP / IDOR
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_farmer_cannot_access_another_farmers_booking(
    raw_client: AsyncClient, db_session: Session
) -> None:
    owner = farmer(db_session, "9000000001")
    other_user = create_farmer_user(db_session, farmer(db_session, "9000000002"))
    booking = booking_for(db_session, "9000000001")
    assert booking.farmer_id == owner.id

    response = await raw_client.get(
        f"/api/bookings/{booking.id}", headers=auth_headers(other_user)
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_farmer_owner_can_access_their_own_booking(
    raw_client: AsyncClient, db_session: Session
) -> None:
    owner_user = create_farmer_user(db_session, farmer(db_session, "9000000001"))
    booking = booking_for(db_session, "9000000001")

    response = await raw_client.get(
        f"/api/bookings/{booking.id}", headers=auth_headers(owner_user)
    )
    assert response.status_code == 200
    assert response.json()["id"] == booking.id


@pytest.mark.anyio
async def test_farmer_cannot_create_booking_for_another_farmer(
    raw_client: AsyncClient, db_session: Session
) -> None:
    caller = create_farmer_user(db_session, farmer(db_session, "9000000001"))
    other_farmer = farmer(db_session, "9000000002")
    response = await raw_client.post(
        "/api/bookings/",
        headers=auth_headers(caller),
        json={
            "farmer_id": other_farmer.id,
            "centre_id": centre(db_session).id,
            "slot_id": 1,
            "crop_type": "Paddy",
            "quantity_kg": 10,
        },
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_farmer_cannot_check_in_another_farmers_booking(
    raw_client: AsyncClient, db_session: Session
) -> None:
    other_user = create_farmer_user(db_session, farmer(db_session, "9000000002"))
    booking = booking_for(db_session, "9000000001")

    response = await raw_client.post(
        "/api/queue/check-in",
        headers=auth_headers(other_user),
        json={"booking_id": booking.id, "centre_id": booking.centre_id},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_staff_cannot_access_another_centres_live_queue(
    raw_client: AsyncClient, db_session: Session
) -> None:
    home_centre = centre(db_session, "TNJ-CENTRAL-01")
    other_centre = centre(db_session, "KUM-01")
    staff = create_staff_user(db_session, home_centre)

    response = await raw_client.get(
        f"/api/queue/centres/{other_centre.id}", headers=auth_headers(staff)
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_staff_cannot_call_next_for_another_centre(
    raw_client: AsyncClient, db_session: Session
) -> None:
    home_centre = centre(db_session, "TNJ-CENTRAL-01")
    other_centre = centre(db_session, "KUM-01")
    staff = create_staff_user(db_session, home_centre)

    response = await raw_client.post(
        f"/api/queue/centres/{other_centre.id}/call-next", headers=auth_headers(staff)
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_staff_of_home_centre_can_view_its_live_queue(
    raw_client: AsyncClient, db_session: Session
) -> None:
    home_centre = centre(db_session, "TNJ-CENTRAL-01")
    staff = create_staff_user(db_session, home_centre)

    response = await raw_client.get(
        f"/api/queue/centres/{home_centre.id}", headers=auth_headers(staff)
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_farmer_cannot_view_another_farmers_scheduling_assessment(
    raw_client: AsyncClient, db_session: Session
) -> None:
    other_user = create_farmer_user(db_session, farmer(db_session, "9000000002"))
    booking = booking_for(db_session, "9000000001")

    response = await raw_client.get(
        f"/api/scheduling/bookings/{booking.id}", headers=auth_headers(other_user)
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_staff_cannot_view_another_centres_scheduling_assessment(
    raw_client: AsyncClient, db_session: Session
) -> None:
    home_centre = centre(db_session, "TNJ-CENTRAL-01")
    other_centre = centre(db_session, "KUM-01")
    staff = create_staff_user(db_session, home_centre)

    response = await raw_client.get(
        f"/api/scheduling/centres/{other_centre.id}", headers=auth_headers(staff)
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# ADMIN
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unauthenticated_admin_access_is_401(raw_client: AsyncClient) -> None:
    response = await raw_client.get("/api/admin/throughput/1")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_non_admin_throughput_access_is_403(
    raw_client: AsyncClient, db_session: Session
) -> None:
    farmer_user = create_farmer_user(db_session, farmer(db_session))
    response = await raw_client.get(
        f"/api/admin/throughput/{centre(db_session).id}", headers=auth_headers(farmer_user)
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_throughput_access_succeeds(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    response = await raw_client.get(
        f"/api/admin/throughput/{centre(db_session).id}", headers=auth_headers(admin)
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_admin_throughput_recalculation_succeeds(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    response = await raw_client.post(
        f"/api/admin/throughput/{centre(db_session, 'KUM-01').id}/recalculate",
        headers=auth_headers(admin),
    )
    # Valid, authorized request: either a fresh snapshot (200) or a
    # legitimate business-rule rejection (e.g. not enough completed
    # services yet, 409) - either is a properly-authorized outcome. What
    # this test guards against is 401/403.
    assert response.status_code in (200, 409)


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------


def test_jwt_secret_is_not_hardcoded_in_token_logic() -> None:
    """Authentication reads its signing key from Settings (environment
    configuration), not a literal baked into the token code.
    """
    from app.core import security as security_module

    source = Path(security_module.__file__).read_text()
    assert "settings.jwt_secret_key" in source
    # No inline string literal is used as the actual signing key.
    assert 'jwt.encode(payload, "' not in source
    assert 'jwt.decode(token, "' not in source


def test_production_config_rejects_insecure_default_secret() -> None:
    with pytest.raises(ValueError):
        Settings(app_env="production", jwt_secret_key=INSECURE_DEFAULT_JWT_SECRET_KEY)


def test_production_config_rejects_short_secret() -> None:
    with pytest.raises(ValueError):
        Settings(app_env="production", jwt_secret_key="too-short")


def test_production_config_accepts_strong_explicit_secret() -> None:
    strong_secret = "x" * 64
    configured = Settings(app_env="production", jwt_secret_key=strong_secret)
    assert configured.jwt_secret_key == strong_secret


def test_development_config_keeps_working_with_default_secret() -> None:
    # The practical development/test workflow must not be broken by the
    # production safeguard.
    configured = Settings(app_env="development")
    assert configured.jwt_secret_key == INSECURE_DEFAULT_JWT_SECRET_KEY


def test_password_is_never_stored_in_plaintext(db_session: Session) -> None:
    admin = create_admin(db_session, email="plaintext-check@example.test")
    assert "TestPass123!" not in admin.hashed_password
    assert admin.hashed_password.startswith("pbkdf2_sha256$")


# ---------------------------------------------------------------------------
# OPENAPI
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_openapi_exposes_a_bearer_security_scheme(raw_client: AsyncClient) -> None:
    response = await raw_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    security_schemes = schema["components"]["securitySchemes"]
    assert security_schemes, "expected at least one security scheme"


@pytest.mark.anyio
async def test_openapi_marks_protected_endpoints_as_secured(raw_client: AsyncClient) -> None:
    response = await raw_client.get("/openapi.json")
    schema = response.json()
    admin_get = schema["paths"]["/api/admin/"]["get"]
    assert admin_get.get("security"), "admin endpoint should advertise a security requirement"


@pytest.mark.anyio
async def test_openapi_does_not_mark_public_endpoints_as_secured(raw_client: AsyncClient) -> None:
    response = await raw_client.get("/openapi.json")
    schema = response.json()
    centres_get = schema["paths"]["/api/centres/"]["get"]
    assert not centres_get.get("security")


# ---------------------------------------------------------------------------
# REGISTRATION / LOGIN (new endpoints introduced by this milestone)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_farmer_can_register_and_log_in(
    raw_client: AsyncClient, db_session: Session
) -> None:
    f = farmer(db_session, "9000000003")
    register_response = await raw_client.post(
        "/api/auth/register",
        json={
            "email": "farmer3@example.test",
            "password": "StrongPass123!",
            "role": "FARMER",
            "farmer_id": f.id,
        },
    )
    assert register_response.status_code == 201, register_response.text
    body = register_response.json()
    assert body["role"] == "FARMER"
    assert body["farmer_id"] == f.id
    assert "password" not in body
    assert "hashed_password" not in body

    login_response = await raw_client.post(
        "/api/auth/login",
        data={"username": "farmer3@example.test", "password": "StrongPass123!"},
    )
    assert login_response.status_code == 200, login_response.text
    token = login_response.json()["access_token"]

    me_response = await raw_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "farmer3@example.test"


@pytest.mark.anyio
async def test_centre_staff_cannot_self_register(
    raw_client: AsyncClient, db_session: Session
) -> None:
    """CENTRE_STAFF is a privileged, centre-scoped role and must never be
    creatable through the public, unauthenticated registration endpoint -
    it must be provisioned by an ADMIN via POST /api/admin/users instead.
    """
    c = centre(db_session, "KUM-01")
    response = await raw_client.post(
        "/api/auth/register",
        json={
            "email": "kum-staff@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "centre_id": c.id,
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.anyio
async def test_admin_role_cannot_be_self_registered(raw_client: AsyncClient) -> None:
    response = await raw_client.post(
        "/api/auth/register",
        json={
            "email": "wannabe-admin@example.test",
            "password": "StrongPass123!",
            "role": "ADMIN",
        },
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_register_duplicate_email_is_rejected(
    raw_client: AsyncClient, db_session: Session
) -> None:
    f1 = farmer(db_session, "9000000001")
    f2 = farmer(db_session, "9000000002")
    payload = {
        "email": "dup@example.test",
        "password": "StrongPass123!",
        "role": "FARMER",
    }
    first = await raw_client.post("/api/auth/register", json={**payload, "farmer_id": f1.id})
    assert first.status_code == 201
    second = await raw_client.post("/api/auth/register", json={**payload, "farmer_id": f2.id})
    assert second.status_code == 409


@pytest.mark.anyio
async def test_register_farmer_already_linked_to_an_account_is_rejected(
    raw_client: AsyncClient, db_session: Session
) -> None:
    f = farmer(db_session, "9000000001")
    payload = {
        "password": "StrongPass123!",
        "role": "FARMER",
        "farmer_id": f.id,
    }
    first = await raw_client.post(
        "/api/auth/register", json={**payload, "email": "first@example.test"}
    )
    assert first.status_code == 201
    second = await raw_client.post(
        "/api/auth/register", json={**payload, "email": "second@example.test"}
    )
    assert second.status_code == 409


@pytest.mark.anyio
async def test_register_farmer_requires_existing_farmer_id(raw_client: AsyncClient) -> None:
    response = await raw_client.post(
        "/api/auth/register",
        json={
            "email": "ghost-farmer@example.test",
            "password": "StrongPass123!",
            "role": "FARMER",
            "farmer_id": 999999,
        },
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_register_farmer_without_farmer_id_is_rejected(raw_client: AsyncClient) -> None:
    response = await raw_client.post(
        "/api/auth/register",
        json={"email": "no-farmer-id@example.test", "password": "StrongPass123!", "role": "FARMER"},
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_register_rejects_centre_staff_regardless_of_centre_id_validity(
    raw_client: AsyncClient,
) -> None:
    """CENTRE_STAFF is rejected by the public registration endpoint's role
    validator before a centre_id is ever looked up - so even a
    *nonexistent* centre_id doesn't change the outcome. (The
    centre-existence check itself is covered for the legitimate,
    ADMIN-only provisioning path by
    test_admin_provisioning_rejects_invalid_centre_id.)
    """
    response = await raw_client.post(
        "/api/auth/register",
        json={
            "email": "ghost-staff@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "centre_id": 999999,
        },
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_admin_role_cannot_be_self_provisioned_by_non_admin(
    raw_client: AsyncClient, db_session: Session
) -> None:
    """Belt-and-suspenders: even if a caller tries the admin provisioning
    path itself, an unauthenticated or non-admin caller must be rejected
    before role validation is even relevant.
    """
    c = centre(db_session, "KUM-01")
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "sneaky-staff@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "centre_id": c.id,
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# ADMIN-ONLY ACCOUNT PROVISIONING (POST /api/admin/users)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_farmer_cannot_provision_centre_staff(
    raw_client: AsyncClient, db_session: Session
) -> None:
    f = farmer(db_session, "9000000001")
    c = centre(db_session, "KUM-01")
    user = create_farmer_user(db_session, f)
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "escalation-attempt@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "centre_id": c.id,
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_centre_staff_cannot_provision_centre_staff(
    raw_client: AsyncClient, db_session: Session
) -> None:
    c = centre(db_session, "TNJ-CENTRAL-01")
    other_centre = centre(db_session, "KUM-01")
    staff = create_staff_user(db_session, c)
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "peer-staff@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "centre_id": other_centre.id,
        },
        headers=auth_headers(staff),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_centre_staff_cannot_provision_admin(
    raw_client: AsyncClient, db_session: Session
) -> None:
    c = centre(db_session, "TNJ-CENTRAL-01")
    staff = create_staff_user(db_session, c)
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "staff-wants-admin@example.test",
            "password": "StrongPass123!",
            "role": "ADMIN",
        },
        headers=auth_headers(staff),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_can_provision_centre_staff(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    c = centre(db_session, "KUM-01")
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "new-staff@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "centre_id": c.id,
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "CENTRE_STAFF"
    assert body["centre_id"] == c.id
    assert body["farmer_id"] is None


@pytest.mark.anyio
async def test_admin_can_provision_admin(raw_client: AsyncClient, db_session: Session) -> None:
    admin = create_admin(db_session)
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "second-admin@example.test",
            "password": "StrongPass123!",
            "role": "ADMIN",
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "ADMIN"
    assert body["farmer_id"] is None
    assert body["centre_id"] is None


@pytest.mark.anyio
async def test_admin_provisioning_rejects_duplicate_email(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    c = centre(db_session, "KUM-01")
    payload = {
        "email": admin.email,  # already exists
        "password": "StrongPass123!",
        "role": "CENTRE_STAFF",
        "centre_id": c.id,
    }
    response = await raw_client.post(
        "/api/admin/users", json=payload, headers=auth_headers(admin)
    )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_admin_provisioning_rejects_invalid_centre_id(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "ghost-centre-staff@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "centre_id": 999999,
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_admin_provisioning_rejects_invalid_farmer_id(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "ghost-farmer-account@example.test",
            "password": "StrongPass123!",
            "role": "FARMER",
            "farmer_id": 999999,
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_admin_provisioned_farmer_cannot_be_assigned_a_centre(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    f = farmer(db_session, "9000000003")
    c = centre(db_session, "KUM-01")
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "farmer-with-centre@example.test",
            "password": "StrongPass123!",
            "role": "FARMER",
            "farmer_id": f.id,
            "centre_id": c.id,
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_admin_provisioned_centre_staff_cannot_be_assigned_a_farmer(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    f = farmer(db_session, "9000000003")
    c = centre(db_session, "KUM-01")
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "staff-with-farmer@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "farmer_id": f.id,
            "centre_id": c.id,
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_admin_provisioned_admin_cannot_be_assigned_a_farmer_or_centre(
    raw_client: AsyncClient, db_session: Session
) -> None:
    admin = create_admin(db_session)
    f = farmer(db_session, "9000000003")
    response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "admin-with-farmer@example.test",
            "password": "StrongPass123!",
            "role": "ADMIN",
            "farmer_id": f.id,
        },
        headers=auth_headers(admin),
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_admin_provisioned_centre_staff_can_log_in_and_is_scoped(
    raw_client: AsyncClient, db_session: Session
) -> None:
    """End-to-end: an ADMIN-provisioned CENTRE_STAFF account can log in
    with the password it was created with, and is scoped only to its own
    centre's live queue - not another centre's.
    """
    admin = create_admin(db_session)
    home = centre(db_session, "KUM-01")
    other = centre(db_session, "TNJ-CENTRAL-01")
    create_response = await raw_client.post(
        "/api/admin/users",
        json={
            "email": "provisioned-staff@example.test",
            "password": "StrongPass123!",
            "role": "CENTRE_STAFF",
            "centre_id": home.id,
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201, create_response.text

    login_response = await raw_client.post(
        "/api/auth/login",
        data={"username": "provisioned-staff@example.test", "password": "StrongPass123!"},
    )
    assert login_response.status_code == 200, login_response.text
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    own_centre_response = await raw_client.get(
        f"/api/queue/centres/{home.id}", headers=headers
    )
    assert own_centre_response.status_code == 200

    other_centre_response = await raw_client.get(
        f"/api/queue/centres/{other.id}", headers=headers
    )
    assert other_centre_response.status_code == 403


@pytest.mark.anyio
async def test_login_with_wrong_password_is_rejected(
    raw_client: AsyncClient, db_session: Session
) -> None:
    f = farmer(db_session, "9000000004")
    await raw_client.post(
        "/api/auth/register",
        json={
            "email": "wrongpass@example.test",
            "password": "StrongPass123!",
            "role": "FARMER",
            "farmer_id": f.id,
        },
    )
    response = await raw_client.post(
        "/api/auth/login",
        data={"username": "wrongpass@example.test", "password": "NotTheRightPassword"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_login_with_unknown_email_is_rejected(raw_client: AsyncClient) -> None:
    response = await raw_client.post(
        "/api/auth/login",
        data={"username": "nobody@example.test", "password": "whatever123"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_me_requires_authentication(raw_client: AsyncClient) -> None:
    response = await raw_client.get("/api/auth/me")
    assert response.status_code == 401
