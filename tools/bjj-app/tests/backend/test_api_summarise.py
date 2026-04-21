"""Tests for POST /api/rolls/:id/summarise."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _minimal_taxonomy(root: Path) -> None:
    tax_dir = root / "tools"
    tax_dir.mkdir(exist_ok=True)
    (tax_dir / "taxonomy.json").write_text(json.dumps({
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing", "category": "standing", "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "CG Bottom", "category": "guard_bottom", "visual_cues": "b"},
        ],
        "valid_transitions": [],
    }))


async def _upload_and_analyse_moments(
    client: AsyncClient, short_video_path: Path
) -> tuple[str, list[str]]:
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Summarise fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]
    pre = await client.post(f"/api/rolls/{roll_id}/analyse")
    assert pre.status_code == 200
    return roll_id, []


def _seed_analyses(db_path: Path, roll_id: str, n_moments_to_analyse: int) -> list[str]:
    from server.db import connect, insert_analyses

    conn = connect(db_path)
    try:
        moments = conn.execute(
            "SELECT id FROM moments WHERE roll_id = ? ORDER BY timestamp_s LIMIT ?",
            (roll_id, n_moments_to_analyse),
        ).fetchall()
        moment_ids: list[str] = []
        for m in moments:
            insert_analyses(
                conn, moment_id=m["id"],
                players=[
                    {"player": "a", "position_id": "closed_guard_bottom",
                     "confidence": 0.8, "description": "d", "coach_tip": "t"},
                    {"player": "b", "position_id": "closed_guard_bottom",
                     "confidence": 0.75, "description": None, "coach_tip": None},
                ],
                claude_version="test",
            )
            moment_ids.append(m["id"])
    finally:
        conn.close()
    return moment_ids


_VALID_SUMMARY_OUTPUT_TEMPLATE = {
    "summary": "Tight roll in closed guard.",
    "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
    "top_improvements": ["imp a", "imp b", "imp c"],
    "strengths": ["patient grips", "solid base"],
    "key_moments": [],
}


@pytest.mark.asyncio
async def test_summarise_happy_path_persists_and_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app
    import server.api.summarise as summarise_mod

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse_moments(client, short_video_path)

    moment_ids = _seed_analyses(tmp_project_root / "test.db", roll_id, 3)
    if len(moment_ids) < 3:
        pytest.skip(f"fixture produced only {len(moment_ids)} moments; need >= 3")

    fake_output = dict(_VALID_SUMMARY_OUTPUT_TEMPLATE)
    fake_output["key_moments"] = [
        {"moment_id": moment_ids[0], "note": "first"},
        {"moment_id": moment_ids[1], "note": "second"},
        {"moment_id": moment_ids[2], "note": "third"},
    ]

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return json.dumps(fake_output)

    monkeypatch.setattr(summarise_mod, "run_claude", fake_run_claude)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["scores"]["summary"] == "Tight roll in closed guard."
    assert body["scores"]["scores"]["guard_retention"] == 8
    assert "distribution" in body
    assert body["finalised_at"] > 0

    from server.db import connect, get_roll
    conn = connect(tmp_project_root / "test.db")
    try:
        row = get_roll(conn, roll_id)
    finally:
        conn.close()
    assert row["finalised_at"] is not None
    assert json.loads(row["scores_json"])["summary"] == "Tight roll in closed guard."


@pytest.mark.asyncio
async def test_summarise_returns_400_when_no_analyses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse_moments(client, short_video_path)
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_summarise_returns_404_for_unknown_roll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/rolls/no-such-roll/summarise", json={})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_summarise_returns_502_on_malformed_claude_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app
    import server.api.summarise as summarise_mod

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse_moments(client, short_video_path)

    moment_ids = _seed_analyses(tmp_project_root / "test.db", roll_id, 1)
    if not moment_ids:
        pytest.skip("fixture produced zero moments")

    async def fake_malformed(prompt, *, settings, limiter, stream_callback=None):
        return "this is not json"

    monkeypatch.setattr(summarise_mod, "run_claude", fake_malformed)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_summarise_returns_429_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app
    from server.analysis.claude_cli import RateLimitedError
    import server.api.summarise as summarise_mod

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse_moments(client, short_video_path)

    moment_ids = _seed_analyses(tmp_project_root / "test.db", roll_id, 1)
    if not moment_ids:
        pytest.skip("fixture produced zero moments")

    async def fake_rate_limited(prompt, *, settings, limiter, stream_callback=None):
        raise RateLimitedError(retry_after_s=42.0)

    monkeypatch.setattr(summarise_mod, "run_claude", fake_rate_limited)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 429
    assert response.headers.get("retry-after") == "42"
