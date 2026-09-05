import pytest
from httpx import ASGITransport, AsyncClient

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
async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.anyio
async def test_api_test_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/test")
    assert response.status_code == 200
    assert response.json() == {
        "message": "React successfully connected to FastAPI!"
    }
