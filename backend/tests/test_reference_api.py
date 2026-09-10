"""API tests for GET /api/reference/ - the read-only reference-data router.

Follows the per-file SQLite fixture pattern used elsewhere in this suite
(see tests/test_throughput.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.seed import seed_demo_data
from app.db.session import get_db
from app.main import app
from app.repositories import reference as reference_repository
from tests._auth_helpers import auth_headers, create_admin


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'reference_api.sqlite3'}"
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
async def client(db_session: Session) -> AsyncClient:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    admin = create_admin(db_session, email="test_reference_api-admin@example.test")
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=auth_headers(admin),
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _seed_reference_row(session: Session, **overrides) -> None:
    defaults = dict(
        dataset_type="SEASON_CROP_REPORT",
        district="Thanjavur",
        season_or_period="2024-25 Kharif",
        metric_name="paddy_area_hectares",
        metric_value=Decimal("12345.67"),
        unit="hectares",
        data_status="REAL",
        source="Test fixture - Season and Crop Report (not a real dataset)",
        source_reference="https://example.test/season-crop-report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    reference_repository.create_reference_row(session, **defaults)
    session.commit()


@pytest.mark.anyio
async def test_list_reference_data_returns_seeded_rows(
    client: AsyncClient, db_session: Session
) -> None:
    _seed_reference_row(db_session)

    response = await client.get("/api/reference/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["district"] == "Thanjavur"
    assert body[0]["data_status"] == "REAL"


@pytest.mark.anyio
async def test_list_reference_data_filters_by_district(
    client: AsyncClient, db_session: Session
) -> None:
    _seed_reference_row(db_session, district="Thanjavur")
    _seed_reference_row(db_session, district="Thiruvarur")

    response = await client.get("/api/reference/", params={"district": "Thiruvarur"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["district"] == "Thiruvarur"


@pytest.mark.anyio
async def test_list_reference_data_filters_by_dataset_type_and_metric_name(
    client: AsyncClient, db_session: Session
) -> None:
    _seed_reference_row(
        db_session, dataset_type="SEASON_CROP_REPORT", metric_name="paddy_area_hectares"
    )
    _seed_reference_row(
        db_session, dataset_type="AGMARKNET_PRICE", metric_name="modal_price_per_quintal"
    )

    response = await client.get("/api/reference/", params={"dataset_type": "AGMARKNET_PRICE"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["metric_name"] == "modal_price_per_quintal"

    response = await client.get(
        "/api/reference/", params={"metric_name": "paddy_area_hectares"}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["dataset_type"] == "SEASON_CROP_REPORT"


@pytest.mark.anyio
async def test_list_reference_data_returns_empty_list_not_error(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/reference/", params={"district": "Nonexistent District"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_get_reference_row_by_id(client: AsyncClient, db_session: Session) -> None:
    _seed_reference_row(db_session)
    listing = await client.get("/api/reference/")
    row_id = listing.json()[0]["id"]

    response = await client.get(f"/api/reference/{row_id}")

    assert response.status_code == 200
    assert response.json()["id"] == row_id


@pytest.mark.anyio
async def test_get_reference_row_unknown_id_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/reference/999999")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_reference_endpoint_requires_authentication() -> None:
    """No auth override/header - the request should be rejected."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as anon_client:
        response = await anon_client.get("/api/reference/")

    assert response.status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
async def test_reference_endpoint_has_no_write_verbs(
    client: AsyncClient, method: str
) -> None:
    response = await client.request(method, "/api/reference/", json={})

    assert response.status_code == 405
