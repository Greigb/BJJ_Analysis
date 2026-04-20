"""OpenCV frame extraction for uploaded videos."""
from __future__ import annotations

from pathlib import Path

import cv2


def extract_frames(
    video_path: Path,
    out_dir: Path,
    fps: float = 1.0,
) -> list[Path]:
    """Extract one frame per (1/fps) seconds to out_dir as frame_NNNNNN.jpg.

    Returns the list of created frame paths in timestamp order.

    Raises:
        FileNotFoundError: if video_path does not exist.
        ValueError: if the video can't be opened or has no frames.
    """
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    if fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")

    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Not a readable video: {video_path}")

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if video_fps <= 0 or total_frames <= 0:
            raise ValueError(f"Video has no frames / unknown fps: {video_path}")

        step = max(int(round(video_fps / fps)), 1)
        paths: list[Path] = []
        frame_idx = 0
        out_idx = 0

        while frame_idx < total_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, image = cap.read()
            if not ok:
                break
            path = out_dir / f"frame_{out_idx:06d}.jpg"
            cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 85])
            paths.append(path)
            out_idx += 1
            frame_idx += step

        return paths
    finally:
        cap.release()
