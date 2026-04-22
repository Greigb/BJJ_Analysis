"""M9b section-sequence analysis pipeline.

Per user-picked section: extract 1 fps frames (cap 8), persist section + moments,
call Claude Opus with a multi-image narrative prompt, stream SSE progress events.
Append semantics — a second Analyse click adds new sections rather than replacing
prior ones.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import AsyncIterator

from server.analysis.claude_cli import (
    ClaudeProcessError,
    ClaudeResponseError,
    RateLimitedError,
    run_claude,
)
from server.analysis.frames import extract_frames_at_timestamps
from server.analysis.positions_vault import PositionNote
from server.analysis.prompt import (
    SectionResponseError,
    build_section_prompt,
    parse_section_response,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import Settings
from server.db import (
    append_moments,
    insert_section,
    update_section_analysis,
)

_MAX_FRAMES_PER_SECTION = 8
_MAX_RATE_LIMIT_RETRIES = 3


def _section_timestamps(start_s: float, end_s: float) -> list[float]:
    """1 fps sampling, capped at _MAX_FRAMES_PER_SECTION, rounded to 3dp."""
    duration = max(0.0, end_s - start_s)
    n = min(_MAX_FRAMES_PER_SECTION, max(1, int(round(duration))))
    if n <= 1:
        return [round(start_s, 3)]
    step = duration / n
    return [round(start_s + i * step, 3) for i in range(n)]


def _next_frame_idx(conn, roll_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(frame_idx), -1) AS m FROM moments WHERE roll_id = ?",
        (roll_id,),
    ).fetchone()
    return int(row["m"]) + 1


async def run_section_analysis(
    *,
    conn,
    roll_id: str,
    video_path: Path,
    frames_dir: Path,
    sections: list[dict],
    duration_s: float,
    player_a_name: str,
    player_b_name: str,
    settings: Settings,
    limiter: SlidingWindowLimiter,
    player_a_description: str | None = None,
    player_b_description: str | None = None,
    positions: list[PositionNote] | None = None,
) -> AsyncIterator[dict]:
    """Process each section sequentially. Yields SSE-shaped dicts.

    Event shapes:
      {"stage": "section_started", "section_id", "start_s", "end_s", "idx", "total"}
      {"stage": "section_queued",  "section_id", "retry_after_s"}
      {"stage": "section_done",    "section_id", "start_s", "end_s",
                                   "narrative", "coach_tip"}
      {"stage": "section_error",   "section_id", "error"}
      {"stage": "done",            "total"}
    """
    total = len(sections)
    for idx, sec_in in enumerate(sections):
        start_s = float(sec_in["start_s"])
        end_s = float(sec_in["end_s"])
        timestamps = _section_timestamps(start_s, end_s)

        start_index = _next_frame_idx(conn, roll_id)
        frame_paths = extract_frames_at_timestamps(
            video_path=video_path,
            timestamps=timestamps,
            out_dir=frames_dir,
            start_index=start_index,
        )

        section_row = insert_section(
            conn,
            roll_id=roll_id,
            start_s=start_s,
            end_s=end_s,
            sample_interval_s=1.0,
        )
        section_id = section_row["id"]

        append_moments(
            conn,
            roll_id=roll_id,
            moments=[
                {
                    "frame_idx": start_index + i,
                    "timestamp_s": timestamps[i],
                    "pose_delta": None,
                    "section_id": section_id,
                }
                for i in range(len(timestamps))
            ],
        )

        yield {
            "stage": "section_started",
            "section_id": section_id,
            "start_s": start_s,
            "end_s": end_s,
            "idx": idx,
            "total": total,
        }

        prompt = build_section_prompt(
            start_s=start_s,
            end_s=end_s,
            frame_paths=frame_paths,
            timestamps=timestamps,
            player_a_name=player_a_name,
            player_b_name=player_b_name,
            player_a_description=player_a_description,
            player_b_description=player_b_description,
            positions=positions,
        )

        error_msg: str | None = None
        raw: str | None = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES):
            try:
                raw = await run_claude(prompt, settings=settings, limiter=limiter)
                break
            except RateLimitedError as exc:
                if attempt == _MAX_RATE_LIMIT_RETRIES - 1:
                    error_msg = f"rate-limited after {_MAX_RATE_LIMIT_RETRIES} retries"
                    break
                yield {
                    "stage": "section_queued",
                    "section_id": section_id,
                    "retry_after_s": exc.retry_after_s,
                }
                await asyncio.sleep(exc.retry_after_s)
            except (ClaudeProcessError, ClaudeResponseError) as exc:
                error_msg = f"claude failed: {exc}"
                break

        if error_msg is None and raw is not None:
            try:
                parsed = parse_section_response(raw)
            except SectionResponseError as exc:
                error_msg = f"malformed output: {exc}"
            else:
                update_section_analysis(
                    conn,
                    section_id=section_id,
                    narrative=parsed["narrative"],
                    coach_tip=parsed["coach_tip"],
                    analysed_at=int(time.time()),
                )
                yield {
                    "stage": "section_done",
                    "section_id": section_id,
                    "start_s": start_s,
                    "end_s": end_s,
                    "narrative": parsed["narrative"],
                    "coach_tip": parsed["coach_tip"],
                }
                continue

        yield {
            "stage": "section_error",
            "section_id": section_id,
            "error": error_msg or "unknown error",
        }

    yield {"stage": "done", "total": total}
