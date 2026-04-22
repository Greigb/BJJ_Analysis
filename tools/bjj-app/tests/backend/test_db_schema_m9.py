"""Verify M9 schema: sections table, moments.section_id column, unique index."""
from __future__ import annotations

from server.db import connect, init_db


def test_sections_table_exists(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sections'"
        ).fetchone()
        assert row is not None, "sections table missing"

        cols = {r[1] for r in conn.execute("PRAGMA table_info(sections)")}
        assert {
            "id",
            "roll_id",
            "start_s",
            "end_s",
            "sample_interval_s",
            "created_at",
        } <= cols
    finally:
        conn.close()


def test_moments_has_section_id(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(moments)")}
        assert "section_id" in cols
    finally:
        conn.close()


def test_unique_index_on_roll_frame(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    try:
        idx_names = {
            r[1] for r in conn.execute("PRAGMA index_list(moments)")
        }
        assert "idx_moments_roll_frame" in idx_names
        # Verify it is UNIQUE.
        row = conn.execute(
            "SELECT \"unique\" FROM pragma_index_list('moments') "
            "WHERE name = 'idx_moments_roll_frame'"
        ).fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    # Second call must not error and must not duplicate anything.
    init_db(db_path)
    conn = connect(db_path)
    try:
        idx_names = [
            r[1] for r in conn.execute("PRAGMA index_list(moments)")
        ]
        assert idx_names.count("idx_moments_roll_frame") == 1
    finally:
        conn.close()
