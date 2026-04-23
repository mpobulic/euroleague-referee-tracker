"""
AI Call Classifier – uses GPT-4o (with optional Vision) to assess
whether a referee call was correct, missed, or incorrectly made.

Two operating modes:
  1. Vision mode  – sends a key frame + game context to GPT-4o Vision
  2. Context only – sends game context text only (no video/image)

Output is a ClassificationResult with:
  - is_error: bool
  - incident_type: IncidentType | None
  - severity: IncidentSeverity
  - confidence: float  (0.0–1.0)
  - reasoning: str
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from openai import AsyncOpenAI

from config import settings
from db.models import IncidentSeverity, IncidentType
from models.context_builder import GameContext

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """
You are an expert basketball referee analyst with deep knowledge of FIBA basketball rules
as used in EuroLeague competition. Your task is to determine whether a referee's call
(or non-call) was correct based on the provided game context and, when available, video frames.

FIBA rules to apply:
- Personal foul: illegal contact that disadvantages an opponent.
- Blocking foul: the defender does not have a legal guarding position (both feet planted, facing opponent).
- Charging foul: the defender has established legal position BEFORE the offensive player begins their upward shooting motion or changes direction.
- Travel: a player moves one or both feet illegally; 2 steps allowed after gathering.
- Double dribble: re-dribbling after a dribble ends.
- Goaltending/interference: touching ball on its downward arc above basket cylinder.
- Bonus/penalty: 5th team foul in a period triggers free throws.

Respond in JSON with this exact schema:
{
  "is_error": true|false,
  "incident_type": "<IncidentType or null>",
  "severity": "low|medium|high|critical",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<concise explanation, max 300 chars>",
  "correct_call_should_be": "<what the call should have been, or null>"
}

IncidentType values: wrong_foul_call, missed_foul, wrong_violation, missed_violation,
charge_block_error, out_of_bounds_error, goaltending_error, other.

If not enough information is available to make a determination, return is_error=false
with confidence < 0.4.
""".strip()


@dataclass
class ClassificationResult:
    is_error: bool
    incident_type: IncidentType | None
    severity: IncidentSeverity
    confidence: float
    reasoning: str
    correct_call_should_be: str | None
    model_used: str


class CallClassifier:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    async def classify(
        self,
        context: GameContext,
        frame_path: Path | None = None,
    ) -> ClassificationResult:
        """
        Classify a referee call.

        Args:
            context: Structured game context.
            frame_path: Optional path to a key video frame (JPEG/PNG).
        """
        if frame_path and frame_path.exists() and settings.openai_api_key:
            return await self._classify_with_vision(context, frame_path)
        return await self._classify_context_only(context)

    # ── Vision mode ───────────────────────────────────────────────────────────

    async def _classify_with_vision(
        self, context: GameContext, frame_path: Path
    ) -> ClassificationResult:
        image_b64 = _encode_image(frame_path)
        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": context.to_prompt_text()},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                            "detail": settings.openai_vision_detail,
                        },
                    },
                ],
            },
        ]
        return await self._call_model(messages, source="vision")

    # ── Context-only mode ─────────────────────────────────────────────────────

    async def _classify_context_only(self, context: GameContext) -> ClassificationResult:
        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": context.to_prompt_text()},
        ]
        return await self._call_model(messages, source="context_only")

    # ── LLM call ──────────────────────────────────────────────────────────────

    async def _call_model(
        self, messages: list[dict], source: str
    ) -> ClassificationResult:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=512,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
        except Exception as exc:
            log.error("LLM classification failed", error=str(exc), source=source)
            return ClassificationResult(
                is_error=False,
                incident_type=None,
                severity=IncidentSeverity.LOW,
                confidence=0.0,
                reasoning=f"Classification failed: {exc}",
                correct_call_should_be=None,
                model_used=self._model,
            )

        return _parse_result(data, self._model)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _encode_image(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _parse_result(data: dict, model: str) -> ClassificationResult:
    incident_type_raw = data.get("incident_type")
    try:
        incident_type = IncidentType(incident_type_raw) if incident_type_raw else None
    except ValueError:
        incident_type = IncidentType.OTHER

    severity_raw = data.get("severity", "medium")
    try:
        severity = IncidentSeverity(severity_raw)
    except ValueError:
        severity = IncidentSeverity.MEDIUM

    confidence = float(data.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    return ClassificationResult(
        is_error=bool(data.get("is_error", False)),
        incident_type=incident_type,
        severity=severity,
        confidence=confidence,
        reasoning=str(data.get("reasoning", ""))[:500],
        correct_call_should_be=data.get("correct_call_should_be"),
        model_used=model,
    )
