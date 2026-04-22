"""POST /api/rolls/:id/analyse — SSE stream of the M9 section-based pipeline."""
from __future__ import annotations

import json
import logging
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.analysis.pipeline import run_section_analysis
from server.config import Settings, load_settings
from server.db import connect, get_roll

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analyse"])

_ALLOWED_INTERVALS = {0.5, 1.0, 2.0}
# Small slop to absorb fps/duration rounding in uploaded videos.
_DURATION_EPSILON = 0.5


class _SectionIn(BaseModel):
    start_s: float = Field(..., ge=0)
    end_s: float = Field(..., ge=0)
    sample_interval_s: float


class _AnalyseIn(BaseModel):
    sections: list[_SectionIn] = Field(..., min_length=1)


@router.post("/rolls/{roll_id}/analyse")
def analyse_roll(
    roll_id: str,
    payload: _AnalyseIn,
    settings: Settings = Depends(load_settings),
) -> StreamingResponse:
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
        )

    duration_s = float(row["duration_s"] or 0.0)

    # Validate each section.
    for idx, s in enumerate(payload.sections):
        if s.end_s <= s.start_s:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Section {idx}: end_s must be > start_s",
            )
        if s.end_s > duration_s + _DURATION_EPSILON:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Section {idx}: end_s ({s.end_s}) exceeds roll "
                    f"duration ({duration_s})"
                ),
            )
        if s.sample_interval_s not in _ALLOWED_INTERVALS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Section {idx}: sample_interval_s must be one of "
                    f"{sorted(_ALLOWED_INTERVALS)}"
                ),
            )

    video_path = settings.project_root / row["video_path"]
    frames_dir = settings.project_root / "assets" / roll_id / "frames"
    sections_payload = [s.model_dump() for s in payload.sections]

    def event_stream() -> Iterator[bytes]:
        conn2 = connect(settings.db_path)
        try:
            for event in run_section_analysis(
                conn=conn2,
                roll_id=roll_id,
                video_path=video_path,
                frames_dir=frames_dir,
                sections=sections_payload,
                duration_s=duration_s,
            ):
                yield f"data: {json.dumps(event)}\n\n".encode("utf-8")
        except Exception:
            logger.exception("Analyse pipeline failed for %s", roll_id)
            yield b'data: {"stage":"done","total":0,"moments":[]}\n\n'
        finally:
            conn2.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
