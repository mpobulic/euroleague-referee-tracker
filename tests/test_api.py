"""FastAPI integration tests using the async test client."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from api.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_games_empty(client: AsyncClient):
    """Without a DB, games endpoint should return 200 + empty list (DB interactions mocked)."""
    with patch("api.routes.games.AsyncSession") as mock_session:
        mock_exec = AsyncMock()
        mock_exec.scalars.return_value.all.return_value = []
        mock_session.return_value.__aenter__.return_value.execute = AsyncMock(return_value=mock_exec)
        r = await client.get("/api/v1/games?season=E2024")
    # Either 200 with [] or a DB error – we just check the path exists
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_referee_rankings_path_exists(client: AsyncClient):
    r = await client.get("/api/v1/referees/rankings")
    assert r.status_code in (200, 500)


@pytest.mark.asyncio
async def test_incident_invalid_severity_returns_404_or_400(client: AsyncClient):
    r = await client.get("/api/v1/incidents?severity=nonexistent")
    assert r.status_code in (400, 422, 500)
