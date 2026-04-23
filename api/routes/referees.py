from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analytics.referee_stats import get_referee_rankings, get_referee_stats
from api.schemas import RefereeOut, RefereeRankingOut, RefereeStatsOut
from db.connection import get_session
from db.models import Referee

router = APIRouter(prefix="/referees", tags=["referees"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[RefereeOut])
async def list_referees(session: SessionDep):
    refs = (await session.execute(select(Referee).order_by(Referee.name))).scalars().all()
    return refs


@router.get("/rankings", response_model=list[RefereeRankingOut])
async def referee_rankings(
    session: SessionDep,
    season: str | None = Query(default=None),
    min_games: int = Query(default=5),
):
    stats = await get_referee_rankings(session, season_code=season, min_games=min_games)
    return [
        RefereeRankingOut(
            rank=i + 1,
            referee_id=s.referee_id,
            referee_name=s.referee_name,
            games_officiated=s.games_officiated,
            accuracy_score=s.accuracy_score,
            error_rate=s.error_rate,
            high_critical_count=s.high_critical_count,
        )
        for i, s in enumerate(stats)
    ]


@router.get("/{referee_id}", response_model=RefereeOut)
async def get_referee(referee_id: int, session: SessionDep):
    ref = await session.get(Referee, referee_id)
    if ref is None:
        raise HTTPException(404, detail="Referee not found")
    return ref


@router.get("/{referee_id}/stats", response_model=RefereeStatsOut)
async def get_referee_stats_endpoint(
    referee_id: int,
    session: SessionDep,
    season: str | None = Query(default=None),
):
    stats = await get_referee_stats(session, referee_id, season_code=season)
    if stats is None:
        raise HTTPException(404, detail="Referee not found")
    return stats.__dict__
