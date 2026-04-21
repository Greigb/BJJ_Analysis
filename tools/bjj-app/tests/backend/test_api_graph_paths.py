"""Tests for GET /api/graph/paths/:roll_id."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _write_minimal_taxonomy(root: Path) -> None:
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
            {"id": "closed_guard_top", "name": "CG Top", "category": "guard_bottom", "visual_cues": "c"},
            {"id": "half_guard_bottom", "name": "HG Bottom", "category": "guard_bottom", "visual_cues": "d"},
            {"id": "half_guard_top", "name": "HG Top", "category": "guard_bottom", "visual_cues": "e"},
        ],
        "valid_transitions": [],
    }))


def _seed_roll_with_analyses(db_path: Path) -> tuple[str, str, str]:
    """Insert a roll with 2 moments, analyses for both players on both moments.
    Returns (roll_id, moment1_id, moment2_id)."""
    from server.db import (
        connect,
        create_roll,
        init_db,
        insert_analyses,
        insert_moments,
    )

    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn, id="roll-1", title="T", date="2026-04-21",
        video_path="assets/roll-1/source.mp4", duration_s=45.0,
        partner="Anthony", result="unknown", created_at=int(time.time()),
    )
    moments = insert_moments(
        conn, roll_id="roll-1",
        moments=[
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 12, "timestamp_s": 12.0, "pose_delta": 0.9},
        ],
    )
    insert_analyses(
        conn, moment_id=moments[0]["id"],
        players=[
            {"player": "greig", "position_id": "closed_guard_bottom", "confidence": 0.9,
             "description": "d", "coach_tip": "t"},
            {"player": "anthony", "position_id": "closed_guard_top", "confidence": 0.88,
             "description": None, "coach_tip": None},
        ],
        claude_version="test",
    )
    insert_analyses(
        conn, moment_id=moments[1]["id"],
        players=[
            {"player": "greig", "position_id": "half_guard_bottom", "confidence": 0.82,
             "description": "d", "coach_tip": "t"},
            {"player": "anthony", "position_id": "half_guard_top", "confidence": 0.8,
             "description": None, "coach_tip": None},
        ],
        claude_version="test",
    )
    conn.close()
    return "roll-1", moments[0]["id"], moments[1]["id"]


@pytest.mark.asyncio
async def test_get_graph_paths_returns_sorted_sequences(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _write_minimal_taxonomy(tmp_project_root)
    db_path = tmp_project_root / "test.db"
    _seed_roll_with_analyses(db_path)

    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(db_path))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph/paths/roll-1")

    assert response.status_code == 200
    body = response.json()
    assert body["duration_s"] == 45.0
    greig = body["paths"]["greig"]
    anthony = body["paths"]["anthony"]
    assert [p["position_id"] for p in greig] == ["closed_guard_bottom", "half_guard_bottom"]
    assert [p["position_id"] for p in anthony] == ["closed_guard_top", "half_guard_top"]
    # Must be sorted by timestamp_s
    assert greig[0]["timestamp_s"] == 3.0
    assert greig[1]["timestamp_s"] == 12.0


@pytest.mark.asyncio
async def test_get_graph_paths_returns_empty_when_no_analyses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    import time as _time

    _write_minimal_taxonomy(tmp_project_root)
    db_path = tmp_project_root / "test.db"
    from server.db import connect, create_roll, init_db

    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn, id="roll-empty", title="T", date="2026-04-21",
        video_path="assets/roll-empty/source.mp4", duration_s=30.0,
        partner=None, result="unknown", created_at=int(_time.time()),
    )
    conn.close()

    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(db_path))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph/paths/roll-empty")

    assert response.status_code == 200
    body = response.json()
    assert body["paths"]["greig"] == []
    assert body["paths"]["anthony"] == []


@pytest.mark.asyncio
async def test_get_graph_paths_returns_404_for_unknown_roll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _write_minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph/paths/no-such-roll")

    assert response.status_code == 404
