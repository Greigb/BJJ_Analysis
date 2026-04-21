"""Tests for the M4/M5 schema migration (vault + player name columns on rolls table)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from server.db import connect, init_db


def _rolls_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("PRAGMA table_info(rolls)")
        return {row[1] for row in cur.fetchall()}


def test_init_db_fresh_includes_vault_columns(tmp_path: Path):
    db_path = tmp_path / "fresh.db"
    init_db(db_path)
    cols = _rolls_columns(db_path)
    assert "vault_path" in cols
    assert "vault_your_notes_hash" in cols
    assert "vault_published_at" in cols


def test_init_db_migrates_pre_m4_schema(tmp_path: Path):
    """A database created before M4 (no vault_* columns) gets them added."""
    db_path = tmp_path / "premigrate.db"
    with sqlite3.connect(db_path) as conn:
        # Minimal pre-M4 rolls table — just the columns that existed before M4.
        conn.executescript(
            """
            CREATE TABLE rolls (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                video_path TEXT NOT NULL,
                duration_s REAL,
                partner TEXT,
                result TEXT,
                scores_json TEXT,
                finalised_at INTEGER,
                created_at INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO rolls (id, title, date, video_path, created_at) "
            "VALUES ('r1', 't', '2026-01-01', 'v.mp4', 1)"
        )
        conn.commit()

    # Should not raise; should add the columns to the existing rolls table.
    init_db(db_path)

    cols = _rolls_columns(db_path)
    assert "vault_path" in cols
    assert "vault_your_notes_hash" in cols
    assert "vault_published_at" in cols

    # Existing row is untouched, new columns are NULL.
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, vault_path, vault_your_notes_hash, vault_published_at "
            "FROM rolls WHERE id = 'r1'"
        ).fetchone()
    finally:
        conn.close()
    assert row["id"] == "r1"
    assert row["vault_path"] is None
    assert row["vault_your_notes_hash"] is None
    assert row["vault_published_at"] is None


def test_init_db_is_idempotent(tmp_path: Path):
    """Running init_db twice must not raise (no duplicate ALTER)."""
    db_path = tmp_path / "idem.db"
    init_db(db_path)
    init_db(db_path)  # must not raise
    cols = _rolls_columns(db_path)
    assert "vault_path" in cols


def test_init_db_fresh_includes_player_name_columns(tmp_path: Path):
    db_path = tmp_path / "fresh.db"
    init_db(db_path)
    cols = _rolls_columns(db_path)
    assert "player_a_name" in cols
    assert "player_b_name" in cols


def test_init_db_migrates_analyses_player_enum(tmp_path: Path):
    """Rows with analyses.player in ('greig','anthony') get renamed to ('a','b')."""
    db_path = tmp_path / "enum.db"
    # Build a minimal pre-migration database and insert legacy rows.
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO rolls (id, title, date, video_path, created_at, "
            "player_a_name, player_b_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("r1", "t", "2026-01-01", "v.mp4", 1, "Greig", "Anthony"),
        )
        conn.execute(
            "INSERT INTO moments (id, roll_id, frame_idx, timestamp_s) "
            "VALUES (?, ?, ?, ?)",
            ("m1", "r1", 0, 0.0),
        )
        conn.execute(
            "INSERT INTO analyses (id, moment_id, player, position_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("a1", "m1", "greig", "pos1", 1),
        )
        conn.execute(
            "INSERT INTO analyses (id, moment_id, player, position_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("a2", "m1", "anthony", "pos2", 1),
        )
        conn.commit()

    # Re-run init_db — the migration should rename.
    init_db(db_path)

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, player FROM analyses ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert [(r["id"], r["player"]) for r in rows] == [("a1", "a"), ("a2", "b")]
