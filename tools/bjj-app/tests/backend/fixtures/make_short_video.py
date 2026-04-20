"""One-shot: generate tests/backend/fixtures/short_video.mp4 via OpenCV.

Run once, commit the output. Regenerate only if the fixture format ever
needs to change.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).parent / "short_video.mp4"
WIDTH, HEIGHT, FPS, SECONDS = 64, 48, 10, 2


def main() -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(OUT), fourcc, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("OpenCV failed to open VideoWriter")

    for i in range(FPS * SECONDS):
        # Slowly shift a grey gradient so frames differ frame-to-frame.
        value = (i * 8) % 256
        frame = np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    if not OUT.exists() or OUT.stat().st_size == 0:
        raise RuntimeError("VideoWriter produced an empty file")

    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
