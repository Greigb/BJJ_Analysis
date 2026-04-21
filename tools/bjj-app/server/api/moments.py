"""POST /api/rolls/:id/moments/:frame_idx/analyse — SSE stream of Claude analysis."""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from server.analysis.claude_cli import (
    ClaudeProcessError,
    ClaudeResponseError,
    RateLimitedError,
    analyse_frame,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import Settings, load_settings
from server.db import connect, get_moments, get_roll, insert_analyses

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["moments"])


# Module-level singleton — one limiter per process.
_LIMITER: SlidingWindowLimiter | None = None


def _get_limiter(settings: Settings) -> SlidingWindowLimiter:
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = SlidingWindowLimiter(
            max_calls=settings.claude_max_calls,
            window_seconds=settings.claude_window_seconds,
        )
    return _LIMITER


@router.post("/rolls/{roll_id}/moments/{frame_idx}/analyse")
async def analyse_moment(
    roll_id: str,
    frame_idx: int,
    settings: Settings = Depends(load_settings),
):
    # --- Validate roll + moment exist (before touching Claude) ---
    conn = connect(settings.db_path)
    try:
        roll_row = get_roll(conn, roll_id)
        if roll_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        moment = next(
            (m for m in get_moments(conn, roll_id) if m["frame_idx"] == frame_idx),
            None,
        )
    finally:
        conn.close()

    if moment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Moment not found"
        )

    frame_path = (
        settings.project_root / "assets" / roll_id / "frames" /
        f"frame_{frame_idx:06d}.jpg"
    )
    if not frame_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Frame not extracted: {frame_path.name}",
        )

    limiter = _get_limiter(settings)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_event(evt: dict) -> None:
        await queue.put(evt)

    async def driver() -> None:
        cache_conn = connect(settings.db_path)
        try:
            result = await analyse_frame(
                frame_path=frame_path,
                timestamp_s=moment["timestamp_s"],
                stream_callback=on_event,
                settings=settings,
                limiter=limiter,
                cache_conn=cache_conn,
            )
            # Persist analyses (per-player rows; description+coach_tip on greig only).
            insert_analyses(
                cache_conn,
                moment_id=moment["id"],
                players=[
                    {
                        "player": "greig",
                        "position_id": result["greig"]["position"],
                        "confidence": result["greig"].get("confidence"),
                        "description": result.get("description"),
                        "coach_tip": result.get("coach_tip"),
                    },
                    {
                        "player": "anthony",
                        "position_id": result["anthony"]["position"],
                        "confidence": result["anthony"].get("confidence"),
                        "description": None,
                        "coach_tip": None,
                    },
                ],
                claude_version=settings.claude_model,
            )
            await queue.put({"stage": "done", "analysis": result, "cached": False})
        finally:
            cache_conn.close()
            await queue.put(None)  # sentinel

    task = asyncio.create_task(driver())

    # Pre-flight: surface RateLimitedError as HTTP 429 *before* opening the stream.
    #
    # Invariant the driver must uphold: `analyse_frame` emits its first
    # `{"stage": "cache", ...}` event synchronously before any awaiting, so a
    # healthy call puts something on the queue within milliseconds. On
    # RateLimitedError the driver puts the None sentinel (no event). This
    # two-outcome shape lets the timeout below act as a clean selector:
    #   - event arrives → normal SSE path
    #   - sentinel arrives (first=None) → check the task for RateLimitedError
    #
    # 5s is a generous safety net — if the cache SQLite lookup ever hangs
    # longer than that we'd rather return a 429-looking error than stall the
    # client. In the hot path this timeout is never approached.
    try:
        first = await asyncio.wait_for(queue.get(), timeout=5.0)
    except asyncio.TimeoutError:
        first = None

    if first is None:
        # Driver ended immediately — consume the task to surface any exception.
        try:
            await task
        except RateLimitedError as exc:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": f"Claude cooldown — {math.ceil(exc.retry_after_s)}s "
                              f"until next call",
                    "retry_after_s": math.ceil(exc.retry_after_s),
                },
                headers={"Retry-After": str(math.ceil(exc.retry_after_s))},
            )

    async def replay_and_continue() -> AsyncIterator[bytes]:
        if first is not None:
            yield f"data: {json.dumps(first)}\n\n".encode("utf-8")
        while True:
            evt = await queue.get()
            if evt is None:
                break
            yield f"data: {json.dumps(evt)}\n\n".encode("utf-8")
        try:
            await task
        except RateLimitedError as exc:
            err_evt = {
                "stage": "error",
                "kind": "rate_limited",
                "retry_after_s": math.ceil(exc.retry_after_s),
            }
            yield f"data: {json.dumps(err_evt)}\n\n".encode("utf-8")
        except (ClaudeProcessError, ClaudeResponseError) as exc:
            err_evt = {"stage": "error", "kind": exc.__class__.__name__, "detail": str(exc)}
            yield f"data: {json.dumps(err_evt)}\n\n".encode("utf-8")

    return StreamingResponse(
        replay_and_continue(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
