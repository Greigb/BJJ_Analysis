"""Tests for the Claude CLI adapter.

We fake asyncio.create_subprocess_exec with an object that quacks like asyncio
subprocesses: `.stdout.readline()` coroutines returning bytes, `.wait()`
returning an exit code, `.returncode` attribute.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from server.analysis.claude_cli import (
    ClaudeProcessError,
    ClaudeResponseError,
    RateLimitedError,
    analyse_frame,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import load_settings
from server.db import connect, init_db


# ---------- Fake subprocess plumbing ----------


@dataclass
class _FakeStream:
    chunks: list[bytes]

    async def readline(self) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class _FakeProcess:
    def __init__(self, stdout_lines: list[bytes], exit_code: int = 0) -> None:
        # Ensure each line ends with \n so the adapter can parse NDJSON.
        lines = [ln if ln.endswith(b"\n") else ln + b"\n" for ln in stdout_lines]
        self.stdout = _FakeStream(lines)
        self._exit_code = exit_code
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = self._exit_code
        return self._exit_code


def _ok_stream(assistant_json: dict) -> list[bytes]:
    """An NDJSON stream that ends with a stream-json 'result' event."""
    text = json.dumps(assistant_json)
    return [
        json.dumps({"type": "system", "subtype": "init"}).encode(),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text[:20]}]}}).encode(),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text[20:]}]}}).encode(),
        json.dumps({"type": "result", "result": text, "is_error": False}).encode(),
    ]


@pytest.fixture
def frame(tmp_path: Path) -> Path:
    p = tmp_path / "frame_000017.jpg"
    p.write_bytes(b"\xff\xd8\xff")
    return p


@pytest.fixture
def taxonomy(tmp_path: Path) -> Path:
    p = tmp_path / "taxonomy.json"
    p.write_text(json.dumps({
        "categories": {"standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"}},
        "positions": [
            {"id": "standing_neutral", "name": "Standing - Neutral",
             "category": "standing", "visual_cues": "x"},
            {"id": "closed_guard_bottom", "name": "Closed Guard (Bottom)",
             "category": "standing", "visual_cues": "x"},
            {"id": "closed_guard_top", "name": "Closed Guard (Top)",
             "category": "standing", "visual_cues": "x"},
        ],
    }))
    return p


@pytest.fixture
def cache_conn(tmp_path: Path):
    db = tmp_path / "cache.db"
    init_db(db)
    conn = connect(db)
    try:
        yield conn
    finally:
        conn.close()


def _settings_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, taxonomy: Path):
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))
    settings = load_settings()
    # Redirect taxonomy to the fixture.
    from dataclasses import replace
    return replace(settings, taxonomy_path=taxonomy)


_ASSISTANT_OK = {
    "timestamp": 17.0,
    "greig": {"position": "closed_guard_bottom", "confidence": 0.82},
    "anthony": {"position": "closed_guard_top", "confidence": 0.78},
    "description": "Greig is working from closed guard.",
    "coach_tip": "Break Anthony's posture before attacking.",
}


# ---------- Tests ----------


@pytest.mark.asyncio
async def test_analyse_frame_happy_path_streams_and_returns_parsed_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    spawned_cmds: list[list[str]] = []

    async def fake_spawn(*args, **kwargs):
        spawned_cmds.append(list(args))
        return _FakeProcess(_ok_stream(_ASSISTANT_OK), exit_code=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    received: list[dict] = []

    async def on_event(evt: dict) -> None:
        received.append(evt)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    result = await analyse_frame(
        frame_path=frame,
        timestamp_s=17.0,
        stream_callback=on_event,
        settings=settings,
        limiter=limiter,
        cache_conn=cache_conn,
    )

    assert result["greig"]["position"] == "closed_guard_bottom"
    assert result["anthony"]["position"] == "closed_guard_top"
    # At least one streaming event was surfaced.
    assert any(e.get("stage") == "streaming" for e in received)
    # The CLI was spawned exactly once with the Claude binary.
    assert len(spawned_cmds) == 1
    assert spawned_cmds[0][0].endswith("claude")


@pytest.mark.asyncio
async def test_analyse_frame_caches_result_and_skips_subprocess_on_second_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    spawn_count = {"n": 0}

    async def fake_spawn(*args, **kwargs):
        spawn_count["n"] += 1
        return _FakeProcess(_ok_stream(_ASSISTANT_OK), exit_code=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    async def noop(_: dict) -> None:
        return None

    await analyse_frame(frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn)
    await analyse_frame(frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn)

    assert spawn_count["n"] == 1


@pytest.mark.asyncio
async def test_analyse_frame_retries_once_on_nonzero_exit_then_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    spawn_count = {"n": 0}

    async def fake_spawn(*args, **kwargs):
        spawn_count["n"] += 1
        return _FakeProcess([b'{"type":"result","is_error":true,"result":""}'], exit_code=2)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    # Monkeypatch asyncio.sleep so the 2s backoff doesn't actually sleep.
    async def instant_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    async def noop(_: dict) -> None:
        return None

    with pytest.raises(ClaudeProcessError):
        await analyse_frame(
            frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn
        )

    assert spawn_count["n"] == 2  # initial + one retry


@pytest.mark.asyncio
async def test_analyse_frame_raises_on_unparseable_assistant_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    bad_stream = [
        json.dumps({"type": "system", "subtype": "init"}).encode(),
        json.dumps({"type": "result", "result": "not json at all", "is_error": False}).encode(),
    ]

    async def fake_spawn(*args, **kwargs):
        return _FakeProcess(bad_stream, exit_code=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    async def instant_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    async def noop(_: dict) -> None:
        return None

    with pytest.raises(ClaudeResponseError):
        await analyse_frame(
            frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn
        )


@pytest.mark.asyncio
async def test_analyse_frame_raises_rate_limited_when_limiter_denies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    async def never_spawn(*args, **kwargs):
        raise AssertionError("subprocess must not be spawned when rate-limited")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", never_spawn)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=1, window_seconds=60)
    # Exhaust the limiter.
    assert limiter.try_acquire() is None

    async def noop(_: dict) -> None:
        return None

    with pytest.raises(RateLimitedError) as exc:
        await analyse_frame(
            frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn
        )
    # The error carries a retry-after hint the endpoint will surface as HTTP 429.
    assert exc.value.retry_after_s > 0


@pytest.mark.asyncio
async def test_analyse_frame_refuses_frame_path_outside_project_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    # Security invariant: the adapter must never accept an arbitrary path.
    outside = Path("/etc/hosts")
    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    async def noop(_: dict) -> None:
        return None

    with pytest.raises(ValueError):
        await analyse_frame(
            outside, 0.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn
        )
