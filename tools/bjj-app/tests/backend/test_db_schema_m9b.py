"""M9b schema: sections narrative/coach_tip/analysed_at + annotations.section_id FK."""
from __future__ import annotations

from server.db import connect, init_db


def test_sections_has_narrative_coach_tip_analysed_at(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(sections)")}
        assert "narrative" in cols
        assert "coach_tip" in cols
        assert "analysed_at" in cols
        assert cols["narrative"].upper() == "TEXT"
        assert cols["coach_tip"].upper() == "TEXT"
        assert cols["analysed_at"].upper() == "INTEGER"
    finally:
        conn.close()


def test_annotations_uses_section_id_fk(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
        assert "section_id" in cols
        assert "moment_id" not in cols

        fks = list(conn.execute("PRAGMA foreign_key_list(annotations)"))
        assert any(fk[2] == "sections" for fk in fks), (
            "annotations should reference sections"
        )
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path):
    """Running init_db twice must not raise or duplicate data."""
    db = tmp_path / "db.sqlite"
    init_db(db)
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sections)")}
        assert "narrative" in cols
        cols_an = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
        assert "section_id" in cols_an
    finally:
        conn.close()


def test_migration_drops_pre_m9b_annotation_rows(tmp_path):
    """Pre-M9b annotations (moment_id FK) are smoke-test-only — dropped on migration."""
    import sqlite3

    db = tmp_path / "db.sqlite"
    # First init creates the table at the current schema.
    init_db(db)
    conn = sqlite3.connect(db)
    # Force the table back to pre-M9b shape so we can seed a legacy row.
    conn.execute("DROP TABLE annotations")
    conn.execute(
        "CREATE TABLE annotations ("
        "  id TEXT PRIMARY KEY, moment_id TEXT NOT NULL, "
        "  body TEXT NOT NULL, created_at INTEGER NOT NULL, "
        "  updated_at INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO annotations VALUES ('a1', 'm1', 'legacy', 1, 1)"
    )
    conn.commit()
    conn.close()

    # Re-run init_db — migration should rebuild the table.
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
        assert "section_id" in cols and "moment_id" not in cols
        n = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        assert n == 0
    finally:
        conn.close()
