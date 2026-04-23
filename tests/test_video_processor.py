"""Tests for video processor timing utilities."""
from __future__ import annotations

import pytest

from ingestion.video_processor import game_clock_to_seconds, PERIOD_DURATION


def test_clock_period1_full_time():
    # At start of period 1, clock = 10:00, elapsed = 0
    ts = game_clock_to_seconds(1, "10:00")
    assert ts == 0.0


def test_clock_period1_half_elapsed():
    # 5 minutes elapsed in period 1
    ts = game_clock_to_seconds(1, "05:00")
    assert ts == pytest.approx(300.0, abs=1)


def test_clock_period1_end():
    ts = game_clock_to_seconds(1, "00:00")
    assert ts == pytest.approx(600.0, abs=1)


def test_clock_period2_start():
    ts = game_clock_to_seconds(2, "10:00")
    # Should be at least PERIOD_DURATION seconds in
    assert ts >= PERIOD_DURATION


def test_clock_increases_with_period():
    ts1 = game_clock_to_seconds(1, "05:00")
    ts2 = game_clock_to_seconds(2, "05:00")
    ts3 = game_clock_to_seconds(3, "05:00")
    assert ts1 < ts2 < ts3


def test_bad_clock_returns_zero():
    ts = game_clock_to_seconds(1, "bad:time")
    assert ts == 0.0
