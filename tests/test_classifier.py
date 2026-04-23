"""Tests for context_builder and call_classifier."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.context_builder import GameContext, build_context_for_event
from models.call_classifier import CallClassifier, _parse_result
from db.models import IncidentSeverity, IncidentType


# ── Context builder ───────────────────────────────────────────────────────────

def _make_event(play_type: str, period: int, clock: str, team: str, player: str | None = None) -> dict:
    return {
        "id": 1,
        "play_type": play_type,
        "period": period,
        "game_clock": clock,
        "team_code": team,
        "player_name": player,
        "home_score": 45,
        "away_score": 43,
    }


def test_build_context_basic():
    events = [
        _make_event("2FGM", 2, "09:00", "MAD"),
        _make_event("FV", 2, "08:34", "MAD", "Tavares"),
        _make_event("FT", 2, "08:30", "BAR"),
    ]
    ctx = build_context_for_event(events[1], events, "MAD", "BAR")
    assert ctx.period == 2
    assert ctx.game_clock == "08:34"
    assert ctx.player_name == "Tavares"
    assert ctx.team_code == "MAD"
    assert len(ctx.preceding_events) == 1


def test_build_context_foul_counting():
    events = []
    for i in range(4):
        events.append({
            "id": i,
            "play_type": "FV",
            "period": 1,
            "game_clock": f"0{9-i}:00",
            "team_code": "MAD",
            "player_name": "Smith",
            "home_score": 10,
            "away_score": 8,
        })
    # 5th foul – now MAD is in penalty
    foul = {
        "id": 5,
        "play_type": "FV",
        "period": 1,
        "game_clock": "05:00",
        "team_code": "MAD",
        "player_name": "Smith",
        "home_score": 14,
        "away_score": 12,
    }
    events.append(foul)
    ctx = build_context_for_event(foul, events, "MAD", "BAR")
    assert ctx.home_team_fouls_in_period == 4
    assert ctx.player_fouls_in_game == 4


def test_context_prompt_text_contains_key_info():
    ctx = GameContext(
        period=3,
        game_clock="04:20",
        play_type="FV",
        play_info="Personal foul on Tavares",
        player_name="Tavares",
        team_code="MAD",
        home_score=60,
        away_score=55,
        home_team_code="MAD",
        away_team_code="BAR",
    )
    text = ctx.to_prompt_text()
    assert "Period 3Q" in text
    assert "04:20" in text
    assert "Tavares" in text
    assert "MAD" in text


# ── Call classifier ───────────────────────────────────────────────────────────

def test_parse_result_correct_call():
    data = {
        "is_error": False,
        "incident_type": None,
        "severity": "low",
        "confidence": 0.85,
        "reasoning": "Clear blocking foul – defender had established position.",
        "correct_call_should_be": None,
    }
    result = _parse_result(data, "gpt-4o")
    assert result.is_error is False
    assert result.confidence == 0.85
    assert result.severity == IncidentSeverity.LOW


def test_parse_result_wrong_foul():
    data = {
        "is_error": True,
        "incident_type": "wrong_foul_call",
        "severity": "high",
        "confidence": 0.92,
        "reasoning": "Defender was still moving – should be blocking foul, not charge.",
        "correct_call_should_be": "blocking_foul",
    }
    result = _parse_result(data, "gpt-4o")
    assert result.is_error is True
    assert result.incident_type == IncidentType.WRONG_FOUL_CALL
    assert result.severity == IncidentSeverity.HIGH
    assert result.confidence == 0.92


def test_parse_result_clamps_confidence():
    data = {"is_error": False, "severity": "medium", "confidence": 1.5, "reasoning": "OK"}
    result = _parse_result(data, "gpt-4o")
    assert result.confidence == 1.0


def test_parse_result_invalid_type_falls_back_to_other():
    data = {"is_error": True, "incident_type": "banana", "severity": "low", "confidence": 0.5, "reasoning": ""}
    result = _parse_result(data, "gpt-4o")
    assert result.incident_type == IncidentType.OTHER


@pytest.mark.asyncio
async def test_classifier_calls_openai():
    ctx = GameContext(
        period=1, game_clock="09:00", play_type="FV", play_info="Foul on Hezonja",
        player_name="Hezonja", team_code="BAR",
        home_score=20, away_score=18,
        home_team_code="BAR", away_team_code="MAD",
    )
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "is_error": True,
        "incident_type": "wrong_foul_call",
        "severity": "medium",
        "confidence": 0.78,
        "reasoning": "Player had clear path.",
        "correct_call_should_be": "no_call",
    })
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("models.call_classifier.AsyncOpenAI") as MockOpenAI:
        instance = MockOpenAI.return_value
        instance.chat = MagicMock()
        instance.chat.completions = MagicMock()
        instance.chat.completions.create = AsyncMock(return_value=mock_response)

        classifier = CallClassifier()
        classifier._client = instance
        result = await classifier.classify(ctx)

    assert result.is_error is True
    assert result.confidence == 0.78
