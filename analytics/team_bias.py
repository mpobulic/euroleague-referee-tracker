"""
Team bias analytics – analyses whether referee decisions systematically
favour or disadvantage specific teams.

Metrics:
  - home_bias_index: normalised home vs. away incident rate difference
  - per-team error rate (how often errors harmed / benefited a team)
  - foul_call_differential: fouls called FOR vs. AGAINST per team
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Game, Incident, Season, Team


@dataclass
class TeamBiasReport:
    team_code: str
    team_name: str
    games_played: int
    incidents_benefited: int   # errors that helped this team
    incidents_harmed: int      # errors that hurt this team
    net_bias: int              # benefited - harmed  (positive = favoured)
    bias_per_game: float
    home_incidents_benefited: int
    home_incidents_harmed: int
    away_incidents_benefited: int
    away_incidents_harmed: int
    home_bias_index: float     # (home_net - away_net) / games; + = home advantage from refs
    season_code: str | None = None


async def get_team_bias(
    session: AsyncSession,
    team_code: str,
    season_code: str | None = None,
) -> TeamBiasReport | None:
    """Return referee bias metrics for a single team."""

    team_q = select(Team).where(Team.code == team_code)
    team = (await session.execute(team_q)).scalar_one_or_none()
    if team is None:
        return None

    benefited = await _count_incidents(session, team_code, "team_benefited", season_code=season_code)
    harmed = await _count_incidents(session, team_code, "team_harmed", season_code=season_code)
    home_ben = await _count_incidents(
        session, team_code, "team_benefited", home_only=True, team_id=team.id, season_code=season_code
    )
    home_harm = await _count_incidents(
        session, team_code, "team_harmed", home_only=True, team_id=team.id, season_code=season_code
    )
    away_ben = await _count_incidents(
        session, team_code, "team_benefited", home_only=False, team_id=team.id, season_code=season_code
    )
    away_harm = await _count_incidents(
        session, team_code, "team_harmed", home_only=False, team_id=team.id, season_code=season_code
    )

    # Games played
    games_played = await _count_games_played(session, team.id, season_code=season_code)
    if games_played == 0:
        games_played = 1

    net_bias = benefited - harmed
    home_net = home_ben - home_harm
    away_net = away_ben - away_harm
    home_games = max(games_played // 2, 1)
    away_games = max(games_played - home_games, 1)
    home_bias_index = (home_net / home_games) - (away_net / away_games)

    return TeamBiasReport(
        team_code=team_code,
        team_name=team.name,
        games_played=games_played,
        incidents_benefited=benefited,
        incidents_harmed=harmed,
        net_bias=net_bias,
        bias_per_game=round(net_bias / games_played, 3),
        home_incidents_benefited=home_ben,
        home_incidents_harmed=home_harm,
        away_incidents_benefited=away_ben,
        away_incidents_harmed=away_harm,
        home_bias_index=round(home_bias_index, 3),
        season_code=season_code,
    )


async def get_all_team_bias(
    session: AsyncSession,
    season_code: str | None = None,
) -> list[TeamBiasReport]:
    """Return bias reports for all teams, sorted by net_bias descending."""
    team_codes = (await session.execute(select(Team.code))).scalars().all()
    reports: list[TeamBiasReport] = []
    for code in team_codes:
        r = await get_team_bias(session, code, season_code)
        if r and r.games_played > 0:
            reports.append(r)
    reports.sort(key=lambda r: r.net_bias, reverse=True)
    return reports


async def _count_incidents(
    session: AsyncSession,
    team_code: str,
    team_col: str,
    season_code: str | None = None,
    home_only: bool | None = None,
    team_id: int | None = None,
) -> int:
    q = (
        select(func.count(Incident.id))
        .join(Game, Incident.game_id == Game.id)
        .where(getattr(Incident, team_col) == team_code)
    )
    if season_code:
        q = q.join(Season, Game.season_id == Season.id).where(Season.code == season_code)
    if home_only is True and team_id is not None:
        q = q.where(Game.home_team_id == team_id)
    elif home_only is False and team_id is not None:
        q = q.where(Game.away_team_id == team_id)
    return int((await session.execute(q)).scalar_one() or 0)


async def _count_games_played(
    session: AsyncSession,
    team_id: int,
    season_code: str | None = None,
) -> int:
    q = select(func.count(Game.id)).where(
        (Game.home_team_id == team_id) | (Game.away_team_id == team_id)
    )
    if season_code:
        q = q.join(Season, Game.season_id == Season.id).where(Season.code == season_code)
    return int((await session.execute(q)).scalar_one() or 0)
