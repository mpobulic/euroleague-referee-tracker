"""
Ingestion pipeline – fetches games, PBP, referees from the Euroleague API
and upserts them into the database.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Game, GameReferee, PlayByPlayEvent, Referee, Season, Team
from ingestion.euroleague_api import EuroleagueClient
from models.call_classifier import CallClassifier
from models.context_builder import build_context_for_event

log = structlog.get_logger(__name__)


class IngestionPipeline:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.classifier = CallClassifier()

    # ── Public API ────────────────────────────────────────────────────────────

    async def ingest_round(self, season_code: str, round_number: int) -> None:
        log.info("Ingesting round", season=season_code, round=round_number)
        async with EuroleagueClient() as client:
            season = await self._ensure_season(client, season_code)
            games_data = await client.get_games_by_round(season_code, round_number)
            await self._ingest_games(client, season, games_data, season_code)

    async def ingest_all_rounds(self, season_code: str) -> None:
        async with EuroleagueClient() as client:
            season = await self._ensure_season(client, season_code)
            all_games = await client.get_games(season_code)
            await self._ingest_games(client, season, all_games, season_code)

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _ensure_season(self, client: EuroleagueClient, season_code: str) -> Season:
        result = await self.session.execute(select(Season).where(Season.code == season_code))
        season = result.scalar_one_or_none()
        if season is None:
            data = await client.get_season(season_code) or {}
            season = Season(
                code=season_code,
                competition_code=data.get("competitionCode", "E"),
                name=data.get("name", season_code),
                year=int(data.get("year", season_code[1:5])),
            )
            self.session.add(season)
            await self.session.flush()
        return season

    async def _ensure_team(self, raw: dict) -> Team:
        code = raw.get("code") or raw.get("clubCode") or raw.get("teamCode", "UNK")
        result = await self.session.execute(select(Team).where(Team.code == code))
        team = result.scalar_one_or_none()
        if team is None:
            team = Team(
                code=code,
                name=raw.get("name") or raw.get("clubName") or code,
                full_name=raw.get("fullName") or raw.get("clubName"),
                country=raw.get("country"),
            )
            self.session.add(team)
            await self.session.flush()
        return team

    async def _ensure_referee(self, raw: dict) -> Referee:
        name = raw.get("name") or raw.get("fullName") or "Unknown"
        ext_id = str(raw.get("id") or raw.get("personId") or "")
        result = await self.session.execute(
            select(Referee).where(Referee.external_id == ext_id) if ext_id
            else select(Referee).where(Referee.name == name)
        )
        referee = result.scalar_one_or_none()
        if referee is None:
            referee = Referee(
                external_id=ext_id or None,
                name=name,
                country=raw.get("country"),
            )
            self.session.add(referee)
            await self.session.flush()
        return referee

    async def _ingest_games(
        self,
        client: EuroleagueClient,
        season: Season,
        games_data: list[dict],
        season_code: str,
    ) -> None:
        semaphore = asyncio.Semaphore(4)

        async def _process(raw_game: dict) -> None:
            async with semaphore:
                await self._ingest_single_game(client, season, raw_game, season_code)

        await asyncio.gather(*[_process(g) for g in games_data], return_exceptions=True)
        await self.session.commit()
        log.info("Round ingestion complete", season=season_code, games=len(games_data))

    async def _ingest_single_game(
        self,
        client: EuroleagueClient,
        season: Season,
        raw: dict,
        season_code: str,
    ) -> None:
        game_code = str(raw.get("code") or raw.get("gameCode") or "")
        if not game_code:
            return

        # Upsert game record
        result = await self.session.execute(
            select(Game).where(Game.game_code == game_code, Game.season_id == season.id)
        )
        game = result.scalar_one_or_none()

        home_data = raw.get("homeClub") or raw.get("home") or {}
        away_data = raw.get("awayClub") or raw.get("away") or {}
        home_team = await self._ensure_team(home_data)
        away_team = await self._ensure_team(away_data)

        if game is None:
            game = Game(
                season_id=season.id,
                game_code=game_code,
                round_number=raw.get("round") or raw.get("roundNumber") or 0,
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                venue=raw.get("stadium") or raw.get("arena"),
            )
            self.session.add(game)
            await self.session.flush()

        game.home_score = raw.get("homeScore") or raw.get("score", {}).get("home")
        game.away_score = raw.get("awayScore") or raw.get("score", {}).get("away")

        # Ingest referees
        refs_data = await client.get_game_referees(season_code, game_code)
        for ref_raw in refs_data:
            referee = await self._ensure_referee(ref_raw)
            existing = await self.session.execute(
                select(GameReferee).where(
                    GameReferee.game_id == game.id,
                    GameReferee.referee_id == referee.id,
                )
            )
            if existing.scalar_one_or_none() is None:
                self.session.add(GameReferee(
                    game_id=game.id,
                    referee_id=referee.id,
                    role=ref_raw.get("role"),
                ))

        # Ingest play-by-play
        if not game.pbp_ingested:
            pbp_events = await client.get_play_by_play(season_code, game_code)
            await self._ingest_pbp(game, pbp_events)
            game.pbp_ingested = True

        await self.session.flush()
        log.info("Game ingested", game_code=game_code)

    async def _ingest_pbp(self, game: Game, events: list[dict]) -> None:
        for raw in events:
            play_type = raw.get("PLAYTYPE") or raw.get("playType") or ""
            ev = PlayByPlayEvent(
                game_id=game.id,
                period=raw.get("PERIOD") or raw.get("period") or 1,
                game_clock=raw.get("MARKERTIME") or raw.get("gameClock") or "00:00",
                play_type=play_type,
                play_info=raw.get("PLAYINFO") or raw.get("description"),
                player_id=str(raw.get("PLAYER_ID") or raw.get("personId") or ""),
                player_name=raw.get("PLAYER") or raw.get("playerName"),
                team_code=raw.get("TEAM") or raw.get("teamCode"),
                home_score=raw.get("HOMESCORE") or raw.get("homeScore"),
                away_score=raw.get("VISITSCORE") or raw.get("awayScore"),
                coordinates_x=raw.get("COORD_X") or raw.get("xLegacy"),
                coordinates_y=raw.get("COORD_Y") or raw.get("yLegacy"),
            )
            self.session.add(ev)

        await self.session.flush()
