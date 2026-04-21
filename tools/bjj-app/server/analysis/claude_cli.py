"""SOLE adapter around the `claude` CLI.

All BJJ-app code that wants Claude inference goes through `analyse_frame`.
That isolates rate limiting, caching, retries, stream parsing, and future
model swaps behind a single seam.

Security note: `--dangerously-skip-permissions` is passed to `claude -p`.
This is audited in docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md.
The short version: the prompt is fully constructed by us (no user input
interpolated), the frame path is validated to lie inside the project root,
and the subprocess is spawned via create_subprocess_exec with an argv list —
never `shell=True`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Awaitable, Callable

from server.analysis.prompt import build_prompt
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import Settings
from server.db import cache_get, cache_put

AnalysisResult = dict
StreamCallback = Callable[[dict], Awaitable[None]]


class RateLimitedError(Exception):
    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"rate-limited: retry after {retry_after_s:.1f}s")
        self.retry_after_s = retry_after_s


class ClaudeProcessError(Exception):
    """Subprocess exited non-zero after a retry."""


class ClaudeResponseError(Exception):
    """stdout stream did not contain parseable assistant JSON."""


_RETRY_BACKOFF_SECONDS = 2.0


async def run_claude(
    prompt: str,
    *,
    settings: Settings,
    limiter: SlidingWindowLimiter,
    stream_callback: StreamCallback | None = None,
) -> str:
    """Spawn claude -p with the given prompt, return raw assistant text.

    Owns: rate-limit acquisition, subprocess spawn, stream-json stdout parsing,
    one retry on non-zero exit with 2s backoff.
    Does NOT own: prompt construction, caching, response schema validation.
    Callers layer those on top.

    Raises:
      RateLimitedError  — limiter rejected the call; caller surfaces 429.
      ClaudeProcessError — subprocess failed after retry.
    """
    wait = limiter.try_acquire()
    if wait is not None:
        raise RateLimitedError(retry_after_s=wait)

    assistant_text: str | None = None
    last_exit: int | None = None
    cb: StreamCallback = stream_callback if stream_callback is not None else _noop_stream_callback
    for attempt in range(2):
        assistant_text, last_exit = await _run_once(
            settings=settings, prompt=prompt, stream_callback=cb
        )
        if last_exit == 0 and assistant_text is not None:
            break
        if attempt == 0:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)

    if last_exit != 0:
        raise ClaudeProcessError(f"claude exited {last_exit}")

    if assistant_text is None:
        # Exit code was 0 but every result event had is_error=true — treat as
        # a process-level failure so the caller sees a consistent error type.
        raise ClaudeProcessError("claude exited 0 but all result events had is_error=true")

    return assistant_text


async def _noop_stream_callback(evt: dict) -> None:
    """Default stream callback — discards stream events."""
    return None


async def analyse_frame(
    frame_path: Path,
    timestamp_s: float,
    stream_callback: StreamCallback,
    *,
    settings: Settings,
    limiter: SlidingWindowLimiter,
    cache_conn: sqlite3.Connection,
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
) -> AnalysisResult:
    """Classify one frame with Claude Opus 4.7. See module docstring."""
    # --- Security invariant: frame must live inside the project root ---
    frame_resolved = frame_path.resolve()
    project_resolved = settings.project_root.resolve()
    try:
        frame_resolved.relative_to(project_resolved)
    except ValueError as exc:
        raise ValueError(
            f"frame_path {frame_path} escapes project root {project_resolved}"
        ) from exc
    if not frame_resolved.exists():
        raise FileNotFoundError(frame_path)

    # --- Cache lookup ---
    prompt = build_prompt(
        frame_path=frame_resolved,
        taxonomy_path=settings.taxonomy_path,
        timestamp_s=timestamp_s,
        player_a_name=player_a_name,
        player_b_name=player_b_name,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    frame_hash = _hash_file(frame_resolved)

    cached = cache_get(cache_conn, prompt_hash=prompt_hash, frame_hash=frame_hash)
    if cached is not None:
        await stream_callback({"stage": "cache", "hit": True})
        return cached

    await stream_callback({"stage": "cache", "hit": False})

    # --- Rate limit + spawn + retry — delegated to run_claude ---
    assistant_text = await run_claude(
        prompt,
        settings=settings,
        limiter=limiter,
        stream_callback=stream_callback,
    )

    try:
        parsed = json.loads(assistant_text)
    except json.JSONDecodeError as exc:
        raise ClaudeResponseError(
            f"assistant output was not JSON: {assistant_text[:200]!r}"
        ) from exc

    _validate_shape(parsed)
    cache_put(
        cache_conn, prompt_hash=prompt_hash, frame_hash=frame_hash, response=parsed
    )
    return parsed


async def _run_once(
    *,
    settings: Settings,
    prompt: str,
    stream_callback: StreamCallback,
) -> tuple[str | None, int]:
    """Run claude -p once. Returns (final_assistant_text, exit_code)."""
    argv = [
        str(settings.claude_bin),
        "-p",
        "--model", settings.claude_model,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--max-turns", "1",
        "--dangerously-skip-permissions",
        "--verbose",
        prompt,
    ]

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None

    final_text: str | None = None
    partial = ""

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip non-JSON lines (shouldn't happen with stream-json)

        etype = event.get("type")
        if etype == "assistant":
            # stream-json emits incremental assistant chunks; surface the deltas.
            chunk = _extract_text(event)
            if chunk:
                partial += chunk
                await stream_callback({"stage": "streaming", "text": partial})
        elif etype == "result":
            # Final event with the full assistant text. A truthy `is_error` means
            # the CLI reported a problem even if exit code ended up zero — treat
            # that the same as a non-zero exit so the outer retry logic fires.
            if event.get("is_error"):
                final_text = None
            else:
                final_text = event.get("result") or partial or None

    exit_code = await proc.wait()
    return final_text, exit_code


def _extract_text(assistant_event: dict) -> str:
    """Pull the text out of an `assistant` stream-json event."""
    msg = assistant_event.get("message") or {}
    content = msg.get("content") or []
    parts = []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text") or "")
    return "".join(parts)


def _hash_file(path: Path, chunk_size: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _validate_shape(parsed: dict) -> None:
    """Raise ClaudeResponseError if the JSON doesn't match the expected schema."""
    for key in ("player_a", "player_b", "description", "coach_tip"):
        if key not in parsed:
            raise ClaudeResponseError(f"missing key: {key}")
    for player in ("player_a", "player_b"):
        sub = parsed[player]
        if not isinstance(sub, dict) or "position" not in sub or "confidence" not in sub:
            raise ClaudeResponseError(f"malformed player subobject: {player}")
