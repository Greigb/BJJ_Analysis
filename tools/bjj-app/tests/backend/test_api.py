from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_get_rolls_returns_list_from_vault(
    monkeypatch: pytest.MonkeyPatch,
    sample_vault: Path,
    tmp_path: Path,
) -> None:
    # Point settings at the sample vault fixture.
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(sample_vault))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))

    # Import AFTER monkeypatching so settings pick up the env.
    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/rolls")

    assert response.status_code == 200
    body = response.json()

    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["date"] == "2026-04-14"
    assert body[0]["partner"] == "Anthony"
    assert body[0]["title"] == "Roll 1: Greig vs Anthony — WIN by Submission"
    assert body[0]["result"] == "win_submission"
    assert "path" in body[0]


@pytest.mark.asyncio
async def test_get_rolls_returns_empty_list_when_no_roll_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))

    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/rolls")

    assert response.status_code == 200
    assert response.json() == []
