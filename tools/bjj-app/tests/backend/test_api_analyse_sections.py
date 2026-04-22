"""Integration tests for POST /api/rolls/:id/analyse (M9 sections)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _short_video_path() -> Path:
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


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

    from server.main import create_app
    from server.db import connect, create_roll, init_db

    init_db(tmp_path / "test.db")
    roll_id = "r1"
    import shutil
    roll_dir = tmp_path / "assets" / roll_id
    roll_dir.mkdir()
    shutil.copy(_short_video_path(), roll_dir / "source.mp4")

    conn = connect(tmp_path / "test.db")
    try:
        create_roll(
            conn,
            id=roll_id,
            title="Fixture",
            date="2026-04-22",
            video_path=f"assets/{roll_id}/source.mp4",
            duration_s=2.0,
            partner=None,
            result="unknown",
            created_at=1713700000,
            player_a_name="Player A",
            player_b_name="Player B",
        )
    finally:
        conn.close()

    app = create_app()
    with TestClient(app) as c:
        yield c, tmp_path, roll_id


class TestAnalyseSectionsEndpoint:
    def test_400_when_sections_missing(self, app_client):
        client, _, roll_id = app_client
        r = client.post(f"/api/rolls/{roll_id}/analyse", json={})
        assert r.status_code == 400 or r.status_code == 422

    def test_400_when_sections_empty(self, app_client):
        client, _, roll_id = app_client
        r = client.post(f"/api/rolls/{roll_id}/analyse", json={"sections": []})
        assert r.status_code == 400 or r.status_code == 422

    def test_400_when_end_before_start(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={
                "sections": [
                    {"start_s": 2.0, "end_s": 1.0, "sample_interval_s": 1.0}
                ]
            },
        )
        assert r.status_code == 400

    def test_400_when_end_exceeds_duration(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={
                "sections": [
                    {"start_s": 0.0, "end_s": 999.0, "sample_interval_s": 1.0}
                ]
            },
        )
        assert r.status_code == 400

    def test_400_when_interval_not_allowed(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={
                "sections": [
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 0.25}
                ]
            },
        )
        assert r.status_code == 400

    def test_404_when_roll_missing(self, app_client):
        client, _, _ = app_client
        r = client.post(
            "/api/rolls/no-such-roll/analyse",
            json={
                "sections": [
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0}
                ]
            },
        )
        assert r.status_code == 404

    def test_happy_path_streams_events_and_persists(self, app_client):
        client, root, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={
                "sections": [
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0},
                ]
            },
        )
        assert r.status_code == 200
        body = r.text
        assert "stage" in body
        assert "\"done\"" in body

        # DB has a section + moment
        from server.db import connect, get_moments, get_sections_by_roll
        conn = connect(root / "test.db")
        try:
            assert len(get_sections_by_roll(conn, roll_id)) == 1
            assert len(get_moments(conn, roll_id)) == 1
        finally:
            conn.close()

        # Frame on disk
        assert (root / "assets" / roll_id / "frames" / "frame_000000.jpg").exists()
