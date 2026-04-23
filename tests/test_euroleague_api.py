"""Tests for the Euroleague API client."""
from __future__ import annotations

import pytest
import respx
import httpx

from ingestion.euroleague_api import EuroleagueClient


@pytest.fixture
def mock_base():
    return "https://api.euroleague.net"


@respx.mock
@pytest.mark.asyncio
async def test_get_seasons_returns_list():
    respx.get("https://api.euroleague.net/v2/competitions/E/seasons").mock(
        return_value=httpx.Response(200, json={"data": [{"code": "E2024", "year": 2024, "name": "2024-25"}]})
    )
    async with EuroleagueClient() as client:
        seasons = await client.get_seasons()
    assert len(seasons) == 1
    assert seasons[0]["code"] == "E2024"


@respx.mock
@pytest.mark.asyncio
async def test_get_seasons_404_returns_empty():
    respx.get("https://api.euroleague.net/v2/competitions/E/seasons").mock(
        return_value=httpx.Response(404)
    )
    async with EuroleagueClient() as client:
        seasons = await client.get_seasons()
    assert seasons == []


@respx.mock
@pytest.mark.asyncio
async def test_get_play_by_play_parses_rows():
    pbp_payload = {
        "Rows": [
            {"PLAYTYPE": "FV", "PERIOD": 1, "MARKERTIME": "08:34", "TEAM": "MAD"},
            {"PLAYTYPE": "2FGM", "PERIOD": 1, "MARKERTIME": "08:32", "TEAM": "BAR"},
        ]
    }
    respx.get("https://api.euroleague.net/v1/games").mock(
        return_value=httpx.Response(200, json=pbp_payload)
    )
    async with EuroleagueClient() as client:
        events = await client.get_play_by_play("E2024", "1")
    assert len(events) == 2
    assert events[0]["PLAYTYPE"] == "FV"


@respx.mock
@pytest.mark.asyncio
async def test_get_games_by_round():
    respx.get(
        "https://api.euroleague.net/v2/competitions/E/seasons/E2024/rounds/5/games"
    ).mock(return_value=httpx.Response(200, json=[{"code": "G100"}]))
    async with EuroleagueClient() as client:
        games = await client.get_games_by_round("E2024", 5)
    assert games[0]["code"] == "G100"
