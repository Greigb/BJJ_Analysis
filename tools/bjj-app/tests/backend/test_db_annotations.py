"""Tests for insert_annotation / get_annotations_by_section / get_annotations_by_roll."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from server.db import (
    connect,
    create_roll,
    get_annotations_by_roll,
    get_annotations_by_section,
    init_db,
    insert_annotation,
    insert_section,
)


@pytest.fixture
def db_with_sections(tmp_path: Path):
    path = tmp_path / "test.db"
    init_db(path)
    conn = connect(path)
    create_roll(
        conn, id="roll-1", title="T", date="2026-04-21",
        video_path="assets/roll-1/source.mp4", duration_s=10.0,
        partner=None, result="unknown", created_at=int(time.time()),
    )
    s1 = insert_section(conn, roll_id="roll-1", start_s=3.0, end_s=5.0, sample_interval_s=1.0)
    s2 = insert_section(conn, roll_id="roll-1", start_s=7.0, end_s=9.0, sample_interval_s=1.0)
    try:
        yield conn, [s1["id"], s2["id"]]
    finally:
        conn.close()


def test_insert_annotation_persists_row(db_with_sections):
    conn, section_ids = db_with_sections
    row = insert_annotation(
        conn, section_id=section_ids[0], body="first note", created_at=1700000000
    )
    assert row["body"] == "first note"
    assert row["section_id"] == section_ids[0]
    assert row["created_at"] == 1700000000


def test_multiple_annotations_per_section_are_allowed(db_with_sections):
    conn, section_ids = db_with_sections
    insert_annotation(conn, section_id=section_ids[0], body="one", created_at=1)
    insert_annotation(conn, section_id=section_ids[0], body="two", created_at=2)
    rows = get_annotations_by_section(conn, section_ids[0])
    assert [r["body"] for r in rows] == ["one", "two"]


def test_get_annotations_by_section_orders_by_created_at(db_with_sections):
    conn, section_ids = db_with_sections
    insert_annotation(conn, section_id=section_ids[0], body="later", created_at=200)
    insert_annotation(conn, section_id=section_ids[0], body="earlier", created_at=100)
    rows = get_annotations_by_section(conn, section_ids[0])
    assert [r["body"] for r in rows] == ["earlier", "later"]


def test_get_annotations_by_roll_joins_section_timestamp(db_with_sections):
    conn, section_ids = db_with_sections
    # s1 spans 3.0-5.0, s2 spans 7.0-9.0
    insert_annotation(conn, section_id=section_ids[1], body="on s2", created_at=50)
    insert_annotation(conn, section_id=section_ids[0], body="on s1", created_at=60)
    rows = get_annotations_by_roll(conn, "roll-1")
    assert [(r["start_s"], r["end_s"], r["body"]) for r in rows] == [
        (3.0, 5.0, "on s1"),
        (7.0, 9.0, "on s2"),
    ]


def test_get_annotations_by_roll_returns_empty_for_roll_with_none(db_with_sections):
    conn, _ = db_with_sections
    assert get_annotations_by_roll(conn, "roll-1") == []


def test_annotations_cascade_delete_on_section_delete(db_with_sections):
    conn, section_ids = db_with_sections
    insert_annotation(conn, section_id=section_ids[0], body="x", created_at=1)
    conn.execute("DELETE FROM sections WHERE id = ?", (section_ids[0],))
    conn.commit()
    assert get_annotations_by_section(conn, section_ids[0]) == []
