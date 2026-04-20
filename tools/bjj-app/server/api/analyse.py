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
                last_moments = event.get("moments", [])
            yield f"data: {json.dumps(event)}\n\n".encode("utf-8")

        # Persist after streaming completes. Done inline so the client sees the
        # moments event *before* the connection closes. A failure here would
        # otherwise be silent to the client (already sent "done") — log it so
        # an operator can notice the mismatch when they refresh and see no chips.
        conn = connect(settings.db_path)
        try:
            insert_moments(conn, roll_id=roll_id, moments=last_moments)
        except Exception:
            logger.exception("Failed to persist moments for %s", roll_id)
        finally:
            conn.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
