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


def test_rolls_has_player_a_b_description(tmp_path):
    """Freeform text columns used to feed Claude a visual-id hint per roll."""
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(rolls)")}
        assert "player_a_description" in cols
        assert "player_b_description" in cols
        assert cols["player_a_description"].upper() == "TEXT"
        assert cols["player_b_description"].upper() == "TEXT"
    finally:
        conn.close()


def test_create_roll_persists_player_descriptions(tmp_path):
    from server.db import create_roll, get_roll

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        create_roll(
            conn, id="r1", title="T", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=10.0,
            partner=None, result="unknown", created_at=1,
            player_a_name="Greig", player_b_name="Sam",
            player_a_description="navy gi, bald",
            player_b_description="white gi, long hair",
        )
        row = get_roll(conn, "r1")
        assert row["player_a_description"] == "navy gi, bald"
        assert row["player_b_description"] == "white gi, long hair"
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
