"""Tests for POST /api/rolls/:id/publish."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


async def _upload_annotate(client: AsyncClient, short_video_path: Path) -> tuple[str, str]:
    """Upload + pre-analysis + add one annotation. Returns (roll_id, section_id)."""
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Publish fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]

    pre = await client.post(
        f"/api/rolls/{roll_id}/analyse",
        json={"sections": [{"start_s": 0.0, "end_s": 2.0, "sample_interval_s": 1.0}]},
    )
    assert pre.status_code == 200

    detail = await client.get(f"/api/rolls/{roll_id}")
    section_id = detail.json()["sections"][0]["id"]

    ann = await client.patch(
        f"/api/rolls/{roll_id}/sections/{section_id}/annotations",
        json={"body": "my note"},
    )
    assert ann.status_code == 201
    return roll_id, section_id


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
        roll_id, section_id = await _upload_annotate(client, short_video_path)
        first = await client.post(f"/api/rolls/{roll_id}/publish", json={})
        assert first.status_code == 200
        vault_path = tmp_project_root / first.json()["vault_path"]

        # Simulate external edit to Your Notes.
        original = vault_path.read_text()
        tampered = original.replace("my note", "my note — edited in Obsidian")
        vault_path.write_text(tampered)

        # Add another annotation + re-publish without force → 409.
        await client.patch(
            f"/api/rolls/{roll_id}/sections/{section_id}/annotations",
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
        roll_id, section_id = await _upload_annotate(client, short_video_path)
        first = await client.post(f"/api/rolls/{roll_id}/publish", json={})
        vault_path = tmp_project_root / first.json()["vault_path"]

        tampered = vault_path.read_text().replace("my note", "externally edited")
        vault_path.write_text(tampered)

        await client.patch(
            f"/api/rolls/{roll_id}/sections/{section_id}/annotations",
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
    """Integration: finalised roll publishes with all five summary sections (no Position Distribution)."""
    import json
    import time

    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, section_id = await _upload_annotate(client, short_video_path)

    from server.db import connect, get_sections_by_roll, set_summary_state

    conn = connect(tmp_project_root / "test.db")
    try:
        section_rows = get_sections_by_roll(conn, roll_id)
        if len(section_rows) < 1:
            pytest.skip(f"fixture produced no sections")
        # Build key_moments from available sections (up to 3).
        km_sections = section_rows[:3]
        scores_payload = {
            "summary": "Integration-test roll.",
            "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 8},
            "top_improvements": ["one", "two", "three"],
            "strengths": ["strong"],
            "key_moments": [
                {"section_id": s["id"], "note": f"note {i}"}
                for i, s in enumerate(km_sections)
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
    assert "## Key Moments" in text
    assert "## Top Improvements" in text
    assert "## Strengths Observed" in text
    assert "## Your Notes" in text
    # Position Distribution is gone post-M9b
    assert "## Position Distribution" not in text
