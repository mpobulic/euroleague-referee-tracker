from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analytics.team_bias import get_all_team_bias, get_team_bias
from api.schemas import TeamBiasOut, TeamOut
from db.connection import get_session
from db.models import Team

router = APIRouter(prefix="/teams", tags=["teams"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[TeamOut])
async def list_teams(session: SessionDep):
    teams = (await session.execute(select(Team).order_by(Team.name))).scalars().all()
    return teams


@router.get("/bias", response_model=list[TeamBiasOut])
async def all_team_bias(
    session: SessionDep,
    season: str | None = Query(default=None),
):
    reports = await get_all_team_bias(session, season_code=season)
    return [r.__dict__ for r in reports]


@router.get("/{team_code}", response_model=TeamOut)
async def get_team(team_code: str, session: SessionDep):
    team = (
        await session.execute(select(Team).where(Team.code == team_code))
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(404, detail="Team not found")
    return team


@router.get("/{team_code}/bias", response_model=TeamBiasOut)
async def get_team_bias_endpoint(
    team_code: str,
    session: SessionDep,
    season: str | None = Query(default=None),
):
    report = await get_team_bias(session, team_code, season_code=season)
    if report is None:
        raise HTTPException(404, detail="Team not found")
    return report.__dict__
