"""Video metadata helpers — OpenCV-based."""
from __future__ import annotations

from pathlib import Path

import cv2


def read_duration(path: Path) -> float:
    """Return the duration of a video in seconds.

    Raises:
        FileNotFoundError: if the path does not exist.
        ValueError: if the file exists but can't be opened as a video.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Not a readable video: {path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or frames <= 0:
            raise ValueError(f"Video has no frames / unknown fps: {path}")

        return float(frames / fps)
    finally:
        cap.release()
