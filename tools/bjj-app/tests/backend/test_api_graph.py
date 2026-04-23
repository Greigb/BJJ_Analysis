"""Tests for GET /api/graph and GET /api/vault/position/:id."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _write_positions_vault(root: Path) -> None:
    pos_dir = root / "Positions"
    pos_dir.mkdir(exist_ok=True)
    (pos_dir / "Closed Guard (Bottom).md").write_text(
        "---\n"
        'category: "Guard (Bottom)"\n'
        "position_id: closed_guard_bottom\n"
        "---\n\n"
        "# Closed Guard (Bottom)\n\nBody.\n"
    )


def _write_minimal_taxonomy(root: Path) -> None:
    # The taxonomy is normally at `<project_root>/tools/taxonomy.json`.
    # For tests with BJJ_PROJECT_ROOT pointed at a tmp dir, place a minimal
    # copy at <tmp>/tools/taxonomy.json.
    import json
    tax_dir = root / "tools"
    tax_dir.mkdir(exist_ok=True)
    (tax_dir / "taxonomy.json").write_text(json.dumps({
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing", "category": "standing",
             "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "Closed Guard (Bottom)",
             "category": "guard_bottom", "visual_cues": "b"},
        ],
        "valid_transitions": [["standing_neutral", "closed_guard_bottom"]],
    }))


@pytest.mark.asyncio
async def test_get_graph_returns_taxonomy_shape(
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
        response = await client.get("/api/graph")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"categories", "positions", "techniques", "transitions"}
    assert len(body["positions"]) == 2
    assert body["transitions"] == [{"from": "standing_neutral", "to": "closed_guard_bottom"}]
    # Every category has a tint
    for cat in body["categories"]:
        assert cat["tint"].startswith("#")


@pytest.mark.asyncio
async def test_get_vault_position_returns_markdown_for_known_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _write_minimal_taxonomy(tmp_project_root)
    _write_positions_vault(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/vault/position/closed_guard_bottom")

    assert response.status_code == 200
    body = response.json()
    assert body["position_id"] == "closed_guard_bottom"
    assert body["name"] == "Closed Guard (Bottom)"
    assert "Body." in body["markdown"]
    assert body["vault_path"] == "Positions/Closed Guard (Bottom).md"


@pytest.mark.asyncio
async def test_get_vault_position_returns_404_for_unknown_id(
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
        response = await client.get("/api/vault/position/no_such_position")

    assert response.status_code == 404
