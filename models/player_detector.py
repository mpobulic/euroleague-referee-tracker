"""
YOLOv8-based player and ball detector.

Provides:
  - detect_players(frame) -> list of bounding boxes with confidence
  - detect_ball(frame) -> BoundingBox | None
  - estimate_contact(frame, boxes) -> bool  (rough contact heuristic)
  - describe_frame(frame) -> str  (natural-language description for LLM)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import structlog

log = structlog.get_logger(__name__)

# Lazy-load YOLO to avoid import overhead when video processing is disabled
_yolo_model: Any = None
_YOLO_MODEL_NAME = "yolov8n.pt"  # nano for speed; upgrade to yolov8m.pt for accuracy

COCO_PERSON_CLASS = 0       # COCO class id for "person"
COCO_SPORTS_BALL_CLASS = 32 # COCO class id for "sports ball"

CONTACT_OVERLAP_THRESHOLD = 0.15  # IoU threshold for "players are in contact"


@dataclass
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    label: str

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height


def _get_model() -> Any:
    global _yolo_model
    if _yolo_model is None:
        try:
            from ultralytics import YOLO
            _yolo_model = YOLO(_YOLO_MODEL_NAME)
            log.info("YOLO model loaded", model=_YOLO_MODEL_NAME)
        except Exception as exc:
            log.warning("YOLO unavailable – vision features disabled", error=str(exc))
    return _yolo_model


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    """Intersection over Union of two bounding boxes."""
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    intersection = (ix2 - ix1) * (iy2 - iy1)
    union = a.area + b.area - intersection
    return intersection / union if union > 0 else 0.0


def detect_players(frame: np.ndarray, conf_threshold: float = 0.4) -> list[BoundingBox]:
    """Detect all players (persons) in a frame."""
    model = _get_model()
    if model is None:
        return []
    results = model(frame, classes=[COCO_PERSON_CLASS], conf=conf_threshold, verbose=False)
    boxes: list[BoundingBox] = []
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            boxes.append(BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=float(box.conf[0]), label="player"))
    return boxes


def detect_ball(frame: np.ndarray, conf_threshold: float = 0.3) -> BoundingBox | None:
    """Detect the basketball in a frame."""
    model = _get_model()
    if model is None:
        return None
    results = model(frame, classes=[COCO_SPORTS_BALL_CLASS], conf=conf_threshold, verbose=False)
    best: BoundingBox | None = None
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            b = BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=float(box.conf[0]), label="ball")
            if best is None or b.confidence > best.confidence:
                best = b
    return best


def estimate_contact(player_boxes: list[BoundingBox]) -> bool:
    """
    Rough heuristic: two players are in contact if their bounding boxes
    significantly overlap (IoU > threshold).
    """
    for i, a in enumerate(player_boxes):
        for b in player_boxes[i + 1:]:
            if _iou(a, b) >= CONTACT_OVERLAP_THRESHOLD:
                return True
    return False


def describe_frame(
    frame: np.ndarray,
    player_boxes: list[BoundingBox],
    ball_box: BoundingBox | None,
) -> str:
    """
    Produce a textual description of the frame for use in the LLM prompt.
    Useful when passing frame description alongside the image.
    """
    h, w = frame.shape[:2]
    lines: list[str] = [f"Frame dimensions: {w}x{h}px."]

    lines.append(f"Players detected: {len(player_boxes)}.")
    if player_boxes:
        zones = []
        for box in player_boxes:
            rel_x = box.cx / w
            rel_y = box.cy / h
            zone_x = "left" if rel_x < 0.33 else "center" if rel_x < 0.66 else "right"
            zone_y = "paint" if rel_y > 0.7 else "mid-range" if rel_y > 0.4 else "perimeter"
            zones.append(f"{zone_y}-{zone_x}")
        lines.append(f"Player positions: {', '.join(zones)}.")

    if ball_box:
        rel_x = ball_box.cx / w
        rel_y = ball_box.cy / h
        zone_x = "left" if rel_x < 0.33 else "center" if rel_x < 0.66 else "right"
        zone_y = "paint" if rel_y > 0.7 else "mid-range" if rel_y > 0.4 else "perimeter"
        lines.append(f"Ball detected at: {zone_y}-{zone_x} (confidence {ball_box.confidence:.2f}).")
    else:
        lines.append("Ball not detected in frame.")

    if estimate_contact(player_boxes):
        lines.append("Physical contact detected between players.")

    return " ".join(lines)
