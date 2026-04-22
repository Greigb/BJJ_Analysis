"""POST /api/rolls/:id/summarise — one Claude call across all moments + annotations."""
from __future__ import annotations

import math
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    compute_distribution,
    parse_summary_response,
)
from server.config import Settings, load_settings
from server.db import (
    connect,
    get_analyses,
    get_moments,
    get_roll,
    set_summary_state,
)

router = APIRouter(prefix="/api", tags=["summarise"])


class _SummariseIn(BaseModel):
    pass


class _SummariseOut(BaseModel):
    finalised_at: int
    scores: dict
    distribution: dict


# Module-level singleton for summary rate limiting.
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
    request: Request,
    settings: Settings = Depends(load_settings),
):
    conn = connect(settings.db_path)
    try:
        roll_row = get_roll(conn, roll_id)
        if roll_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        moment_rows = [dict(m) for m in get_moments(conn, roll_id)]
        analyses_by_moment = {
            m["id"]: [dict(a) for a in get_analyses(conn, m["id"])] for m in moment_rows
        }
        # Annotations are now section-scoped (M9b); moments carry no annotations.
        annotations_by_moment = {m["id"]: [] for m in moment_rows}
    finally:
        conn.close()

    any_analyses = any(analyses_by_moment[m["id"]] for m in moment_rows)
    if not any_analyses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Roll has no analyses — analyse at least one moment before finalising.",
        )

    prompt = build_summary_prompt(
        roll_row=dict(roll_row),
        moment_rows=moment_rows,
        analyses_by_moment=analyses_by_moment,
        annotations_by_moment=annotations_by_moment,
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

    valid_moment_ids = {m["id"] for m in moment_rows}
    try:
        parsed = parse_summary_response(raw, valid_moment_ids)
    except SummaryResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude gave malformed output: {exc}",
        )

    now = int(time.time())
    conn = connect(settings.db_path)
    try:
        set_summary_state(
            conn, roll_id=roll_id, scores_payload=parsed, finalised_at=now,
        )
    finally:
        conn.close()

    taxonomy = getattr(request.app.state, "taxonomy", None) or {"categories": [], "positions": []}
    position_to_category = {p["id"]: p["category"] for p in taxonomy.get("positions", [])}
    flat_analyses: list[dict] = []
    for m in moment_rows:
        for a in analyses_by_moment[m["id"]]:
            flat_analyses.append({
                "position_id": a["position_id"],
                "player": a["player"],
                "timestamp_s": m["timestamp_s"],
                "category": position_to_category.get(a["position_id"], "scramble"),
            })
    distribution = compute_distribution(flat_analyses, taxonomy.get("categories", []))

    return _SummariseOut(
        finalised_at=now,
        scores=parsed,
        distribution=distribution,
    )
