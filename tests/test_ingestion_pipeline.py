from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from db.models import IncidentSeverity, IncidentType
from ingestion.pipeline import (
    IngestionPipeline,
    _is_candidate_event,
    _safe_score_diff,
    _team_benefited_for_event,
)
from models.call_classifier import ClassificationResult


def test_is_candidate_event_requires_exact_match():
    assert _is_candidate_event("FV") is True
    assert _is_candidate_event("TO") is True
    assert _is_candidate_event("SHOT_BLOCKED") is False
    assert _is_candidate_event("TURNOVER_TOUCH") is False


def test_team_benefited_infers_opponent():
    assert _team_benefited_for_event("MAD", "MAD", "BAR") == "BAR"
    assert _team_benefited_for_event("BAR", "MAD", "BAR") == "MAD"
    assert _team_benefited_for_event("UNK", "MAD", "BAR") is None


def test_safe_score_diff_handles_missing_values():
    assert _safe_score_diff(73, 70) == 3
    assert _safe_score_diff(None, 70) is None
    assert _safe_score_diff(73, None) is None


@pytest.mark.asyncio
async def test_analyze_game_events_creates_incident_for_error_candidates():
    session = AsyncMock()
    pipeline = IngestionPipeline(session)
    pipeline.classifier.classify = AsyncMock(
        return_value=ClassificationResult(
            is_error=True,
            incident_type=IncidentType.WRONG_FOUL_CALL,
            severity=IncidentSeverity.HIGH,
            confidence=0.9,
            reasoning="Incorrect foul call.",
            correct_call_should_be="no_call",
            model_used="test-model",
        )
    )

    event_candidate = SimpleNamespace(
        id=10,
        period=1,
        game_clock="08:10",
        play_type="FV",
        play_info="Foul on player",
        player_name="Player A",
        team_code="MAD",
        home_score=20,
        away_score=18,
        coordinates_x=None,
        coordinates_y=None,
        video_timestamp_seconds=None,
    )
    event_non_candidate = SimpleNamespace(
        id=11,
        period=1,
        game_clock="07:50",
        play_type="2FGM",
        play_info="Shot made",
        player_name="Player B",
        team_code="BAR",
        home_score=22,
        away_score=18,
        coordinates_x=None,
        coordinates_y=None,
        video_timestamp_seconds=None,
    )

    class SelectResult:
        def scalars(self):
            class ScalarResult:
                @staticmethod
                def all():
                    return [event_candidate, event_non_candidate]

            return ScalarResult()

    session.execute = AsyncMock(side_effect=[SelectResult(), AsyncMock()])

    game = SimpleNamespace(
        id=5,
        game_code="TEST001",
        home_team=SimpleNamespace(code="MAD"),
        away_team=SimpleNamespace(code="BAR"),
    )

    await pipeline._analyze_game_events(game)

    assert pipeline.classifier.classify.await_count == 1
    assert session.add.call_count == 1
    added_incident = session.add.call_args[0][0]
    assert added_incident.game_id == 5
    assert added_incident.pbp_event_id == 10
    assert added_incident.team_benefited == "BAR"
    assert added_incident.team_harmed == "MAD"
    assert added_incident.score_differential == 2
    assert added_incident.ai_model == "test-model"
    assert session.flush.await_count == 1
