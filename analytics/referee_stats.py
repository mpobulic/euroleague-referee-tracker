"""
Referee statistics – per-referee error rates, accuracy trends,
severity breakdown, and head-to-head game comparisons.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Game, GameReferee, Incident, IncidentSeverity, Referee, Season


@dataclass
class RefereeStats:
    referee_id: int
    referee_name: str
    games_officiated: int
    total_incidents: int
    error_rate: float                         # incidents per game
    high_critical_count: int
    severity_breakdown: dict[str, int] = field(default_factory=dict)
    incident_type_breakdown: dict[str, int] = field(default_factory=dict)
    accuracy_score: float = 0.0               # 1.0 - normalised error rate (0–1)
    season_code: str | None = None


async def get_referee_stats(
    session: AsyncSession,
    referee_id: int,
    season_code: str | None = None,
) -> RefereeStats | None:
    """Return stats for a single referee, optionally filtered by season."""

    # Fetch referee
    referee = await session.get(Referee, referee_id)
    if referee is None:
        return None

    # Games officiated
    games_q = select(func.count(GameReferee.id)).where(GameReferee.referee_id == referee_id)
    if season_code:
        games_q = (
            select(func.count(GameReferee.id))
            .join(Game, GameReferee.game_id == Game.id)
            .join(Season, Game.season_id == Season.id)
            .where(GameReferee.referee_id == referee_id, Season.code == season_code)
        )
    games_officiated = (await session.execute(games_q)).scalar_one() or 0

    # Incidents
    inc_q = select(Incident).where(Incident.referee_id == referee_id)
    if season_code:
        inc_q = (
            select(Incident)
            .join(Game, Incident.game_id == Game.id)
            .join(Season, Game.season_id == Season.id)
            .where(Incident.referee_id == referee_id, Season.code == season_code)
        )
    incidents = (await session.execute(inc_q)).scalars().all()

    total = len(incidents)
    severity_breakdown: dict[str, int] = {}
    type_breakdown: dict[str, int] = {}
    high_critical = 0

    for inc in incidents:
        sev = inc.severity.value
        severity_breakdown[sev] = severity_breakdown.get(sev, 0) + 1
        inc_type = inc.incident_type.value
        type_breakdown[inc_type] = type_breakdown.get(inc_type, 0) + 1
        if inc.severity in (IncidentSeverity.HIGH, IncidentSeverity.CRITICAL):
            high_critical += 1

    error_rate = total / games_officiated if games_officiated else 0.0
    # Accuracy score: penalise more for high/critical errors
    weighted_errors = sum(
        n * {"low": 0.25, "medium": 0.5, "high": 1.0, "critical": 2.0}.get(sev, 0.5)
        for sev, n in severity_breakdown.items()
    )
    max_weighted = games_officiated * 2.0 if games_officiated else 1.0
    accuracy_score = max(0.0, 1.0 - (weighted_errors / max_weighted))

    return RefereeStats(
        referee_id=referee_id,
        referee_name=referee.name,
        games_officiated=games_officiated,
        total_incidents=total,
        error_rate=round(error_rate, 3),
        high_critical_count=high_critical,
        severity_breakdown=severity_breakdown,
        incident_type_breakdown=type_breakdown,
        accuracy_score=round(accuracy_score, 3),
        season_code=season_code,
    )


async def get_referee_rankings(
    session: AsyncSession,
    season_code: str | None = None,
    min_games: int = 5,
) -> list[RefereeStats]:
    """
    Return all referees ranked by accuracy_score (best first).
    Only includes referees with >= min_games officiated.
    """
    ref_ids_q = select(Referee.id)
    refs = (await session.execute(ref_ids_q)).scalars().all()

    stats: list[RefereeStats] = []
    for ref_id in refs:
        s = await get_referee_stats(session, ref_id, season_code)
        if s and s.games_officiated >= min_games:
            stats.append(s)

    stats.sort(key=lambda s: s.accuracy_score, reverse=True)
    return stats
