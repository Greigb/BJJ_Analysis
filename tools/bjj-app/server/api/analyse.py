"""POST /api/rolls/:id/analyse — SSE stream of the section-based pipeline.

NOTE: This endpoint is being rewritten in M9 Task 6 to use run_section_analysis.
The body below is a placeholder stub so the module loads cleanly and tests that
call this endpoint as setup don't break at import time. Task 6 replaces it fully.
"""
from __future__ import annotations

import json
import logging
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from server.analysis.pipeline import run_section_analysis  # noqa: F401 — used by Task 6
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

    def event_stream() -> Iterator[bytes]:
        # Stub: Task 6 replaces this with the section-based pipeline.
        # Emit a minimal done event so callers that drain this endpoint
        # (e.g. test setup helpers) don't hang or error at the SSE level.
        yield b'data: {"stage":"done","total":0,"moments":[]}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
