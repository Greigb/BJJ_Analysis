"""Integration tests for POST /api/rolls/:id/analyse (M9b sections)."""
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

    # Stub run_claude so no real subprocess is spawned.
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return '{"narrative": "test narrative", "coach_tip": "test tip"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

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
            conn, id=roll_id, title="Fixture", date="2026-04-22",
            video_path=f"assets/{roll_id}/source.mp4",
            duration_s=2.0, partner=None, result="unknown",
            created_at=1713700000,
            player_a_name="Player A", player_b_name="Player B",
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
        assert r.status_code in (400, 422)

    def test_400_when_sections_empty(self, app_client):
        client, _, roll_id = app_client
        r = client.post(f"/api/rolls/{roll_id}/analyse", json={"sections": []})
        assert r.status_code in (400, 422)

    def test_400_when_end_before_start(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [{"start_s": 2.0, "end_s": 1.0}]},
        )
        assert r.status_code == 400

    def test_400_when_end_exceeds_duration(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [{"start_s": 0.0, "end_s": 999.0}]},
        )
        assert r.status_code == 400

    def test_accepts_sample_interval_s_but_ignores_it(self, app_client):
        """Old frontends may still send sample_interval_s — backend accepts, ignores."""
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [
                {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 0.25},
            ]},
        )
        assert r.status_code == 200

    def test_404_when_roll_missing(self, app_client):
        client, _, _ = app_client
        r = client.post(
            "/api/rolls/no-such-roll/analyse",
            json={"sections": [{"start_s": 0.0, "end_s": 1.0}]},
        )
        assert r.status_code == 404

    def test_happy_path_streams_section_events_and_persists(self, app_client):
        client, root, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [{"start_s": 0.0, "end_s": 1.0}]},
        )
        assert r.status_code == 200
        body = r.text
        assert "section_started" in body
        assert "section_done" in body
        assert '"stage": "done"' in body or '"stage":"done"' in body

        from server.db import connect, get_sections_by_roll
        conn = connect(root / "test.db")
        try:
            sections = get_sections_by_roll(conn, roll_id)
            assert len(sections) == 1
            assert sections[0]["narrative"] == "test narrative"
            assert sections[0]["coach_tip"] == "test tip"
            assert sections[0]["analysed_at"] is not None
        finally:
            conn.close()

        assert (root / "assets" / roll_id / "frames" / "frame_000000.jpg").exists()

    def test_analyse_passes_positions_from_app_state_into_pipeline(
        self, app_client, monkeypatch
    ):
        """/analyse should read app.state.positions_index + app.state.taxonomy
        and forward an ordered list[PositionNote] into run_section_analysis."""
        client, _, roll_id = app_client

        captured: dict = {}

        async def fake_pipeline(**kwargs):
            # Async generator — capture kwargs then yield one terminal event.
            captured.update(kwargs)
            yield {"stage": "done", "total": 0}

        monkeypatch.setattr(
            "server.api.analyse.run_section_analysis", fake_pipeline
        )

        fake_note = {
            "position_id": "fixture_pos",
            "name": "Fixture Position",
            "markdown": "# Fixture Position",
            "vault_path": "Positions/Fixture Position.md",
            "how_to_identify": "Distinctive cue here.",
        }
        client.app.state.positions_index = {"fixture_pos": fake_note}
        client.app.state.taxonomy = {
            "positions": [
                {"id": "fixture_pos", "name": "Fixture Position", "category": "guard_bottom"}
            ]
        }

        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [{"start_s": 0.0, "end_s": 1.0}]},
        )
        assert r.status_code == 200

        positions = captured.get("positions")
        assert isinstance(positions, list)
        assert len(positions) == 1
        assert positions[0]["position_id"] == "fixture_pos"
