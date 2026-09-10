from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core import clock
from app.db.seed import seed_demo_data
from app.db.session import get_db
from app.main import app
from app.models import ProcurementCentre, ThroughputSnapshot
from app.repositories import reference as reference_repository
from app.services import procurement_insights as insights_service
from app.services.scheduling import SchedulingStatus
from tests._auth_helpers import auth_headers, create_admin, create_staff_user


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        clock,
        "utcnow",
        lambda: datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'procurement_insights.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(sqlite_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_demo_data(session, today=datetime(2026, 6, 15).date())
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
    admin = create_admin(db_session, email="insights-admin@example.test")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers=auth_headers(admin),
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def centre(session: Session) -> ProcurementCentre:
    result = session.scalar(
        select(ProcurementCentre).where(ProcurementCentre.code == "TNJ-CENTRAL-01")
    )
    assert result is not None
    return result


@pytest.mark.anyio
async def test_insight_returns_operational_snapshot_without_reference_data(
    client: AsyncClient,
    db_session: Session,
) -> None:
    response = await client.get(f"/api/centres/{centre(db_session).id}/procurement-insights")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["centre_code"] == "TNJ-CENTRAL-01"
    assert body["operational_status"] in {"ON_TRACK", "AT_RISK", "DELAYED"}
    assert body["metrics"]["active_booking_count"] == 3
    assert body["reference_context"] == []
    assert body["reasons"]
    assert body["recommendations"]
    assert body["recommendations"] == sorted(
        body["recommendations"], key=lambda item: item["priority"]
    )


@pytest.mark.anyio
async def test_insight_preserves_reference_provenance(
    client: AsyncClient,
    db_session: Session,
) -> None:
    target = centre(db_session)
    reference_repository.create_reference_row(
        db_session,
        dataset_type="SEASON_CROP_REPORT",
        district=target.district,
        season_or_period="2024-25",
        metric_name="paddy_area",
        metric_value=Decimal("2.10"),
        unit="lakh hectares",
        data_status="REAL",
        source="Test report",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    db_session.commit()

    response = await client.get(f"/api/centres/{target.id}/procurement-insights")

    assert response.status_code == 200, response.text
    fact = response.json()["reference_context"][0]
    assert fact["metric_name"] == "paddy_area"
    assert fact["source"] == "Test report"
    assert fact["source_reference"] == "https://example.test/report"
    assert fact["data_status"] == "REAL"
    assert fact["retrieved_at"].startswith("2026-06-01")


@pytest.mark.anyio
async def test_insight_unknown_centre_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/centres/999999/procurement-insights")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_insight_inactive_centre_returns_409(
    client: AsyncClient,
    db_session: Session,
) -> None:
    target = centre(db_session)
    target.active = False
    db_session.commit()

    response = await client.get(f"/api/centres/{target.id}/procurement-insights")

    assert response.status_code == 409


@pytest.mark.anyio
async def test_insight_rejects_staff_from_another_centre(
    db_session: Session,
) -> None:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    first = centre(db_session)
    other = db_session.scalar(
        select(ProcurementCentre).where(ProcurementCentre.code == "KUM-01")
    )
    assert other is not None
    staff = create_staff_user(db_session, other)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers=auth_headers(staff),
        ) as staff_client:
            response = await staff_client.get(
                f"/api/centres/{first.id}/procurement-insights"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_recommendations_are_deterministic_and_evidence_based() -> None:
    delayed = type("Assessment", (), {"scheduling_status": SchedulingStatus.DELAYED})()
    at_risk = type("Assessment", (), {"scheduling_status": SchedulingStatus.AT_RISK})()

    first = insights_service._build_recommendations(
        [delayed, at_risk],
        queue_depth=2,
        current_serving_token=None,
        has_throughput=False,
    )
    second = insights_service._build_recommendations(
        [delayed, at_risk],
        queue_depth=2,
        current_serving_token=None,
        has_throughput=False,
    )

    assert first == second
    assert [recommendation.code for recommendation in first] == [
        "REVIEW_DELAYED_BOOKINGS",
        "MONITOR_AT_RISK_BOOKINGS",
        "START_QUEUE_SERVICE",
        "CAPTURE_THROUGHPUT_DATA",
    ]
    assert all(recommendation.evidence for recommendation in first)


def test_empty_centre_recommends_no_action() -> None:
    recommendations = insights_service._build_recommendations(
        [],
        queue_depth=0,
        current_serving_token=None,
        has_throughput=False,
    )

    assert [recommendation.code for recommendation in recommendations] == [
        "NO_ACTION_REQUIRED"
    ]


def test_reference_context_cannot_change_operational_inputs(db_session: Session) -> None:
    target = centre(db_session)
    snapshot = ThroughputSnapshot(
        centre_id=target.id,
        snapshot_at=clock.utcnow(),
        avg_minutes_per_farmer=Decimal("12.50"),
    )
    db_session.add(snapshot)
    db_session.commit()

    from app.services.procurement_insights import get_centre_procurement_insight

    before = get_centre_procurement_insight(db_session, target.id)
    reference_repository.create_reference_row(
        db_session,
        dataset_type="SEASON_CROP_REPORT",
        district=target.district,
        season_or_period="2024-25",
        metric_name="paddy_area",
        metric_value=Decimal("999.00"),
        unit="lakh hectares",
        data_status="DEMO",
        source=None,
        source_reference=None,
        retrieved_at=None,
    )
    db_session.commit()
    after = get_centre_procurement_insight(db_session, target.id)

    assert after.metrics == before.metrics
    assert after.operational_status == before.operational_status
