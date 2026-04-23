"""
Game-by-game incident log – returns a structured report for a single game
with all incidents, referee assignments, and summary statistics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Game, GameReferee, Incident, Season


@dataclass
class IncidentSummary:
    incident_id: int
    period: int
    game_clock: str
    incident_type: str
    severity: str
    referee_name: str | None
    team_benefited: str | None
    team_harmed: str | None
    ai_confidence: float | None
    ai_reasoning: str | None
    classification_source: str
    verification_status: str
    video_timestamp_seconds: float | None


@dataclass
class GameIncidentReport:
    game_code: str
    season_code: str
    played_at: datetime | None
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    referees: list[str]
    total_incidents: int
    high_critical_count: int
    incidents: list[IncidentSummary] = field(default_factory=list)


async def get_game_incident_report(
    session: AsyncSession,
    game_code: str,
    season_code: str | None = None,
) -> GameIncidentReport | None:
    """Return the full incident report for a single game."""

    q = (
        select(Game)
        .options(
            selectinload(Game.season),
            selectinload(Game.home_team),
            selectinload(Game.away_team),
            selectinload(Game.referee_assignments).selectinload(GameReferee.referee),
            selectinload(Game.incidents).selectinload(Incident.referee),
        )
        .where(Game.game_code == game_code)
    )
    if season_code:
        q = q.join(Season, Game.season_id == Season.id).where(Season.code == season_code)

    game = (await session.execute(q)).scalar_one_or_none()
    if game is None:
        return None

    referees = [gr.referee.name for gr in game.referee_assignments if gr.referee]
    incidents_sorted = sorted(
        game.incidents,
        key=lambda i: (i.period, i.game_clock),
    )

    summaries = [
        IncidentSummary(
            incident_id=inc.id,
            period=inc.period,
            game_clock=inc.game_clock,
            incident_type=inc.incident_type.value,
            severity=inc.severity.value,
            referee_name=inc.referee.name if inc.referee else None,
            team_benefited=inc.team_benefited,
            team_harmed=inc.team_harmed,
            ai_confidence=inc.ai_confidence,
            ai_reasoning=inc.ai_reasoning,
            classification_source=inc.classification_source.value,
            verification_status=inc.verification_status.value,
            video_timestamp_seconds=inc.video_timestamp_seconds,
        )
        for inc in incidents_sorted
    ]

    from db.models import IncidentSeverity
    high_critical = sum(
        1 for inc in game.incidents
        if inc.severity in (IncidentSeverity.HIGH, IncidentSeverity.CRITICAL)
    )

    return GameIncidentReport(
        game_code=game_code,
        season_code=game.season.code,
        played_at=game.played_at,
        home_team=game.home_team.code,
        away_team=game.away_team.code,
        home_score=game.home_score,
        away_score=game.away_score,
        referees=referees,
        total_incidents=len(summaries),
        high_critical_count=high_critical,
        incidents=summaries,
    )
