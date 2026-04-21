"""Tests for M6b vault_writer.update_report_section."""
from __future__ import annotations

import sqlite3

import pytest

from server.analysis.vault_writer import (
    ConflictError,
    update_report_section,
)
from server.db import (
    connect,
    create_roll,
    init_db,
    set_summary_state,
    set_vault_state,
    set_vault_summary_hashes,
)


def _setup_roll(tmp_path, *, with_vault_file=True):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)

    roll_id = "abcdef1234567890abcdef1234567890"
    create_roll(
        conn,
        id=roll_id,
        title="Tuesday Roll",
        date="2026-04-21",
        video_path="assets/x/source.mp4",
        duration_s=245.0,
        partner=None,
        result="unknown",
        created_at=1713700000,
        player_a_name="Greig",
        player_b_name="Partner",
    )
    set_summary_state(
        conn,
        roll_id=roll_id,
        scores_payload={
            "summary": "s",
            "scores": {"position_control": 7, "submission_threat": 3, "defensive_resilience": 8},
            "top_improvements": ["a"],
            "strengths": ["b"],
            "key_moments": [],
        },
        finalised_at=1713700100,
    )

    vault_root = tmp_path / "vault"
    (vault_root / "Roll Log").mkdir(parents=True)
    vault_path = f"Roll Log/2026-04-21 - Tuesday Roll.md"

    if with_vault_file:
        (vault_root / vault_path).write_text(
            "---\ntitle: Tuesday Roll\n---\n\n"
            "## Summary\n\nsomething\n\n"
            "## Your Notes\n\n(none)\n",
            encoding="utf-8",
        )
        set_vault_state(
            conn,
            roll_id=roll_id,
            vault_path=vault_path,
            vault_your_notes_hash="abc",
            vault_published_at=1713700200,
        )
        set_vault_summary_hashes(conn, roll_id=roll_id, hashes={"summary": "h1"})

    return conn, roll_id, vault_root


def test_inserts_report_section_when_absent(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)

    new_hash = update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="[[assets/xxx/report.pdf|Match report PDF]]\n\n*Generated now*",
        force=False,
    )

    assert isinstance(new_hash, str) and len(new_hash) > 0
    text = (vault_root / "Roll Log" / "2026-04-21 - Tuesday Roll.md").read_text()
    # Report section appears after strengths order (or wherever ordered-insert lands it)
    assert "## Report" in text
    assert "Match report PDF" in text


def test_hash_persisted_to_vault_summary_hashes(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)
    new_hash = update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="[[assets/xxx/report.pdf|Match report PDF]]",
        force=False,
    )
    row = conn.execute(
        "SELECT vault_summary_hashes FROM rolls WHERE id = ?", (roll_id,)
    ).fetchone()
    import json
    stored = json.loads(row["vault_summary_hashes"])
    assert stored["report"] == new_hash


def test_replaces_existing_report_body(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)
    # First export — inserts.
    update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="first body",
        force=False,
    )
    # Second export — replaces.
    second_hash = update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="second body",
        force=False,
    )
    text = (vault_root / "Roll Log" / "2026-04-21 - Tuesday Roll.md").read_text()
    assert "second body" in text
    assert "first body" not in text


def test_raises_conflict_when_user_edited(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)
    update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="original",
        force=False,
    )
    vault_file = vault_root / "Roll Log" / "2026-04-21 - Tuesday Roll.md"
    text = vault_file.read_text()
    # Simulate user edit in Obsidian.
    vault_file.write_text(text.replace("original", "user hand edit"), encoding="utf-8")

    with pytest.raises(ConflictError):
        update_report_section(
            conn,
            roll_id=roll_id,
            vault_root=vault_root,
            body="new body",
            force=False,
        )


def test_force_overwrites_conflict(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)
    update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="original",
        force=False,
    )
    vault_file = vault_root / "Roll Log" / "2026-04-21 - Tuesday Roll.md"
    vault_file.write_text(
        vault_file.read_text().replace("original", "user edit"),
        encoding="utf-8",
    )

    update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="fresh body",
        force=True,
    )
    assert "fresh body" in vault_file.read_text()
    assert "user edit" not in vault_file.read_text()


def test_raises_when_vault_file_missing(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path, with_vault_file=False)
    with pytest.raises(FileNotFoundError):
        update_report_section(
            conn,
            roll_id=roll_id,
            vault_root=vault_root,
            body="body",
            force=False,
        )
