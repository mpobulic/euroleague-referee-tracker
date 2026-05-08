"""
Ingestion pipeline – fetches games, PBP, referees from the Euroleague API
and upserts them into the database.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import (
    ClassificationSource,
    Game,
    GameReferee,
    Incident,
    IncidentType,
    PlayByPlayEvent,
    Referee,
    Season,
    Team,
)
from ingestion.euroleague_api import EuroleagueClient
from ingestion.video_processor import VideoProcessor, game_clock_to_seconds
from models.call_classifier import CallClassifier
from models.context_builder import build_context_for_event

log = structlog.get_logger(__name__)

_CANDIDATE_PLAY_TYPES = {
    "FV",
    "FT",
    "FO",
    "F",
    "TFOUL",
    "PFOUL",
    "FOUL",
    "TO",
    "TREV",
    "DBLDRIB",
    "VIO",
    "VIOLATION",
    "3SEC",
    "5SEC",
    "8SEC",
    "24SEC",
}


class IngestionPipeline:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.classifier = CallClassifier()
        self.video_processor = VideoProcessor() if settings.enable_vision_classification else None

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

        results = await asyncio.gather(*[_process(g) for g in games_data], return_exceptions=True)
        failures: list[tuple[str, Exception]] = []
        for raw_game, result in zip(games_data, results, strict=False):
            if isinstance(result, Exception):
                game_code = str(raw_game.get("code") or raw_game.get("gameCode") or "unknown")
                failures.append((game_code, result))

        if failures:
            for game_code, exc in failures:
                log.error(
                    "Game ingestion failed",
                    season=season_code,
                    game_code=game_code,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            await self.session.rollback()
            raise RuntimeError(
                f"Failed to ingest {len(failures)} of {len(games_data)} games for season {season_code}"
            )

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
        game.video_url = (
            raw.get("videoUrl")
            or raw.get("vodUrl")
            or raw.get("video_url")
            or game.video_url
        )

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

        if not game.analysis_complete:
            await self._analyze_game_events(game)
            game.analysis_complete = True

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

    async def _analyze_game_events(self, game: Game) -> None:
        events = (
            await self.session.execute(
                select(PlayByPlayEvent)
                .where(PlayByPlayEvent.game_id == game.id)
                .order_by(PlayByPlayEvent.id)
            )
        ).scalars().all()

        if not events:
            log.info("No play-by-play events available for analysis", game_code=game.game_code)
            return

        await self.session.execute(
            delete(Incident).where(
                Incident.game_id == game.id,
                Incident.classification_source.in_(
                    [ClassificationSource.AI_CONTEXT, ClassificationSource.AI_VISION]
                ),
            )
        )

        events_data = [self._pbp_event_to_dict(ev) for ev in events]
        video_path = await self._prepare_video_for_game(game)
        incident_count = 0
        for event_data, event in zip(events_data, events, strict=False):
            if not _is_candidate_event(event_data.get("play_type", "")):
                continue

            context = build_context_for_event(
                event_data,
                events_data,
                game.home_team.code if game.home_team else "",
                game.away_team.code if game.away_team else "",
            )
            frame_path = await self._extract_frame_for_event(game, event, video_path)
            result = await self.classifier.classify(context=context, frame_path=frame_path)
            if not result.is_error:
                continue

            classification_source = (
                ClassificationSource.AI_VISION if frame_path is not None else ClassificationSource.AI_CONTEXT
            )
            incident = Incident(
                game_id=game.id,
                pbp_event_id=event.id,
                incident_type=result.incident_type or IncidentType.OTHER,
                severity=result.severity,
                classification_source=classification_source,
                period=event.period,
                game_clock=event.game_clock,
                score_differential=_safe_score_diff(event.home_score, event.away_score),
                team_benefited=_team_benefited_for_event(
                    event.team_code, game.home_team.code if game.home_team else None, game.away_team.code if game.away_team else None
                ),
                team_harmed=event.team_code,
                ai_confidence=result.confidence,
                ai_reasoning=result.reasoning,
                ai_model=result.model_used,
                video_timestamp_seconds=event.video_timestamp_seconds,
                description=result.correct_call_should_be,
            )
            self.session.add(incident)
            incident_count += 1

        await self.session.flush()
        log.info("Game analysis complete", game_code=game.game_code, incidents_created=incident_count)

    async def _prepare_video_for_game(self, game: Game) -> Path | None:
        if not self.video_processor or not game.video_url:
            return None
        try:
            video_path = await asyncio.wait_for(
                self.video_processor.download_game_video(game.game_code, game.video_url),
                timeout=settings.vision_download_timeout_seconds,
            )
        except TimeoutError:
            log.warning(
                "Video download timed out; falling back to context-only analysis",
                game_code=game.game_code,
                timeout_seconds=settings.vision_download_timeout_seconds,
            )
            return None
        except Exception as exc:
            log.warning(
                "Video download failed; falling back to context-only analysis",
                game_code=game.game_code,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None
        if video_path is not None:
            game.video_downloaded = True
        return video_path

    async def _extract_frame_for_event(
        self,
        game: Game,
        event: PlayByPlayEvent,
        video_path: Path | None,
    ) -> Path | None:
        if not self.video_processor or video_path is None:
            return None
        timestamp_seconds = game_clock_to_seconds(event.period, event.game_clock)
        for attempt in range(1, settings.vision_frame_extract_retries + 1):
            try:
                return await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        self.video_processor.extract_key_frame,
                        video_path,
                        game.game_code,
                        event.id,
                        timestamp_seconds,
                    ),
                    timeout=settings.vision_frame_extract_timeout_seconds,
                )
            except TimeoutError:
                log.warning(
                    "Frame extraction timed out",
                    game_code=game.game_code,
                    event_id=event.id,
                    attempt=attempt,
                    timeout_seconds=settings.vision_frame_extract_timeout_seconds,
                )
            except Exception as exc:
                log.warning(
                    "Frame extraction failed",
                    game_code=game.game_code,
                    event_id=event.id,
                    attempt=attempt,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        return None

    @staticmethod
    def _pbp_event_to_dict(event: PlayByPlayEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "period": event.period,
            "game_clock": event.game_clock,
            "play_type": event.play_type,
            "play_info": event.play_info,
            "player_name": event.player_name,
            "team_code": event.team_code,
            "home_score": event.home_score,
            "away_score": event.away_score,
            "coordinates_x": event.coordinates_x,
            "coordinates_y": event.coordinates_y,
        }


def _is_candidate_event(play_type: str) -> bool:
    normalized = (play_type or "").upper().strip()
    return normalized in _CANDIDATE_PLAY_TYPES


def _team_benefited_for_event(
    team_code: str | None,
    home_team_code: str | None,
    away_team_code: str | None,
) -> str | None:
    if not team_code:
        return None
    if team_code == home_team_code:
        return away_team_code
    if team_code == away_team_code:
        return home_team_code
    return None


def _safe_score_diff(home_score: int | None, away_score: int | None) -> int | None:
    if home_score is None or away_score is None:
        return None
    return home_score - away_score
