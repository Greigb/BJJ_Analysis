"""Tests for PATCH /api/rolls/:id/sections/:section_id/annotations."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))
    (tmp_path / "Roll Log").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "taxonomy.json").write_text(json.dumps({
        "events": {}, "categories": {}, "positions": [], "valid_transitions": [],
    }))

    from server.db import connect, create_roll, init_db, insert_section
    init_db(tmp_path / "test.db")
    conn = connect(tmp_path / "test.db")
    try:
        create_roll(
            conn, id="r1", title="T", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=10.0,
            partner=None, result="unknown", created_at=1713700000,
        )
        sec = insert_section(conn, roll_id="r1", start_s=0.0, end_s=4.0, sample_interval_s=1.0)
    finally:
        conn.close()

    from server.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c, sec["id"]


def test_annotation_appends_to_section(app_client):
    client, section_id = app_client
    r = client.patch(
        f"/api/rolls/r1/sections/{section_id}/annotations",
        json={"body": "keep elbows in"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["body"] == "keep elbows in"
    assert body["id"]


def test_annotation_missing_section_returns_404(app_client):
    client, _ = app_client
    r = client.patch(
        "/api/rolls/r1/sections/no-such/annotations",
        json={"body": "x"},
    )
    assert r.status_code == 404


def test_annotation_empty_body_returns_400(app_client):
    client, section_id = app_client
    r = client.patch(
        f"/api/rolls/r1/sections/{section_id}/annotations",
        json={"body": "   "},
    )
    assert r.status_code == 400


def test_annotation_missing_roll_returns_404(app_client):
    client, section_id = app_client
    r = client.patch(
        f"/api/rolls/no-such/sections/{section_id}/annotations",
        json={"body": "x"},
    )
    assert r.status_code == 404
