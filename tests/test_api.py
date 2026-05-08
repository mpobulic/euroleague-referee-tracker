"""FastAPI integration tests using the async test client."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from api.main import app
from db.connection import get_session


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_games_empty(client: AsyncClient, mock_session: AsyncMock):
    """Games endpoint should return 200 with an empty list when no games exist."""
    class MockResult:
        def all(self):
            return []

    mock_result = MockResult()
    mock_session.execute.return_value = mock_result

    async def override_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        r = await client.get("/api/v1/games?season=E2024")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_referee_rankings_path_exists(client: AsyncClient):
    async def override_get_session():
        yield object()

    app.dependency_overrides[get_session] = override_get_session
    try:
        with patch("api.routes.referees.get_referee_rankings", new=AsyncMock(return_value=[])):
            r = await client.get("/api/v1/referees/rankings")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_incident_invalid_severity_returns_422(client: AsyncClient):
    r = await client.get("/api/v1/incidents?severity=nonexistent")
    assert r.status_code == 422
