from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── Enumerations ───────────────────────────────────────────────────────────────

class IncidentType(str, enum.Enum):
    WRONG_FOUL_CALL = "wrong_foul_call"
    MISSED_FOUL = "missed_foul"
    WRONG_VIOLATION = "wrong_violation"
    MISSED_VIOLATION = "missed_violation"
    CHARGE_BLOCK_ERROR = "charge_block_error"
    OUT_OF_BOUNDS_ERROR = "out_of_bounds_error"
    GOALTENDING_ERROR = "goaltending_error"
    OTHER = "other"


class IncidentSeverity(str, enum.Enum):
    LOW = "low"        # minor, did not affect outcome
    MEDIUM = "medium"  # affected momentum / possession
    HIGH = "high"      # directly changed score or momentum significantly
    CRITICAL = "critical"  # altered game result


class ClassificationSource(str, enum.Enum):
    AI_VISION = "ai_vision"       # GPT-4o Vision analysis
    AI_CONTEXT = "ai_context"     # Play-by-play context only (no video)
    RULE_BASED = "rule_based"     # Deterministic rule check
    MANUAL = "manual"             # Human review/override


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    OVERTURNED = "overturned"


# ── Core entities ─────────────────────────────────────────────────────────────

class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)  # e.g. "E2024"
    competition_code: Mapped[str] = mapped_column(String(8), nullable=False)   # e.g. "E"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    games: Mapped[list["Game"]] = relationship(back_populates="season")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)  # e.g. "MAD"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(256))
    country: Mapped[Optional[str]] = mapped_column(String(64))

    home_games: Mapped[list["Game"]] = relationship(
        back_populates="home_team", foreign_keys="Game.home_team_id"
    )
    away_games: Mapped[list["Game"]] = relationship(
        back_populates="away_team", foreign_keys="Game.away_team_id"
    )


class Referee(Base):
    __tablename__ = "referees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(64))

    game_assignments: Mapped[list["GameReferee"]] = relationship(back_populates="referee")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="referee")


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    game_code: Mapped[str] = mapped_column(String(32), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    played_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    home_score: Mapped[Optional[int]] = mapped_column(Integer)
    away_score: Mapped[Optional[int]] = mapped_column(Integer)
    venue: Mapped[Optional[str]] = mapped_column(String(256))
    video_url: Mapped[Optional[str]] = mapped_column(String(512))
    video_downloaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pbp_ingested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    analysis_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    season: Mapped["Season"] = relationship(back_populates="games")
    home_team: Mapped["Team"] = relationship(back_populates="home_games", foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(back_populates="away_games", foreign_keys=[away_team_id])
    referee_assignments: Mapped[list["GameReferee"]] = relationship(back_populates="game")
    play_by_play: Mapped[list["PlayByPlayEvent"]] = relationship(back_populates="game")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="game")

    __table_args__ = (
        UniqueConstraint("season_id", "game_code", name="uq_game_season_code"),
        Index("ix_games_season_round", "season_id", "round_number"),
    )


class GameReferee(Base):
    """Association: which referees officiated which game."""

    __tablename__ = "game_referees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    referee_id: Mapped[int] = mapped_column(ForeignKey("referees.id"), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(32))  # "crew_chief", "referee", "umpire"

    game: Mapped["Game"] = relationship(back_populates="referee_assignments")
    referee: Mapped["Referee"] = relationship(back_populates="game_assignments")

    __table_args__ = (UniqueConstraint("game_id", "referee_id"),)


class PlayByPlayEvent(Base):
    """Raw play-by-play event from the Euroleague API."""

    __tablename__ = "play_by_play_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    game_clock: Mapped[str] = mapped_column(String(16), nullable=False)  # "09:34"
    play_type: Mapped[str] = mapped_column(String(64), nullable=False)
    play_info: Mapped[Optional[str]] = mapped_column(Text)
    player_id: Mapped[Optional[str]] = mapped_column(String(32))
    player_name: Mapped[Optional[str]] = mapped_column(String(128))
    team_code: Mapped[Optional[str]] = mapped_column(String(16))
    home_score: Mapped[Optional[int]] = mapped_column(Integer)
    away_score: Mapped[Optional[int]] = mapped_column(Integer)
    coordinates_x: Mapped[Optional[float]] = mapped_column(Float)
    coordinates_y: Mapped[Optional[float]] = mapped_column(Float)
    video_timestamp_seconds: Mapped[Optional[float]] = mapped_column(Float)

    game: Mapped["Game"] = relationship(back_populates="play_by_play")

    __table_args__ = (Index("ix_pbp_game_period_clock", "game_id", "period"),)


# ── Incident (referee error) ───────────────────────────────────────────────────

class Incident(Base):
    """A detected or confirmed referee error."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    referee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("referees.id"))
    pbp_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("play_by_play_events.id"))

    incident_type: Mapped[IncidentType] = mapped_column(Enum(IncidentType), nullable=False)
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity), nullable=False, default=IncidentSeverity.MEDIUM
    )
    classification_source: Mapped[ClassificationSource] = mapped_column(
        Enum(ClassificationSource), nullable=False
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus), nullable=False, default=VerificationStatus.PENDING
    )

    # Game context
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    game_clock: Mapped[str] = mapped_column(String(16), nullable=False)
    score_differential: Mapped[Optional[int]] = mapped_column(Integer)  # home - away at time of incident
    team_benefited: Mapped[Optional[str]] = mapped_column(String(16))   # team code
    team_harmed: Mapped[Optional[str]] = mapped_column(String(16))

    # AI classification output
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float)       # 0.0 – 1.0
    ai_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    ai_model: Mapped[Optional[str]] = mapped_column(String(64))

    # Video evidence
    frame_path: Mapped[Optional[str]] = mapped_column(String(512))
    video_timestamp_seconds: Mapped[Optional[float]] = mapped_column(Float)

    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    game: Mapped["Game"] = relationship(back_populates="incidents")
    referee: Mapped[Optional["Referee"]] = relationship(back_populates="incidents")
    pbp_event: Mapped[Optional["PlayByPlayEvent"]] = relationship()

    __table_args__ = (
        Index("ix_incidents_game", "game_id"),
        Index("ix_incidents_referee", "referee_id"),
        Index("ix_incidents_type_severity", "incident_type", "severity"),
    )
