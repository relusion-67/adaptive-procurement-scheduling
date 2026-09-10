import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.main import app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_root_endpoint(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "message": "Adaptive Procurement Scheduling API is running -v2"
    }


@pytest.mark.anyio
async def test_health_endpoint(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # /health reflects real Postgres connectivity (see app/db/health.py), so
    # it must not depend on a real Postgres instance actually being
    # reachable from wherever `pytest` happens to run - a teammate without
    # a local Postgres running (or without DATABASE_URL configured for one)
    # would otherwise see this test flake/fail for a reason that has
    # nothing to do with application behavior. Patch the connectivity
    # check itself so this test verifies the endpoint's *handling* of a
    # healthy DB, independent of whatever database (if any) is configured
    # in this environment.
    monkeypatch.setattr(main_module, "can_connect_to_database", lambda: True)
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.anyio
async def test_health_endpoint_reports_unhealthy_when_db_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "can_connect_to_database", lambda: False)
    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "detail": "database unreachable"}


@pytest.mark.anyio
async def test_api_test_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/test")
    assert response.status_code == 200
    assert response.json() == {
        "message": "React successfully connected to FastAPI!"
    }
