"""Integration tests for POST /api/rolls/:id/export-pdf."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _minimal_taxonomy(root: Path) -> None:
    """Write a minimal taxonomy.json into `<root>/tools/`.

    Matches the shape `server/analysis/taxonomy.load_taxonomy` expects.
    """
    tax_dir = root / "tools"
    tax_dir.mkdir(exist_ok=True)
    (tax_dir / "taxonomy.json").write_text(json.dumps({
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
            "scramble": {"label": "Scramble", "dominance": 0, "visual_cues": "z"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing", "category": "standing", "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "CG Bottom", "category": "guard_bottom", "visual_cues": "b"},
        ],
        "valid_transitions": [],
    }))


def _setup_finalised_roll(db_path: Path, roll_id: str, project_root: Path) -> list[str]:
    """Create a roll in the DB with 1 section and a finalised summary.

    Returns [section_id] so tests can reference it in key_moments.
    """
    from server.db import (
        connect,
        create_roll,
        insert_section,
        set_summary_state,
    )

    # Also create the assets dir the upload would normally have created.
    (project_root / "assets" / roll_id).mkdir(parents=True, exist_ok=True)

    conn = connect(db_path)
    try:
        create_roll(
            conn,
            id=roll_id,
            title="Tuesday Roll",
            date="2026-04-21",
            video_path=f"assets/{roll_id}/source.mp4",
            duration_s=245.0,
            partner=None,
            result="unknown",
            created_at=1713700000,
            player_a_name="Greig",
            player_b_name="Partner",
        )
        sec_row = insert_section(
            conn,
            roll_id=roll_id,
            start_s=12.5,
            end_s=30.0,
            sample_interval_s=5.0,
        )
        sec_id = sec_row["id"]
        set_summary_state(
            conn,
            roll_id=roll_id,
            scores_payload={
                "summary": "Solid guard retention.",
                "scores": {
                    "guard_retention": 7,
                    "positional_awareness": 3,
                    "transition_quality": 8,
                },
                "top_improvements": ["Chain sweeps from closed guard."],
                "strengths": ["Strong retention."],
                "key_moments": [{"section_id": sec_id, "note": "First sweep attempt."}],
            },
            finalised_at=1713700100,
        )
        return [sec_id]
    finally:
        conn.close()


def _setup_unfinalised_roll(db_path: Path, roll_id: str, project_root: Path) -> None:
    from server.db import connect, create_roll

    (project_root / "assets" / roll_id).mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        create_roll(
            conn,
            id=roll_id,
            title="Unfinalised Roll",
            date="2026-04-21",
            video_path=f"assets/{roll_id}/source.mp4",
            duration_s=10.0,
            partner=None,
            result="unknown",
            created_at=1713700000,
            player_a_name="A",
            player_b_name="B",
        )
    finally:
        conn.close()


@pytest.fixture
def app_client(monkeypatch, tmp_project_root):
    """Return (TestClient, project_root) with env vars pointing at tmp_project_root."""
    _minimal_taxonomy(tmp_project_root)
    db_path = tmp_project_root / "test.db"
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(db_path))

    from server.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client, tmp_project_root, db_path


class TestExportPdfEndpoint:
    def test_400_when_not_finalised(self, app_client):
        client, root, db_path = app_client
        roll_id = "abcdef1234567890abcdef1234567890"
        _setup_unfinalised_roll(db_path, roll_id, root)

        r = client.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r.status_code == 400
        assert "finalised" in r.json()["detail"].lower()

    def test_404_when_roll_missing(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/rolls/00000000000000000000000000000000/export-pdf")
        assert r.status_code == 404

    def test_happy_path_writes_pdf_and_markdown(self, app_client):
        client, root, db_path = app_client
        roll_id = "abcdef1234567890abcdef1234567890"
        _setup_finalised_roll(db_path, roll_id, root)

        r = client.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert "attachment" in r.headers["content-disposition"]
        assert r.content.startswith(b"%PDF-")

        # PDF file exists on disk
        assert (root / "assets" / roll_id / "report.pdf").exists()

        # Markdown has ## Report section
        md_files = list((root / "Roll Log").glob("*.md"))
        assert md_files, "Expected a Roll Log markdown file to be created"
        md = md_files[0].read_text(encoding="utf-8")
        assert "## Report" in md
        assert f"[[assets/{roll_id}/report.pdf|Match report PDF]]" in md

        # Hash persisted
        from server.db import connect

        conn = connect(db_path)
        try:
            row = conn.execute(
                "SELECT vault_summary_hashes FROM rolls WHERE id = ?", (roll_id,)
            ).fetchone()
        finally:
            conn.close()
        hashes = json.loads(row["vault_summary_hashes"])
        assert "report" in hashes

    def test_second_call_is_idempotent(self, app_client):
        client, root, db_path = app_client
        roll_id = "abcdef1234567890abcdef1234567890"
        _setup_finalised_roll(db_path, roll_id, root)

        r1 = client.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r1.status_code == 200
        r2 = client.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r2.status_code == 200
        assert (root / "assets" / roll_id / "report.pdf").exists()

    def test_409_on_user_edited_report_section(self, app_client):
        client, root, db_path = app_client
        roll_id = "abcdef1234567890abcdef1234567890"
        _setup_finalised_roll(db_path, roll_id, root)

        r1 = client.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r1.status_code == 200

        # Simulate user hand-edit in Obsidian.
        md_files = list((root / "Roll Log").glob("*.md"))
        md_path = md_files[0]
        md_text = md_path.read_text(encoding="utf-8")
        assert "Match report PDF" in md_text
        md_path.write_text(md_text.replace("Match report PDF", "USER HAND EDIT"), encoding="utf-8")

        r2 = client.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r2.status_code == 409
        assert r2.headers.get("x-conflict") == "report"
        # PDF body still returned
        assert r2.content.startswith(b"%PDF-")
        # PDF file still written
        assert (root / "assets" / roll_id / "report.pdf").exists()
        # Markdown NOT overwritten
        assert "USER HAND EDIT" in md_path.read_text(encoding="utf-8")

    def test_overwrite_query_resolves_conflict(self, app_client):
        client, root, db_path = app_client
        roll_id = "abcdef1234567890abcdef1234567890"
        _setup_finalised_roll(db_path, roll_id, root)

        client.post(f"/api/rolls/{roll_id}/export-pdf")
        md_files = list((root / "Roll Log").glob("*.md"))
        md_path = md_files[0]
        md_path.write_text(
            md_path.read_text(encoding="utf-8").replace("Match report PDF", "USER EDIT"),
            encoding="utf-8",
        )

        r = client.post(f"/api/rolls/{roll_id}/export-pdf?overwrite=1")
        assert r.status_code == 200
        assert "Match report PDF" in md_path.read_text(encoding="utf-8")

    def test_502_when_weasyprint_raises(self, app_client, monkeypatch):
        client, root, db_path = app_client
        roll_id = "abcdef1234567890abcdef1234567890"
        _setup_finalised_roll(db_path, roll_id, root)

        def _boom(ctx):  # noqa: ARG001
            raise RuntimeError("synthetic weasyprint failure")

        monkeypatch.setattr("server.api.export_pdf.render_report_pdf", _boom)
        r = client.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r.status_code == 502
        # PDF file NOT written
        assert not (root / "assets" / roll_id / "report.pdf").exists()

    def test_filename_slugified(self, app_client):
        client, root, db_path = app_client
        roll_id = "abcdef1234567890abcdef1234567890"
        _setup_finalised_roll(db_path, roll_id, root)

        r = client.post(f"/api/rolls/{roll_id}/export-pdf")
        cd = r.headers["content-disposition"]
        assert "tuesday-roll-2026-04-21.pdf" in cd
