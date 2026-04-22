"""POST /api/rolls/:id/analyse — SSE stream of the M9b section-narrative pipeline."""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.analysis.pipeline import run_section_analysis
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import Settings, load_settings
from server.db import connect, get_roll

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analyse"])

_DURATION_EPSILON = 0.5

# Module-level singleton for per-section Claude rate limiting.
_SECTION_LIMITER: SlidingWindowLimiter | None = None


def _get_limiter(settings: Settings) -> SlidingWindowLimiter:
    global _SECTION_LIMITER
    if _SECTION_LIMITER is None:
        _SECTION_LIMITER = SlidingWindowLimiter(
            max_calls=settings.claude_max_calls,
            window_seconds=settings.claude_window_seconds,
        )
    return _SECTION_LIMITER


class _SectionIn(BaseModel):
    start_s: float = Field(..., ge=0)
    end_s: float = Field(..., ge=0)
    # Accepted for frontend-transition compatibility; ignored by the pipeline.
    sample_interval_s: float | None = None


class _AnalyseIn(BaseModel):
    sections: list[_SectionIn] = Field(..., min_length=1)


@router.post("/rolls/{roll_id}/analyse")
async def analyse_roll(
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

    video_path = settings.project_root / row["video_path"]
    frames_dir = settings.project_root / "assets" / roll_id / "frames"
    sections_payload = [
        {"start_s": s.start_s, "end_s": s.end_s} for s in payload.sections
    ]
    player_a_name = row["player_a_name"] or "Player A"
    player_b_name = row["player_b_name"] or "Player B"
    limiter = _get_limiter(settings)

    async def event_stream() -> AsyncIterator[bytes]:
        conn2 = connect(settings.db_path)
        try:
            async for event in run_section_analysis(
                conn=conn2,
                roll_id=roll_id,
                video_path=video_path,
                frames_dir=frames_dir,
                sections=sections_payload,
                duration_s=duration_s,
                player_a_name=player_a_name,
                player_b_name=player_b_name,
                settings=settings,
                limiter=limiter,
            ):
                yield f"data: {json.dumps(event)}\n\n".encode("utf-8")
        except Exception:
            logger.exception("Analyse pipeline failed for %s", roll_id)
            yield b'data: {"stage":"done","total":0}\n\n'
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
