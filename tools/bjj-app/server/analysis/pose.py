"""MediaPipe BlazePose wrapper + pose-delta scoring.

Landmarks are normalised to [0, 1] in (x, y) and camera-space in z.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import mediapipe as mp  # type: ignore[import-untyped]

Landmark = tuple[float, float, float]
LandmarkSet = list[Landmark]


class PoseDetector:
    """MediaPipe Pose wrapper. Holds the model instance; call close() when done."""

    def __init__(self, model_complexity: int = 1) -> None:
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=True,
            model_complexity=model_complexity,
        )

    def detect(self, image_path: Path) -> LandmarkSet | None:
        """Return 33 landmarks or None if MediaPipe didn't find a pose."""
        if not image_path.exists():
            raise FileNotFoundError(image_path)

        image_bgr = cv2.imread(str(image_path))
        if image_bgr is None:
            raise ValueError(f"Not a readable image: {image_path}")

        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        result = self._pose.process(image_rgb)
        if result.pose_landmarks is None:
            return None
        return [(lm.x, lm.y, lm.z) for lm in result.pose_landmarks.landmark]

    def close(self) -> None:
        self._pose.close()

    def __enter__(self) -> "PoseDetector":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def pose_delta(
    a: LandmarkSet | None,
    b: LandmarkSet | None,
) -> float:
    """Sum of Euclidean distances between matched (x, y, z) landmarks.

    Returns 0.0 if either argument is None (a convention that simplifies the
    caller — a frame with no detected pose contributes no motion signal).
    """
    if a is None or b is None:
        return 0.0
    if len(a) != len(b):
        raise ValueError(f"Landmark count mismatch: {len(a)} vs {len(b)}")

    total = 0.0
    for (ax, ay, az), (bx, by, bz) in zip(a, b):
        dx, dy, dz = ax - bx, ay - by, az - bz
        total += math.sqrt(dx * dx + dy * dy + dz * dz)
    return total
