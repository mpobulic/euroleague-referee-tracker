"""Pydantic schemas for API request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Shared ────────────────────────────────────────────────────────────────────

class OKResponse(BaseModel):
    ok: bool = True


# ── Incident ──────────────────────────────────────────────────────────────────

class IncidentOut(BaseModel):
    id: int
    game_id: int
    referee_id: int | None
    incident_type: str
    severity: str
    classification_source: str
    verification_status: str
    period: int
    game_clock: str
    score_differential: int | None
    team_benefited: str | None
    team_harmed: str | None
    ai_confidence: float | None
    ai_reasoning: str | None
    ai_model: str | None
    frame_path: str | None
    video_timestamp_seconds: float | None
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class IncidentPatch(BaseModel):
    verification_status: str | None = None
    severity: str | None = None
    description: str | None = None


# ── Game ──────────────────────────────────────────────────────────────────────

class GameOut(BaseModel):
    id: int
    game_code: str
    round_number: int
    played_at: datetime | None
    home_team_code: str
    away_team_code: str
    home_score: int | None
    away_score: int | None
    venue: str | None
    analysis_complete: bool
    incident_count: int = 0

    class Config:
        from_attributes = True


class GameIncidentReportOut(BaseModel):
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
    incidents: list[dict]


# ── Referee ───────────────────────────────────────────────────────────────────

class RefereeOut(BaseModel):
    id: int
    external_id: str | None
    name: str
    country: str | None

    class Config:
        from_attributes = True


class RefereeStatsOut(BaseModel):
    referee_id: int
    referee_name: str
    games_officiated: int
    total_incidents: int
    error_rate: float
    high_critical_count: int
    severity_breakdown: dict[str, int]
    incident_type_breakdown: dict[str, int]
    accuracy_score: float
    season_code: str | None


class RefereeRankingOut(BaseModel):
    rank: int
    referee_id: int
    referee_name: str
    games_officiated: int
    accuracy_score: float
    error_rate: float
    high_critical_count: int


# ── Team ──────────────────────────────────────────────────────────────────────

class TeamOut(BaseModel):
    id: int
    code: str
    name: str
    country: str | None

    class Config:
        from_attributes = True


class TeamBiasOut(BaseModel):
    team_code: str
    team_name: str
    games_played: int
    incidents_benefited: int
    incidents_harmed: int
    net_bias: int
    bias_per_game: float
    home_incidents_benefited: int
    home_incidents_harmed: int
    away_incidents_benefited: int
    away_incidents_harmed: int
    home_bias_index: float
    season_code: str | None
