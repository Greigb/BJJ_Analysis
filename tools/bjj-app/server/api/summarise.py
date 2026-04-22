"""POST /api/rolls/:id/summarise — one Claude call across all sections + annotations."""
from __future__ import annotations

import math
import time

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.analysis.claude_cli import (
    ClaudeProcessError,
    RateLimitedError,
    run_claude,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.analysis.summarise import (
    SummaryResponseError,
    build_summary_prompt,
    parse_summary_response,
)
from server.config import Settings, load_settings
from server.db import (
    connect,
    get_annotations_by_section,
    get_roll,
    get_sections_by_roll,
    set_summary_state,
)

router = APIRouter(prefix="/api", tags=["summarise"])


class _SummariseIn(BaseModel):
    pass


class _SummariseOut(BaseModel):
    finalised_at: int
    scores: dict


_SUMMARY_LIMITER: SlidingWindowLimiter | None = None


def _get_limiter(settings: Settings) -> SlidingWindowLimiter:
    global _SUMMARY_LIMITER
    if _SUMMARY_LIMITER is None:
        _SUMMARY_LIMITER = SlidingWindowLimiter(
            max_calls=settings.claude_max_calls,
            window_seconds=settings.claude_window_seconds,
        )
    return _SUMMARY_LIMITER


@router.post("/rolls/{roll_id}/summarise", response_model=_SummariseOut)
async def summarise_roll(
    roll_id: str,
    payload: _SummariseIn,
    settings: Settings = Depends(load_settings),
):
    conn = connect(settings.db_path)
    try:
        roll_row = get_roll(conn, roll_id)
        if roll_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        section_rows = [dict(s) for s in get_sections_by_roll(conn, roll_id)]
        annotations_by_section = {
            s["id"]: [dict(a) for a in get_annotations_by_section(conn, s["id"])]
            for s in section_rows
        }
    finally:
        conn.close()

    analysed_sections = [s for s in section_rows if s.get("narrative")]
    if not analysed_sections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Roll has no analysed sections — analyse at least one section before finalising.",
        )

    prompt = build_summary_prompt(
        roll_row=dict(roll_row),
        sections=section_rows,
        annotations_by_section=annotations_by_section,
    )

    limiter = _get_limiter(settings)
    try:
        raw = await run_claude(prompt, settings=settings, limiter=limiter)
    except RateLimitedError as exc:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": f"Claude cooldown — {math.ceil(exc.retry_after_s)}s until next call",
                "retry_after_s": math.ceil(exc.retry_after_s),
            },
            headers={"Retry-After": str(math.ceil(exc.retry_after_s))},
        )
    except ClaudeProcessError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude subprocess failed: {exc}",
        )

    valid_section_ids = {s["id"] for s in section_rows}
    try:
        parsed = parse_summary_response(raw, valid_section_ids)
    except SummaryResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude gave malformed output: {exc}",
        )

    now = int(time.time())
    conn = connect(settings.db_path)
    try:
        set_summary_state(conn, roll_id=roll_id, scores_payload=parsed, finalised_at=now)
    finally:
        conn.close()

    return _SummariseOut(finalised_at=now, scores=parsed)
