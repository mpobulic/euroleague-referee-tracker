"""
Euroleague public API client.

Base URL: https://api.euroleague.net
No authentication required for public endpoints.

Key endpoints used:
  GET /v2/competitions/{comp}/seasons/{season}/games
  GET /v1/games?seasonCode={season}&gameCode={code}   -> play-by-play
  GET /v2/competitions/{comp}/seasons/{season}/rounds/{round}/games
  GET /v2/competitions/{comp}/seasons/{season}/people -> referees
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_HEADERS = {"Accept": "application/json", "User-Agent": "euroleague-referee-tracker/1.0"}


class EuroleagueAPIError(Exception):
    pass


class EuroleagueClient:
    """Async HTTP client for the Euroleague public API."""

    def __init__(self) -> None:
        self._base = settings.euroleague_api_base.rstrip("/")
        self._comp = settings.euroleague_competition_code
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "EuroleagueClient":
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers=_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None) -> Any:
        assert self._client is not None, "Use as async context manager"
        response = await self._client.get(path, params=params)
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 5))
            logger.warning("Rate limited; sleeping %ds", retry_after)
            await asyncio.sleep(retry_after)
            raise httpx.TransportError("rate limited")
        response.raise_for_status()
        return response.json()

    # ── Seasons ───────────────────────────────────────────────────────────────

    async def get_seasons(self) -> list[dict]:
        """Return all available seasons for the competition."""
        data = await self._get(f"/v2/competitions/{self._comp}/seasons")
        if not data:
            return []
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_season(self, season_code: str) -> dict | None:
        return await self._get(f"/v2/competitions/{self._comp}/seasons/{season_code}")

    # ── Games ─────────────────────────────────────────────────────────────────

    async def get_games(self, season_code: str) -> list[dict]:
        """Return all games for a season."""
        data = await self._get(
            f"/v2/competitions/{self._comp}/seasons/{season_code}/games"
        )
        if not data:
            return []
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_games_by_round(self, season_code: str, round_number: int) -> list[dict]:
        data = await self._get(
            f"/v2/competitions/{self._comp}/seasons/{season_code}/rounds/{round_number}/games"
        )
        if not data:
            return []
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_game(self, season_code: str, game_code: str) -> dict | None:
        """Return header data for a single game."""
        data = await self._get(
            f"/v2/competitions/{self._comp}/seasons/{season_code}/games/{game_code}"
        )
        return data

    # ── Play-by-play ──────────────────────────────────────────────────────────

    async def get_play_by_play(self, season_code: str, game_code: str) -> list[dict]:
        """
        Return all play-by-play events for a game.
        Euroleague v1 endpoint returns the full PBP feed.
        """
        data = await self._get(
            "/v1/games",
            params={"seasonCode": season_code, "gameCode": game_code},
        )
        if not data:
            return []
        # PBP lives under 'Rows' or 'data' depending on endpoint version
        if isinstance(data, dict):
            return data.get("Rows", data.get("rows", data.get("data", [])))
        return data

    # ── Referees ──────────────────────────────────────────────────────────────

    async def get_game_referees(self, season_code: str, game_code: str) -> list[dict]:
        """Return referees who officiated a specific game."""
        data = await self._get(
            f"/v2/competitions/{self._comp}/seasons/{season_code}/games/{game_code}/referees"
        )
        if not data:
            return []
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_season_referees(self, season_code: str) -> list[dict]:
        """Return all referees active in a season (not always available)."""
        data = await self._get(
            f"/v2/competitions/{self._comp}/seasons/{season_code}/people",
            params={"role": "referees"},
        )
        if not data:
            return []
        return data.get("data", data) if isinstance(data, dict) else data

    # ── Teams ─────────────────────────────────────────────────────────────────

    async def get_teams(self, season_code: str) -> list[dict]:
        data = await self._get(
            f"/v2/competitions/{self._comp}/seasons/{season_code}/clubs"
        )
        if not data:
            return []
        return data.get("data", data) if isinstance(data, dict) else data

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def get_game_stats(self, season_code: str, game_code: str) -> dict | None:
        """Box score / game stats."""
        return await self._get(
            f"/v2/competitions/{self._comp}/seasons/{season_code}/games/{game_code}/stats"
        )
