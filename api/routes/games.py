from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from analytics.game_log import get_game_incident_report
from api.schemas import GameIncidentReportOut, GameOut
from db.connection import get_session
from db.models import Game, Season, Team

router = APIRouter(prefix="/games", tags=["games"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[GameOut])
async def list_games(
    session: SessionDep,
    season: str = Query(default="E2024"),
    round: int | None = Query(default=None),
    team: str | None = Query(default=None),
):
    q = (
        select(Game)
        .join(Season, Game.season_id == Season.id)
        .options(selectinload(Game.home_team), selectinload(Game.away_team))
        .where(Season.code == season)
        .order_by(Game.round_number, Game.played_at)
    )
    if round:
        q = q.where(Game.round_number == round)
    if team:
        team_row = (await session.execute(select(Team).where(Team.code == team))).scalar_one_or_none()
        if team_row:
            q = q.where((Game.home_team_id == team_row.id) | (Game.away_team_id == team_row.id))

    games = (await session.execute(q)).scalars().all()
    return [_to_out(g) for g in games]


@router.get("/{game_code}", response_model=GameOut)
async def get_game(game_code: str, session: SessionDep, season: str = Query(default="E2024")):
    q = (
        select(Game)
        .join(Season, Game.season_id == Season.id)
        .options(selectinload(Game.home_team), selectinload(Game.away_team))
        .where(Game.game_code == game_code, Season.code == season)
    )
    game = (await session.execute(q)).scalar_one_or_none()
    if game is None:
        raise HTTPException(404, detail="Game not found")
    return _to_out(game)


@router.get("/{game_code}/incidents", response_model=GameIncidentReportOut)
async def get_game_incidents(
    game_code: str, session: SessionDep, season: str = Query(default="E2024")
):
    report = await get_game_incident_report(session, game_code, season)
    if report is None:
        raise HTTPException(404, detail="Game not found")
    return report.__dict__


def _to_out(g: Game) -> GameOut:
    from db.models import Incident
    return GameOut(
        id=g.id,
        game_code=g.game_code,
        round_number=g.round_number,
        played_at=g.played_at,
        home_team_code=g.home_team.code if g.home_team else "",
        away_team_code=g.away_team.code if g.away_team else "",
        home_score=g.home_score,
        away_score=g.away_score,
        venue=g.venue,
        analysis_complete=g.analysis_complete,
        incident_count=len(g.incidents) if g.incidents else 0,
    )
