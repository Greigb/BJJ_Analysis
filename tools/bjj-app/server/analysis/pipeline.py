"""Pose pre-pass pipeline: extract frames → detect pose → flag moments.

Sync generator — yields `{stage, pct, ...}` events, terminating with
`{stage: "done", moments: [...]}`. Callers feed this into an SSE
StreamingResponse or drain it in tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from server.analysis.frames import extract_frames
from server.analysis.pose import PoseDetector, pose_delta


_TOP_PERCENT = 0.20
_MIN_MOMENTS = 3
_MAX_MOMENTS = 30


def run_analysis(
    video_path: Path,
    frames_dir: Path,
    fps: float = 1.0,
) -> Iterator[dict]:
    """Run the pose pre-pass, yielding progress events."""

    # ---------- Stage 1: frame extraction ----------
    yield {"stage": "frames", "pct": 0}
    frame_paths = extract_frames(video_path, frames_dir, fps=fps)
    total = len(frame_paths)
    yield {"stage": "frames", "pct": 100, "total": total}

    # ---------- Stage 2: pose detection ----------
    yield {"stage": "pose", "pct": 0, "total": total}
    landmarks_per_frame: list[list[tuple[float, float, float]] | None] = []
    with PoseDetector() as detector:
        for i, fp in enumerate(frame_paths):
            landmarks_per_frame.append(detector.detect(fp))
            pct = int(round(100 * (i + 1) / max(total, 1)))
            # Emit progress roughly every ~5%.
            if pct in (100,) or (i % max(total // 20, 1) == 0):
                yield {"stage": "pose", "pct": pct, "total": total}

    # ---------- Stage 3: delta + flagging ----------
    deltas = [0.0]  # frame 0 has no predecessor
    for i in range(1, total):
        deltas.append(pose_delta(landmarks_per_frame[i - 1], landmarks_per_frame[i]))

    moments = _flag_moments(deltas, fps)

    yield {"stage": "done", "moments": moments, "total": total}


def _flag_moments(deltas: list[float], fps: float) -> list[dict]:
    """Flag the top _TOP_PERCENT highest-delta frames as moments.

    Bounded by [_MIN_MOMENTS, _MAX_MOMENTS], clamped to len(deltas).
    """
    n = len(deltas)
    if n == 0:
        return []

    target = max(_MIN_MOMENTS, int(round(n * _TOP_PERCENT)))
    target = min(target, _MAX_MOMENTS, n)

    # Select indices of top-target deltas, then sort by timestamp for output stability.
    indexed = sorted(enumerate(deltas), key=lambda x: x[1], reverse=True)[:target]
    indexed.sort(key=lambda x: x[0])  # restore chronological order

    moments: list[dict] = []
    for frame_idx, delta in indexed:
        moments.append(
            {
                "frame_idx": frame_idx,
                "timestamp_s": round(frame_idx / fps, 3),
                "pose_delta": round(delta, 4),
            }
        )
    return moments
