from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_get_roll_returns_detail_after_upload(
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
        # Upload first, then fetch detail.
        with short_video_path.open("rb") as f:
            upload = await client.post(
                "/api/rolls",
                files={"video": ("short.mp4", f, "video/mp4")},
                data={"title": "Detail test", "date": "2026-04-20"},
            )
        assert upload.status_code == 201
        roll_id = upload.json()["id"]

        get = await client.get(f"/api/rolls/{roll_id}")

    assert get.status_code == 200
    body = get.json()
    assert body["id"] == roll_id
    assert body["title"] == "Detail test"
    assert body["date"] == "2026-04-20"
    assert body["partner"] is None
    assert 1.8 <= body["duration_s"] <= 2.2
    assert body["video_url"] == f"/assets/{roll_id}/source.mp4"
    assert body["result"] == "unknown"


@pytest.mark.asyncio
async def test_get_roll_returns_404_for_unknown_id(
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
        response = await client.get("/api/rolls/nonexistent-id")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_uploaded_video_is_served_at_video_url(
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
            upload = await client.post(
                "/api/rolls",
                files={"video": ("short.mp4", f, "video/mp4")},
                data={"title": "Served", "date": "2026-04-20"},
            )
        roll_id = upload.json()["id"]
        video_url = upload.json()["video_url"]

        response = await client.get(video_url)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/")
    assert int(response.headers.get("content-length", "0")) > 0
