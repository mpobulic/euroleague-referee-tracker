"""
Video processor – downloads Euroleague game video and extracts key frames
around foul/violation events for AI analysis.

Pipeline per game:
  1. Download video via yt-dlp (YouTube VOD or direct URL)
  2. Map PBP game clock -> video timestamp (using period offsets)
  3. Extract a short clip (±5 s) around each candidate event via OpenCV
  4. Save representative frames (every 250ms in the clip window)
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import cv2
import structlog

from config import settings

log = structlog.get_logger(__name__)

# Rough period start offsets in seconds (including pre-game, breaks, etc.)
# These are approximate and can be calibrated per broadcast.
PERIOD_OFFSETS_SECONDS = {
    1: 0,
    2: 10 * 60 + 35,   # ~10:35 after period 1 tips off (OT included  break)
    3: 22 * 60,
    4: 33 * 60,
    5: 45 * 60,         # OT1
    6: 52 * 60,         # OT2
}
HALF_TIME_BREAK = 15 * 60   # seconds
PERIOD_DURATION = 10 * 60   # FIBA 10-minute periods

FOUL_PLAY_TYPES = {
    "FV",  # foul personal
    "FT",  # foul technical
    "FO",  # foul offensive
    "F",
    "TFOUL",
    "PFOUL",
    "FOUL",
}
VIOLATION_PLAY_TYPES = {
    "TO",      # turnover (includes travel, double dribble)
    "TREV",    # travel
    "DBLDRIB", # double dribble
    "VIO",
    "VIOLATION",
    "3SEC",
    "5SEC",
    "8SEC",
    "24SEC",
}

CANDIDATE_PLAY_TYPES = FOUL_PLAY_TYPES | VIOLATION_PLAY_TYPES

CLIP_WINDOW_BEFORE = 4.0   # seconds before the event
CLIP_WINDOW_AFTER = 2.0    # seconds after
FRAME_INTERVAL = 0.25      # extract a frame every 250ms


def game_clock_to_seconds(period: int, clock: str) -> float:
    """Convert e.g. period=2, clock='07:34' to absolute video seconds."""
    try:
        minutes, seconds = clock.strip().split(":")
        remaining = int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0.0
    elapsed_in_period = PERIOD_DURATION - remaining
    offset = PERIOD_OFFSETS_SECONDS.get(period, (period - 1) * (PERIOD_DURATION + 120))
    # Add half-time break after period 2
    if period > 2:
        offset += HALF_TIME_BREAK - 120  # already partially included in offsets above
    return offset + elapsed_in_period


class VideoProcessor:
    def __init__(self) -> None:
        self.video_dir = Path(settings.video_storage_path)
        self.frame_dir = Path(settings.frame_storage_path)
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.frame_dir.mkdir(parents=True, exist_ok=True)

    # ── Download ──────────────────────────────────────────────────────────────

    async def download_game_video(self, game_code: str, video_url: str) -> Path | None:
        """Download game VOD using yt-dlp. Returns local path or None on failure."""
        dest = self.video_dir / f"{game_code}.mp4"
        if dest.exists():
            log.info("Video already downloaded", game_code=game_code, path=str(dest))
            return dest

        cmd = [
            "yt-dlp",
            "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]",
            "--merge-output-format", "mp4",
            "--output", str(dest),
            "--no-playlist",
            "--quiet",
        ]
        if settings.ydl_cookies_file:
            cmd += ["--cookies", settings.ydl_cookies_file]
        cmd.append(video_url)

        log.info("Downloading video", game_code=game_code, url=video_url)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.error("yt-dlp failed", game_code=game_code, stderr=stderr.decode()[:500])
            return None
        return dest

    # ── Frame extraction ──────────────────────────────────────────────────────

    def extract_frames_for_event(
        self,
        video_path: Path,
        game_code: str,
        event_id: int,
        timestamp_seconds: float,
    ) -> list[Path]:
        """
        Extract frames around an event timestamp.
        Returns list of saved frame paths.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            log.error("Cannot open video", path=str(video_path))
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        start_s = max(0.0, timestamp_seconds - CLIP_WINDOW_BEFORE)
        end_s = timestamp_seconds + CLIP_WINDOW_AFTER

        event_frame_dir = self.frame_dir / game_code / str(event_id)
        event_frame_dir.mkdir(parents=True, exist_ok=True)

        saved: list[Path] = []
        t = start_s
        while t <= end_s:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                break
            frame_path = event_frame_dir / f"t{t:.3f}.jpg"
            cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            saved.append(frame_path)
            t += FRAME_INTERVAL

        cap.release()
        log.info(
            "Frames extracted",
            game_code=game_code,
            event_id=event_id,
            count=len(saved),
            timestamp=timestamp_seconds,
        )
        return saved

    def extract_key_frame(
        self, video_path: Path, game_code: str, event_id: int, timestamp_seconds: float
    ) -> Path | None:
        """Extract the single frame closest to the event moment (for quick AI preview)."""
        frames = self.extract_frames_for_event(
            video_path, game_code, event_id, timestamp_seconds
        )
        if not frames:
            return None
        # Return frame closest to the event (CLIP_WINDOW_BEFORE seconds in)
        mid = len(frames) // 2
        return frames[mid]

    # ── Convenience: process all candidate events for a game ─────────────────

    async def process_game_events(
        self,
        game_code: str,
        video_url: str,
        pbp_events: list[dict],  # list of PlayByPlayEvent dicts
    ) -> dict[int, list[Path]]:
        """
        Download video and extract frames for all foul/violation events.
        Returns mapping of event_id -> list of frame paths.
        """
        video_path = await self.download_game_video(game_code, video_url)
        if video_path is None:
            return {}

        result: dict[int, list[Path]] = {}
        for ev in pbp_events:
            play_type = (ev.get("play_type") or "").upper()
            if not any(pt in play_type for pt in CANDIDATE_PLAY_TYPES):
                continue

            ts = game_clock_to_seconds(ev.get("period", 1), ev.get("game_clock", "10:00"))
            event_id = ev.get("id") or ev.get("event_id")
            if event_id is None:
                continue

            frames = await asyncio.get_event_loop().run_in_executor(
                None,
                self.extract_frames_for_event,
                video_path,
                game_code,
                event_id,
                ts,
            )
            if frames:
                result[event_id] = frames

        return result
