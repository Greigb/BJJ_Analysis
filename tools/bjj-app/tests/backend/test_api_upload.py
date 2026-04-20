from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_post_rolls_uploads_video_and_returns_roll(
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
        with short_video_path.open("rb") as f:
            response = await client.post(
                "/api/rolls",
                files={"video": ("short.mp4", f, "video/mp4")},
                data={"title": "Smoke roll", "date": "2026-04-20", "partner": "Anthony"},
            )

    assert response.status_code == 201, response.text
    body = response.json()

    assert "id" in body
    assert body["title"] == "Smoke roll"
    assert body["date"] == "2026-04-20"
    assert body["partner"] == "Anthony"
    assert body["result"] == "unknown"
    # Duration from the 2s fixture, allowing OpenCV rounding slack.
    assert 1.8 <= body["duration_s"] <= 2.2

    # Video physically stored under assets/<id>/source.mp4
    video_file = tmp_project_root / "assets" / body["id"] / "source.mp4"
    assert video_file.exists()
    assert video_file.stat().st_size > 0


@pytest.mark.asyncio
async def test_post_rolls_rejects_non_video_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()

    bad_file = tmp_project_root / "not-video.mp4"
    bad_file.write_bytes(b"not actually a video")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with bad_file.open("rb") as f:
            response = await client.post(
                "/api/rolls",
                files={"video": ("bad.mp4", f, "video/mp4")},
                data={"title": "Bad upload", "date": "2026-04-20"},
            )

    assert response.status_code == 400
    body = response.json()
    assert "detail" in body
