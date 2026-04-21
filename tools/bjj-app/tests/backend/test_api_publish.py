"""Tests for POST /api/rolls/:id/publish."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


async def _upload_annotate(client: AsyncClient, short_video_path: Path) -> tuple[str, str]:
    """Upload + pose pre-pass + add one annotation. Returns (roll_id, moment_id)."""
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Publish fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]

    pre = await client.post(f"/api/rolls/{roll_id}/analyse")
    assert pre.status_code == 200

    detail = await client.get(f"/api/rolls/{roll_id}")
    moment_id = detail.json()["moments"][0]["id"]

    ann = await client.patch(
        f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
        json={"body": "my note"},
    )
    assert ann.status_code == 201
    return roll_id, moment_id


@pytest.mark.asyncio
async def test_publish_first_time_creates_file_and_returns_200(
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
        roll_id, _ = await _upload_annotate(client, short_video_path)
        response = await client.post(
            f"/api/rolls/{roll_id}/publish", json={}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["vault_path"].startswith("Roll Log/")
    assert body["your_notes_hash"]
    assert body["vault_published_at"] > 0

    vault_file = tmp_project_root / body["vault_path"]
    assert vault_file.exists()
    content = vault_file.read_text()
    assert "my note" in content
    assert "## Your Notes" in content
    assert f'roll_id: "{roll_id}"' in content


@pytest.mark.asyncio
async def test_publish_returns_409_on_external_your_notes_edit(
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
        roll_id, moment_id = await _upload_annotate(client, short_video_path)
        first = await client.post(f"/api/rolls/{roll_id}/publish", json={})
        assert first.status_code == 200
        vault_path = tmp_project_root / first.json()["vault_path"]

        # Simulate external edit to Your Notes.
        original = vault_path.read_text()
        tampered = original.replace("my note", "my note — edited in Obsidian")
        vault_path.write_text(tampered)

        # Add another annotation + re-publish without force → 409.
        await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "second note"},
        )
        second = await client.post(f"/api/rolls/{roll_id}/publish", json={})

    assert second.status_code == 409
    body = second.json()
    assert body["current_hash"] != body["stored_hash"]


@pytest.mark.asyncio
async def test_publish_force_true_overrides_conflict(
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
        roll_id, moment_id = await _upload_annotate(client, short_video_path)
        first = await client.post(f"/api/rolls/{roll_id}/publish", json={})
        vault_path = tmp_project_root / first.json()["vault_path"]

        tampered = vault_path.read_text().replace("my note", "externally edited")
        vault_path.write_text(tampered)

        await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "force note"},
        )

        forced = await client.post(
            f"/api/rolls/{roll_id}/publish", json={"force": True}
        )

    assert forced.status_code == 200
    content = vault_path.read_text()
    assert "externally edited" not in content
    assert "force note" in content


@pytest.mark.asyncio
async def test_publish_returns_404_for_unknown_roll(
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
        response = await client.post("/api/rolls/no-such-roll/publish", json={})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_publish_finalised_roll_writes_summary_sections_to_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    """Integration: finalised roll publishes with all six summary sections."""
    import json
    import time

    tax_dir = tmp_project_root / "tools"
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

    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moment_id = await _upload_annotate(client, short_video_path)

    from server.db import connect, set_summary_state

    conn = connect(tmp_project_root / "test.db")
    try:
        rows = conn.execute(
            "SELECT id FROM moments WHERE roll_id = ? ORDER BY timestamp_s", (roll_id,)
        ).fetchall()
        # Need at least 3 distinct moment_ids for key_moments validation.
        if len(rows) < 3:
            pytest.skip(f"fixture produced only {len(rows)} moments; need >= 3")
        scores_payload = {
            "summary": "Integration-test roll.",
            "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 8},
            "top_improvements": ["one", "two", "three"],
            "strengths": ["strong"],
            "key_moments": [
                {"moment_id": rows[0]["id"], "note": "first"},
                {"moment_id": rows[1]["id"], "note": "second"},
                {"moment_id": rows[2]["id"], "note": "third"},
            ],
        }
        set_summary_state(
            conn, roll_id=roll_id, scores_payload=scores_payload, finalised_at=int(time.time()),
        )
    finally:
        conn.close()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/publish", json={})

    assert response.status_code == 200
    vault_path = tmp_project_root / response.json()["vault_path"]
    text = vault_path.read_text()
    assert "## Summary" in text
    assert "Integration-test roll." in text
    assert "## Scores" in text
    assert "## Position Distribution" in text
    assert "## Key Moments" in text
    assert "## Top Improvements" in text
    assert "## Strengths Observed" in text
    assert "## Your Notes" in text
