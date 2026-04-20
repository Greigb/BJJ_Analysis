import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


async def _upload_fixture_roll(client: AsyncClient, video_path: Path) -> str:
    with video_path.open("rb") as f:
        response = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Analyse fixture", "date": "2026-04-20"},
        )
    assert response.status_code == 201
    return response.json()["id"]


def _parse_sse_lines(body: str) -> list[dict]:
    events: list[dict] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_analyse_streams_progress_and_final_done(
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
        roll_id = await _upload_fixture_roll(client, short_video_path)

        response = await client.post(f"/api/rolls/{roll_id}/analyse")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_lines(response.text)
    stages = [e["stage"] for e in events]
    assert stages[0] == "frames"
    assert "pose" in stages
    assert stages[-1] == "done"

    done = events[-1]
    assert isinstance(done["moments"], list)


@pytest.mark.asyncio
async def test_analyse_persists_moments_to_db(
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
        roll_id = await _upload_fixture_roll(client, short_video_path)

        analyse = await client.post(f"/api/rolls/{roll_id}/analyse")
        assert analyse.status_code == 200
        done = _parse_sse_lines(analyse.text)[-1]
        expected_moments = done["moments"]

        detail = await client.get(f"/api/rolls/{roll_id}")

    assert detail.status_code == 200
    body = detail.json()
    assert "moments" in body
    assert len(body["moments"]) == len(expected_moments)
    # Each moment has the expected shape.
    for m in body["moments"]:
        assert "id" in m
        assert "frame_idx" in m
        assert "timestamp_s" in m
        assert "pose_delta" in m


@pytest.mark.asyncio
async def test_analyse_returns_404_for_unknown_roll(
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
        response = await client.post("/api/rolls/does-not-exist/analyse")

    assert response.status_code == 404
