"""OpenCV frame extraction for uploaded videos.

After M9 this module exposes only `extract_frames_at_timestamps` — the
old whole-video fps-sampling `extract_frames` is gone since the pose
pre-pass was retired.
"""
from __future__ import annotations

from pathlib import Path

import cv2


def extract_frames_at_timestamps(
    video_path: Path,
    timestamps: list[float],
    out_dir: Path,
    start_index: int = 0,
) -> list[Path]:
    """Write one JPEG frame per requested timestamp (seconds) to out_dir.

    Files are named `frame_NNNNNN.jpg` with NNNNNN = start_index,
    start_index+1, ... in request order. `timestamps` is consumed in order;
    the caller is responsible for sorting or deduping if that matters.

    Raises:
        FileNotFoundError: if video_path does not exist.
        ValueError: if the video can't be opened.
    """
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    if not timestamps:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Not a readable video: {video_path}")

        paths: list[Path] = []
        for i, ts in enumerate(timestamps):
            # POS_MSEC is more reliable than POS_FRAMES for fractional seconds
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
            ok, image = cap.read()
            if not ok:
                raise ValueError(
                    f"Could not read frame at timestamp {ts}s from {video_path}"
                )
            path = out_dir / f"frame_{start_index + i:06d}.jpg"
            cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 85])
            paths.append(path)

        return paths
    finally:
        cap.release()
