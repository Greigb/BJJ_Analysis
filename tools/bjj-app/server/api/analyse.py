"""POST /api/rolls/:id/analyse — SSE stream of the pose pre-pass pipeline."""
from __future__ import annotations

import json
import logging
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from server.analysis.pipeline import run_analysis
from server.config import Settings, load_settings
from server.db import connect, get_roll, insert_moments

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api", tags=["analyse"])


@router.post("/rolls/{roll_id}/analyse")
def analyse_roll(
    roll_id: str,
    settings: Settings = Depends(load_settings),
) -> StreamingResponse:
    # Look up the roll before streaming so we can return a clean 404.
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
        )

    video_path = settings.project_root / row["video_path"]
    frames_dir = settings.project_root / "assets" / roll_id / "frames"

    def event_stream() -> Iterator[bytes]:
        last_moments: list[dict] = []
        for event in run_analysis(video_path, frames_dir):
            if event["stage"] == "done":
                # Hold the done event — we'll re-emit it with real moment IDs
                # after persistence.
                last_moments = event.get("moments", [])
                continue
            yield f"data: {json.dumps(event)}\n\n".encode("utf-8")

        # Persist, then emit a done event that carries the real IDs.
        conn = connect(settings.db_path)
        try:
            inserted_rows = insert_moments(
                conn, roll_id=roll_id, moments=last_moments
            )
        except Exception:
            logger.exception("Failed to persist moments for %s", roll_id)
            # Still emit a done event so the client doesn't hang.
            yield (
                b'data: {"stage":"done","total":0,"moments":[]}\n\n'
            )
            return
        finally:
            conn.close()

        done_event = {
            "stage": "done",
            "total": len(inserted_rows),
            "moments": [
                {
                    "id": r["id"],
                    "frame_idx": r["frame_idx"],
                    "timestamp_s": r["timestamp_s"],
                    "pose_delta": r["pose_delta"],
                }
                for r in inserted_rows
            ],
        }
        yield f"data: {json.dumps(done_event)}\n\n".encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
