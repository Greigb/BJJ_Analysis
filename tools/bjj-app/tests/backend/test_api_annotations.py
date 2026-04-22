"""Tests for PATCH /api/rolls/:id/moments/:moment_id/annotations."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


async def _upload_and_detect_moment(client: AsyncClient, short_video_path: Path) -> tuple[str, str]:
    """Upload + pose pre-pass. Returns (roll_id, first_moment_id)."""
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Annotations fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]

    pre = await client.post(
        f"/api/rolls/{roll_id}/analyse",
        json={"sections": [{"start_s": 0.0, "end_s": 2.0, "sample_interval_s": 1.0}]},
    )
    assert pre.status_code == 200

    detail = await client.get(f"/api/rolls/{roll_id}")
    moments = detail.json()["moments"]
    assert moments
    return roll_id, moments[0]["id"]


@pytest.mark.asyncio
async def test_patch_annotation_inserts_and_returns_row(
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
        roll_id, moment_id = await _upload_and_detect_moment(client, short_video_path)
        response = await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "a first note"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "a first note"
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_patch_annotation_appends_multiple(
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
        roll_id, moment_id = await _upload_and_detect_moment(client, short_video_path)
        await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "one"},
        )
        await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "two"},
        )

        detail = await client.get(f"/api/rolls/{roll_id}")

    moment = next(
        m for m in detail.json()["moments"] if m["id"] == moment_id
    )
    bodies = [a["body"] for a in moment["annotations"]]
    assert bodies == ["one", "two"]


@pytest.mark.asyncio
async def test_patch_annotation_returns_404_for_unknown_roll(
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
        response = await client.patch(
            "/api/rolls/no-such-roll/moments/no-such-moment/annotations",
            json={"body": "x"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_annotation_returns_404_for_unknown_moment(
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
        roll_id, _ = await _upload_and_detect_moment(client, short_video_path)
        response = await client.patch(
            f"/api/rolls/{roll_id}/moments/no-such-moment/annotations",
            json={"body": "x"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_annotation_rejects_empty_body(
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
        roll_id, moment_id = await _upload_and_detect_moment(client, short_video_path)
        response = await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "   "},
        )

    assert response.status_code == 400
