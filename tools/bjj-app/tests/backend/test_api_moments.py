"""Tests for POST /api/rolls/:id/moments/:frame_idx/analyse.

The endpoint is mocked at the `analyse_frame` seam, NOT by faking subprocesses
at the asyncio level — claude_cli.py already owns that concern and has its
own tests. Here we verify the HTTP wiring: SSE framing, persistence, 404s,
429 behaviour.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _parse_sse_lines(body: str) -> list[dict]:
    events: list[dict] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


async def _upload_and_analyse(
    client: AsyncClient, short_video_path: Path
) -> tuple[str, list[dict]]:
    """Upload + run pose pre-pass → return (roll_id, moments_in_response)."""
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Moment analyse fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]

    pre = await client.post(f"/api/rolls/{roll_id}/analyse")
    assert pre.status_code == 200
    detail = await client.get(f"/api/rolls/{roll_id}")
    return roll_id, detail.json()["moments"]


_FAKE_RESULT = {
    "timestamp": 1.0,
    "greig": {"position": "closed_guard_bottom", "confidence": 0.9},
    "anthony": {"position": "closed_guard_top", "confidence": 0.85},
    "description": "Closed guard.",
    "coach_tip": "Break posture.",
}


@pytest.mark.asyncio
async def test_moment_analyse_streams_and_persists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    # Patch claude_cli.analyse_frame where api.moments imports it from.
    async def fake_analyse_frame(frame_path, timestamp_s, stream_callback, **kw):
        await stream_callback({"stage": "cache", "hit": False})
        await stream_callback({"stage": "streaming", "text": '{"greig":'})
        return _FAKE_RESULT

    import server.api.moments as moments_mod
    monkeypatch.setattr(moments_mod, "analyse_frame", fake_analyse_frame)

    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moments = await _upload_and_analyse(client, short_video_path)
        assert moments, "pose pre-pass must flag at least one moment on the fixture"
        first_frame_idx = moments[0]["frame_idx"]

        analyse = await client.post(
            f"/api/rolls/{roll_id}/moments/{first_frame_idx}/analyse"
        )

    assert analyse.status_code == 200
    assert analyse.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_lines(analyse.text)
    stages = [e["stage"] for e in events]
    assert stages[0] == "cache"
    assert stages[-1] == "done"
    assert events[-1]["analysis"]["greig"]["position"] == "closed_guard_bottom"

    # After the stream, the moment's analyses are persisted in the DB.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client2:
        detail = await client2.get(f"/api/rolls/{roll_id}")
    body = detail.json()
    target = next(m for m in body["moments"] if m["frame_idx"] == first_frame_idx)
    players = sorted(a["player"] for a in target["analyses"])
    assert players == ["anthony", "greig"]


@pytest.mark.asyncio
async def test_moment_analyse_returns_404_for_unknown_roll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/rolls/does-not-exist/moments/0/analyse")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_moment_analyse_returns_404_for_unknown_frame_idx(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse(client, short_video_path)
        response = await client.post(
            f"/api/rolls/{roll_id}/moments/99999/analyse"
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_moment_analyse_returns_429_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.analysis.claude_cli import RateLimitedError

    async def always_rate_limited(*args, **kwargs):
        raise RateLimitedError(retry_after_s=42.0)

    import server.api.moments as moments_mod
    monkeypatch.setattr(moments_mod, "analyse_frame", always_rate_limited)

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moments = await _upload_and_analyse(client, short_video_path)
        response = await client.post(
            f"/api/rolls/{roll_id}/moments/{moments[0]['frame_idx']}/analyse"
        )
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "42"
    assert "retry_after_s" in response.json()
