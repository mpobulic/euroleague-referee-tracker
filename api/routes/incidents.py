from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.schemas import IncidentOut, IncidentPatch, OKResponse
from db.connection import get_session
from db.models import Game, Incident, IncidentSeverity, Season, VerificationStatus

router = APIRouter(prefix="/incidents", tags=["incidents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[IncidentOut])
async def list_incidents(
    session: SessionDep,
    season: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    incident_type: str | None = Query(default=None),
    referee_id: int | None = Query(default=None),
    team: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
):
    q = select(Incident).options(selectinload(Incident.referee))

    if season:
        q = q.join(Game, Incident.game_id == Game.id).join(
            Season, Game.season_id == Season.id
        ).where(Season.code == season)
    if severity:
        try:
            q = q.where(Incident.severity == IncidentSeverity(severity))
        except ValueError:
            raise HTTPException(400, detail=f"Invalid severity: {severity}")
    if incident_type:
        q = q.where(Incident.incident_type == incident_type)
    if referee_id:
        q = q.where(Incident.referee_id == referee_id)
    if team:
        q = q.where(
            (Incident.team_benefited == team) | (Incident.team_harmed == team)
        )

    q = q.order_by(Incident.created_at.desc()).limit(limit).offset(offset)
    incidents = (await session.execute(q)).scalars().all()
    return incidents


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: int, session: SessionDep):
    inc = await session.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, detail="Incident not found")
    return inc


@router.patch("/{incident_id}", response_model=IncidentOut)
async def patch_incident(incident_id: int, body: IncidentPatch, session: SessionDep):
    """Allow human reviewers to update verification status, severity, or description."""
    inc = await session.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, detail="Incident not found")

    if body.verification_status is not None:
        try:
            inc.verification_status = VerificationStatus(body.verification_status)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid status: {body.verification_status}")
    if body.severity is not None:
        try:
            inc.severity = IncidentSeverity(body.severity)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid severity: {body.severity}")
    if body.description is not None:
        inc.description = body.description

    return inc


@router.delete("/{incident_id}", response_model=OKResponse)
async def delete_incident(incident_id: int, session: SessionDep):
    inc = await session.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, detail="Incident not found")
    await session.delete(inc)
    return OKResponse()
