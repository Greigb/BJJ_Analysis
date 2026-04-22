"""Tests for POST /api/rolls/:id/summarise (M9b section-based)."""
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
        "events": {}, "categories": {}, "positions": [], "valid_transitions": [],
    }))


def _seed_roll_with_analysed_sections(
    db_path: Path, n_sections: int = 3
) -> tuple[str, list[str]]:
    """Create a roll + N analysed sections directly via DB. Returns (roll_id, section_ids)."""
    from server.db import (
        connect, create_roll, init_db, insert_section, update_section_analysis,
    )
    init_db(db_path)
    conn = connect(db_path)
    try:
        roll_id = "roll-sum"
        create_roll(
            conn, id=roll_id, title="Summarise fixture",
            date="2026-04-21", video_path=f"assets/{roll_id}/source.mp4",
            duration_s=60.0, partner=None, result="unknown",
            created_at=int(time.time()),
            player_a_name="Player A", player_b_name="Player B",
        )
        section_ids: list[str] = []
        for i in range(n_sections):
            sec = insert_section(
                conn, roll_id=roll_id,
                start_s=float(i * 10), end_s=float(i * 10 + 5),
                sample_interval_s=1.0,
            )
            update_section_analysis(
                conn, section_id=sec["id"],
                narrative=f"Section {i} narrative.",
                coach_tip=f"Tip {i}.",
                analysed_at=int(time.time()),
            )
            section_ids.append(sec["id"])
    finally:
        conn.close()
    return roll_id, section_ids


_VALID_SUMMARY_OUTPUT_TEMPLATE = {
    "summary": "Tight roll in closed guard.",
    "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
    "top_improvements": ["imp a", "imp b", "imp c"],
    "strengths": ["patient grips", "solid base"],
}


@pytest.mark.asyncio
async def test_summarise_happy_path_persists_and_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    roll_id, section_ids = _seed_roll_with_analysed_sections(tmp_project_root / "test.db", 3)

    fake_output = dict(_VALID_SUMMARY_OUTPUT_TEMPLATE)
    fake_output["key_moments"] = [
        {"section_id": section_ids[0], "note": "first"},
        {"section_id": section_ids[1], "note": "second"},
        {"section_id": section_ids[2], "note": "third"},
    ]

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return json.dumps(fake_output)

    from server.main import create_app
    import server.api.summarise as summarise_mod
    monkeypatch.setattr(summarise_mod, "run_claude", fake_run_claude)

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["scores"]["summary"] == "Tight roll in closed guard."
    assert body["scores"]["scores"]["guard_retention"] == 8
    assert "distribution" not in body  # M9b dropped
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
async def test_summarise_returns_400_when_no_analysed_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    # Seed a roll with sections that have NULL narrative (staged but not analysed).
    from server.db import connect, create_roll, init_db, insert_section
    db = tmp_project_root / "test.db"
    init_db(db)
    conn = connect(db)
    try:
        create_roll(
            conn, id="r1", title="T", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=10.0,
            partner=None, result="unknown", created_at=1,
        )
        insert_section(conn, roll_id="r1", start_s=0.0, end_s=2.0, sample_interval_s=1.0)
    finally:
        conn.close()

    from server.main import create_app
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/rolls/r1/summarise", json={})
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

    from server.db import init_db
    init_db(tmp_project_root / "test.db")

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
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    roll_id, _ = _seed_roll_with_analysed_sections(tmp_project_root / "test.db", 1)

    async def fake_malformed(prompt, *, settings, limiter, stream_callback=None):
        return "this is not json"

    from server.main import create_app
    import server.api.summarise as summarise_mod
    monkeypatch.setattr(summarise_mod, "run_claude", fake_malformed)

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_summarise_returns_429_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    roll_id, _ = _seed_roll_with_analysed_sections(tmp_project_root / "test.db", 1)

    from server.analysis.claude_cli import RateLimitedError

    async def fake_rate_limited(prompt, *, settings, limiter, stream_callback=None):
        raise RateLimitedError(retry_after_s=42.0)

    from server.main import create_app
    import server.api.summarise as summarise_mod
    monkeypatch.setattr(summarise_mod, "run_claude", fake_rate_limited)

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "42"
