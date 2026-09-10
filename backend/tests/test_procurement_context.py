"""Milestone 2: tests for the procurement/scheduling <-> reference-data
integration.

Covers:
  - app.services.reference_data.find_reference_context (deterministic
    matching, provenance preservation)
  - app.services.procurement_context.get_centre_agricultural_context
    (district resolution, error handling for an unknown centre)
  - GET /api/centres/{centre_id}/reference-context (API shape, filters,
    empty-result behavior, unknown centre)
  - Structural failure isolation: scheduling/ETA/queue/booking code must
    not import, and must not be affected by, the reference-data layer -
    with or without reference data present, and even if the reference
    layer raises.

Follows the per-file SQLite + Alembic fixture pattern used throughout
this suite (see tests/test_slot_lookup_api.py, tests/test_reference_data.py).
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.seed import seed_demo_data
from app.db.session import get_db
from app.main import app
from app.models import ProcurementCentre
from app.repositories import reference as reference_repository
from app.services import procurement_context as procurement_context_service
from app.services import reference_data as reference_service
from app.services import scheduling as scheduling_service
from app.core import clock
from tests._auth_helpers import auth_headers, create_admin


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze app.core.clock.utcnow() so forecast-based scheduling
    estimates (which depend on "now") are reproducible across calls in
    the same test - matching the pattern used in tests/test_scheduling.py.
    Does not affect seed_demo_data's slot dates, which are generated from
    the real wall-clock date module directly, not via app.core.clock."""
    fixed_now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "utcnow", lambda: fixed_now)
    return fixed_now


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'procurement_context.sqlite3'}"
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
    admin = create_admin(db_session, email="test_procurement_context-admin@example.test")
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


def thanjavur_centre(session: Session) -> ProcurementCentre:
    centre = session.scalar(
        select(ProcurementCentre).where(ProcurementCentre.code == "TNJ-CENTRAL-01")
    )
    assert centre is not None
    assert centre.district == "Thanjavur"
    return centre


def _seed_reference_row(session: Session, **overrides) -> None:
    """Test fixture only - shaped like the real, already-imported Thanjavur
    paddy_area record, but with clearly fake values so it can never be
    confused with production data. See README's data-provenance policy."""
    defaults = dict(
        dataset_type="SEASON_CROP_REPORT",
        district="Thanjavur",
        season_or_period="2024-25",
        metric_name="paddy_area",
        metric_value=Decimal("2.10"),
        unit="lakh hectares",
        data_status="REAL",
        source="Test fixture - not the real Season and Crop Report",
        source_reference="https://example.test/season-crop-report",
        retrieved_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    reference_repository.create_reference_row(session, **defaults)
    session.commit()


# ---------------------------------------------------------------------------
# app.services.reference_data.find_reference_context
# ---------------------------------------------------------------------------


def test_find_reference_context_returns_matching_fact(db_session: Session) -> None:
    _seed_reference_row(db_session)

    results = reference_service.find_reference_context(db_session, district="Thanjavur")

    assert len(results) == 1
    assert isinstance(results[0], reference_service.ReferenceContext)
    assert results[0].metric_name == "paddy_area"


def test_find_reference_context_district_matching(db_session: Session) -> None:
    _seed_reference_row(db_session, district="Thanjavur")
    _seed_reference_row(db_session, district="Thiruvarur", source="Other district fixture")

    results = reference_service.find_reference_context(db_session, district="Thiruvarur")

    assert len(results) == 1
    assert results[0].district == "Thiruvarur"


def test_find_reference_context_season_matching(db_session: Session) -> None:
    _seed_reference_row(db_session, season_or_period="2024-25", source="Season A")
    _seed_reference_row(db_session, season_or_period="2025-26", source="Season B")

    results = reference_service.find_reference_context(
        db_session, district="Thanjavur", season_or_period="2025-26"
    )

    assert len(results) == 1
    assert results[0].season_or_period == "2025-26"


def test_find_reference_context_metric_matching(db_session: Session) -> None:
    _seed_reference_row(db_session, metric_name="paddy_area", source="Metric A")
    _seed_reference_row(
        db_session,
        metric_name="modal_price_per_quintal",
        dataset_type="AGMARKNET_PRICE",
        source="Metric B",
    )

    results = reference_service.find_reference_context(
        db_session, district="Thanjavur", metric_name="modal_price_per_quintal"
    )

    assert len(results) == 1
    assert results[0].metric_name == "modal_price_per_quintal"


def test_find_reference_context_dataset_type_matching(db_session: Session) -> None:
    _seed_reference_row(
        db_session, dataset_type="SEASON_CROP_REPORT", source="Dataset A"
    )
    _seed_reference_row(
        db_session,
        dataset_type="AGMARKNET_PRICE",
        metric_name="modal_price_per_quintal",
        source="Dataset B",
    )

    results = reference_service.find_reference_context(
        db_session, district="Thanjavur", dataset_type="AGMARKNET_PRICE"
    )

    assert len(results) == 1
    assert results[0].dataset_type == "AGMARKNET_PRICE"


def test_find_reference_context_missing_data_returns_empty_list(db_session: Session) -> None:
    """No reference data at all for the district - not an error."""
    results = reference_service.find_reference_context(db_session, district="Thanjavur")

    assert results == []


def test_find_reference_context_unsupported_metric_returns_empty_list(
    db_session: Session,
) -> None:
    _seed_reference_row(db_session, metric_name="paddy_area")

    results = reference_service.find_reference_context(
        db_session, district="Thanjavur", metric_name="yield_per_hectare"
    )

    assert results == []


def test_find_reference_context_preserves_incomplete_demo_provenance(
    db_session: Session,
) -> None:
    """A DEMO row (no source/source_reference/retrieved_at) must still be
    returned with those fields honestly reflected as None, not fabricated
    or hidden."""
    _seed_reference_row(
        db_session,
        data_status="DEMO",
        source=None,
        source_reference=None,
        retrieved_at=None,
    )

    results = reference_service.find_reference_context(db_session, district="Thanjavur")

    assert len(results) == 1
    assert results[0].data_status == "DEMO"
    assert results[0].source is None
    assert results[0].source_reference is None
    assert results[0].retrieved_at is None


def test_find_reference_context_preserves_full_provenance(db_session: Session) -> None:
    _seed_reference_row(db_session)

    results = reference_service.find_reference_context(db_session, district="Thanjavur")

    fact = results[0]
    assert fact.dataset_type == "SEASON_CROP_REPORT"
    assert fact.district == "Thanjavur"
    assert fact.season_or_period == "2024-25"
    assert fact.metric_name == "paddy_area"
    assert fact.metric_value == Decimal("2.10")
    assert fact.unit == "lakh hectares"
    assert fact.data_status == "REAL"
    assert fact.source == "Test fixture - not the real Season and Crop Report"
    assert fact.source_reference == "https://example.test/season-crop-report"
    # SQLite drops tzinfo on read for DateTime(timezone=True) columns
    # (unlike PostgreSQL, the actual deployment target) - compare the
    # naive wall-clock value, which is what's actually preserved either
    # way.
    assert fact.retrieved_at.replace(tzinfo=None) == datetime(2026, 9, 9)


def test_find_reference_context_is_deterministic(db_session: Session) -> None:
    _seed_reference_row(db_session)

    first = reference_service.find_reference_context(db_session, district="Thanjavur")
    second = reference_service.find_reference_context(db_session, district="Thanjavur")

    assert first == second


# ---------------------------------------------------------------------------
# app.services.procurement_context.get_centre_agricultural_context
# ---------------------------------------------------------------------------


def test_get_centre_agricultural_context_resolves_centre_district(
    db_session: Session,
) -> None:
    _seed_reference_row(db_session)
    centre = thanjavur_centre(db_session)

    context = procurement_context_service.get_centre_agricultural_context(
        db_session, centre.id
    )

    assert context.centre_id == centre.id
    assert context.district == "Thanjavur"
    assert len(context.reference_facts) == 1
    assert context.reference_facts[0].metric_name == "paddy_area"


def test_get_centre_agricultural_context_with_no_reference_data(
    db_session: Session,
) -> None:
    """A valid centre whose district has no reference data yet must return
    a clean, empty result - never an error."""
    centre = thanjavur_centre(db_session)

    context = procurement_context_service.get_centre_agricultural_context(
        db_session, centre.id
    )

    assert context.centre_id == centre.id
    assert context.reference_facts == []


def test_get_centre_agricultural_context_applies_filters(db_session: Session) -> None:
    _seed_reference_row(db_session, metric_name="paddy_area", source="A")
    _seed_reference_row(
        db_session,
        metric_name="modal_price_per_quintal",
        dataset_type="AGMARKNET_PRICE",
        source="B",
    )
    centre = thanjavur_centre(db_session)

    context = procurement_context_service.get_centre_agricultural_context(
        db_session, centre.id, metric_name="paddy_area"
    )

    assert len(context.reference_facts) == 1
    assert context.reference_facts[0].metric_name == "paddy_area"


def test_get_centre_agricultural_context_unknown_centre_raises_404(
    db_session: Session,
) -> None:
    with pytest.raises(procurement_context_service.ProcurementContextError) as excinfo:
        procurement_context_service.get_centre_agricultural_context(db_session, 999999)

    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# API: GET /api/centres/{centre_id}/reference-context
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_returns_matching_reference_context(
    client: AsyncClient, db_session: Session
) -> None:
    _seed_reference_row(db_session)
    centre = thanjavur_centre(db_session)

    response = await client.get(f"/api/centres/{centre.id}/reference-context")

    assert response.status_code == 200
    body = response.json()
    assert body["centre_id"] == centre.id
    assert body["district"] == "Thanjavur"
    assert len(body["reference_facts"]) == 1
    fact = body["reference_facts"][0]
    assert fact["metric_name"] == "paddy_area"
    assert fact["data_status"] == "REAL"
    assert fact["source"] == "Test fixture - not the real Season and Crop Report"
    # No database internals leak into the response.
    assert "id" not in fact
    assert "imported_at" not in fact
    assert "raw_payload" not in fact


@pytest.mark.anyio
async def test_api_returns_empty_facts_when_no_reference_data(
    client: AsyncClient, db_session: Session
) -> None:
    centre = thanjavur_centre(db_session)

    response = await client.get(f"/api/centres/{centre.id}/reference-context")

    assert response.status_code == 200
    body = response.json()
    assert body["reference_facts"] == []


@pytest.mark.anyio
async def test_api_filters_by_query_params(
    client: AsyncClient, db_session: Session
) -> None:
    _seed_reference_row(db_session, metric_name="paddy_area", source="A")
    _seed_reference_row(
        db_session,
        metric_name="modal_price_per_quintal",
        dataset_type="AGMARKNET_PRICE",
        source="B",
    )
    centre = thanjavur_centre(db_session)

    response = await client.get(
        f"/api/centres/{centre.id}/reference-context",
        params={"dataset_type": "AGMARKNET_PRICE"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["reference_facts"]) == 1
    assert body["reference_facts"][0]["metric_name"] == "modal_price_per_quintal"


@pytest.mark.anyio
async def test_api_unknown_centre_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/centres/999999/reference-context")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_api_reference_context_endpoint_is_public(db_session: Session) -> None:
    """Matches this router's existing convention (centre listing and slot
    listing are also unauthenticated) - see app/api/routers/centres.py."""
    _seed_reference_row(db_session)
    centre = thanjavur_centre(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as anon:
            response = await anon.get(f"/api/centres/{centre.id}/reference-context")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Failure isolation: scheduling/ETA/queue/booking must never be affected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module",
    [
        "app.services.scheduling",
        "app.services.eta",
        "app.services.throughput",
        "app.services.queue",
        "app.services.bookings",
    ],
)
def test_operational_services_do_not_import_reference_layer(module: str) -> None:
    """Structural guard: the scheduling/ETA/throughput/queue/booking
    services must never import the reference-data layer or the
    procurement-context adapter. This is what makes isolation a property
    of the code, not just of today's test scenarios - if this ever
    starts failing, a change introduced a coupling this milestone
    deliberately avoided."""
    imported_module = __import__(module, fromlist=["_"])
    source = inspect.getsource(imported_module)

    assert "reference_data" not in source
    assert "procurement_context" not in source
    assert "reference_repository" not in source
    assert "import reference" not in source


@pytest.mark.anyio
async def test_scheduling_assessment_unaffected_by_reference_data_presence(
    client: AsyncClient, db_session: Session
) -> None:
    """Booking + scheduling assessment must produce the same outcome
    whether or not reference data exists for the centre's district."""
    from app.models import Farmer, ProcurementSlot

    farmer = db_session.scalar(select(Farmer).where(Farmer.phone == "9000000001"))
    centre = thanjavur_centre(db_session)
    slot = db_session.scalar(
        select(ProcurementSlot)
        .where(ProcurementSlot.centre_id == centre.id, ProcurementSlot.capacity > 0)
        .order_by(ProcurementSlot.id)
    )
    assert farmer is not None and slot is not None

    booking_payload = {
        "farmer_id": farmer.id,
        "centre_id": centre.id,
        "slot_id": slot.id,
        "crop_type": "Paddy",
        "quantity_kg": 500,
    }

    create_response = await client.post("/api/bookings/", json=booking_payload)
    assert create_response.status_code == 201
    booking_id = create_response.json()["id"]

    without_reference = await client.get(f"/api/scheduling/bookings/{booking_id}")
    assert without_reference.status_code == 200
    without_body = without_reference.json()

    _seed_reference_row(db_session)

    with_reference = await client.get(f"/api/scheduling/bookings/{booking_id}")
    assert with_reference.status_code == 200
    with_body = with_reference.json()

    # Identical scheduling outcome and response shape regardless of
    # whether reference data exists for this centre's district.
    assert with_body == without_body


@pytest.mark.anyio
async def test_scheduling_still_works_when_reference_layer_raises(
    client: AsyncClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if the reference-data layer were to start raising unexpectedly,
    an existing scheduling assessment must be completely unaffected - this
    is only possible because scheduling.py never calls into it (see the
    structural test above); this test additionally proves it end-to-end
    through the API."""
    from app.models import Farmer, ProcurementSlot

    farmer = db_session.scalar(select(Farmer).where(Farmer.phone == "9000000001"))
    centre = thanjavur_centre(db_session)
    slot = db_session.scalar(
        select(ProcurementSlot)
        .where(ProcurementSlot.centre_id == centre.id, ProcurementSlot.capacity > 0)
        .order_by(ProcurementSlot.id)
    )
    assert farmer is not None and slot is not None

    booking_payload = {
        "farmer_id": farmer.id,
        "centre_id": centre.id,
        "slot_id": slot.id,
        "crop_type": "Paddy",
        "quantity_kg": 500,
    }
    create_response = await client.post("/api/bookings/", json=booking_payload)
    assert create_response.status_code == 201
    booking_id = create_response.json()["id"]

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated reference-layer failure")

    monkeypatch.setattr(reference_repository, "list_reference_data", _boom)

    response = await client.get(f"/api/scheduling/bookings/{booking_id}")

    assert response.status_code == 200


def test_procurement_context_module_isolates_reference_layer_failures(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reference-context lookup itself is allowed to fail loudly (it
    IS the reference feature) - but that failure must not corrupt
    anything about the centre lookup that happened first, and must be a
    plain, catchable exception rather than something that could crash an
    unrelated request."""
    centre = thanjavur_centre(db_session)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated reference-layer failure")

    monkeypatch.setattr(reference_repository, "list_reference_data", _boom)

    with pytest.raises(RuntimeError):
        procurement_context_service.get_centre_agricultural_context(db_session, centre.id)
