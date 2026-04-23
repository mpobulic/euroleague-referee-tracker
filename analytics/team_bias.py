"""
Team bias analytics – analyses whether referee decisions systematically
favour or disadvantage specific teams.

Metrics:
  - home_bias_index: normalised home vs. away incident rate difference
  - per-team error rate (how often errors harmed / benefited a team)
  - foul_call_differential: fouls called FOR vs. AGAINST per team
"""
from __future__ import annotations

from dataclasses import dataclass, field

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

    # Build base incident query
    def _inc_q(team_col: str, home_only: bool | None = None) -> select:
        q = (
            select(Incident)
            .join(Game, Incident.game_id == Game.id)
            .where(getattr(Incident, team_col) == team_code)
        )
        if season_code:
            q = q.join(Season, Game.season_id == Season.id).where(Season.code == season_code)
        if home_only is True:
            q = q.where(Game.home_team_id == team.id)
        elif home_only is False:
            q = q.where(Game.away_team_id == team.id)
        return q

    def _count(rows: list) -> int:
        return len(rows)

    benefited = _count((await session.execute(_inc_q("team_benefited"))).scalars().all())
    harmed = _count((await session.execute(_inc_q("team_harmed"))).scalars().all())
    home_ben = _count((await session.execute(_inc_q("team_benefited", home_only=True))).scalars().all())
    home_harm = _count((await session.execute(_inc_q("team_harmed", home_only=True))).scalars().all())
    away_ben = _count((await session.execute(_inc_q("team_benefited", home_only=False))).scalars().all())
    away_harm = _count((await session.execute(_inc_q("team_harmed", home_only=False))).scalars().all())

    # Games played
    games_q = select(func.count(Game.id)).where(
        (Game.home_team_id == team.id) | (Game.away_team_id == team.id)
    )
    if season_code:
        games_q = games_q.join(Season, Game.season_id == Season.id).where(Season.code == season_code)
    games_played = (await session.execute(games_q)).scalar_one() or 1

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
