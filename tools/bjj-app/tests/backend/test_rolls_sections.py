"""Test that GET /api/rolls/:id returns sections."""
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
            conn,
            id="r1",
            title="Fixture",
            date="2026-04-22",
            video_path="assets/r1/source.mp4",
            duration_s=60.0,
            partner=None,
            result="unknown",
            created_at=1713700000,
            player_a_name="Player A",
            player_b_name="Player B",
        )
        insert_section(conn, roll_id="r1", start_s=3.0, end_s=7.0, sample_interval_s=1.0)
        insert_section(conn, roll_id="r1", start_s=10.0, end_s=14.0, sample_interval_s=0.5)
    finally:
        conn.close()

    from server.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_roll_detail_includes_sections(app_client):
    r = app_client.get("/api/rolls/r1")
    assert r.status_code == 200
    body = r.json()
    assert "sections" in body
    assert len(body["sections"]) == 2
    assert body["sections"][0]["start_s"] == 3.0
    assert body["sections"][0]["sample_interval_s"] == 1.0
    assert body["sections"][1]["start_s"] == 10.0


def test_delete_section_removes_row_and_moments(app_client):
    r0 = app_client.get("/api/rolls/r1").json()
    section_id = r0["sections"][0]["id"]
    r = app_client.delete(f"/api/rolls/r1/sections/{section_id}")
    assert r.status_code == 204
    r1 = app_client.get("/api/rolls/r1").json()
    assert section_id not in {s["id"] for s in r1["sections"]}


def test_roll_detail_sections_include_narrative_coach_tip_annotations(app_client):
    """The fixture inserts two sections; update the first with analysis + annotation."""
    import os
    from server.db import connect, insert_annotation, update_section_analysis

    db_path = os.environ["BJJ_DB_OVERRIDE"]
    conn = connect(db_path)
    try:
        r0 = app_client.get("/api/rolls/r1").json()
        section_id = r0["sections"][0]["id"]
        update_section_analysis(
            conn, section_id=section_id,
            narrative="A passes to side control.",
            coach_tip="Stay heavy.",
            analysed_at=1713700100,
        )
        insert_annotation(
            conn, section_id=section_id, body="first note", created_at=1713700200,
        )
    finally:
        conn.close()

    r1 = app_client.get("/api/rolls/r1").json()
    s0 = r1["sections"][0]
    assert s0["narrative"] == "A passes to side control."
    assert s0["coach_tip"] == "Stay heavy."
    assert s0["analysed_at"] == 1713700100
    assert len(s0["annotations"]) == 1
    assert s0["annotations"][0]["body"] == "first note"


def test_roll_detail_distribution_is_null(app_client):
    r = app_client.get("/api/rolls/r1").json()
    assert r["distribution"] is None
