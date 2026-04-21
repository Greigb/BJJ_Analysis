"""Tests for insert_annotation / get_annotations_by_moment / get_annotations_by_roll."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from server.db import (
    connect,
    create_roll,
    get_annotations_by_moment,
    get_annotations_by_roll,
    init_db,
    insert_annotation,
    insert_moments,
)


@pytest.fixture
def db_with_moments(tmp_path: Path):
    path = tmp_path / "test.db"
    init_db(path)
    conn = connect(path)
    create_roll(
        conn,
        id="roll-1",
        title="T",
        date="2026-04-21",
        video_path="assets/roll-1/source.mp4",
        duration_s=10.0,
        partner=None,
        result="unknown",
        created_at=int(time.time()),
    )
    moments = insert_moments(
        conn,
        roll_id="roll-1",
        moments=[
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 7, "timestamp_s": 7.0, "pose_delta": 0.8},
        ],
    )
    try:
        yield conn, [m["id"] for m in moments]
    finally:
        conn.close()


def test_insert_annotation_persists_row(db_with_moments):
    conn, moment_ids = db_with_moments
    row = insert_annotation(
        conn, moment_id=moment_ids[0], body="first note", created_at=1700000000
    )
    assert row["body"] == "first note"
    assert row["moment_id"] == moment_ids[0]
    assert row["created_at"] == 1700000000


def test_multiple_annotations_per_moment_are_allowed(db_with_moments):
    conn, moment_ids = db_with_moments
    insert_annotation(conn, moment_id=moment_ids[0], body="one", created_at=1)
    insert_annotation(conn, moment_id=moment_ids[0], body="two", created_at=2)
    rows = get_annotations_by_moment(conn, moment_ids[0])
    assert [r["body"] for r in rows] == ["one", "two"]


def test_get_annotations_by_moment_orders_by_created_at(db_with_moments):
    conn, moment_ids = db_with_moments
    insert_annotation(conn, moment_id=moment_ids[0], body="later", created_at=200)
    insert_annotation(conn, moment_id=moment_ids[0], body="earlier", created_at=100)
    rows = get_annotations_by_moment(conn, moment_ids[0])
    assert [r["body"] for r in rows] == ["earlier", "later"]


def test_get_annotations_by_moment_returns_empty_for_moment_with_none(db_with_moments):
    conn, moment_ids = db_with_moments
    assert get_annotations_by_moment(conn, moment_ids[0]) == []


def test_get_annotations_by_roll_joins_moment_timestamp(db_with_moments):
    conn, moment_ids = db_with_moments
    insert_annotation(conn, moment_id=moment_ids[1], body="on m2", created_at=50)
    insert_annotation(conn, moment_id=moment_ids[0], body="on m1", created_at=60)
    rows = get_annotations_by_roll(conn, "roll-1")
    # Ordered by timestamp_s asc, then created_at asc — so m1 (t=3) comes before m2 (t=7).
    assert [(r["timestamp_s"], r["body"]) for r in rows] == [
        (3.0, "on m1"),
        (7.0, "on m2"),
    ]


def test_get_annotations_by_roll_returns_empty_for_roll_with_none(db_with_moments):
    conn, _ = db_with_moments
    assert get_annotations_by_roll(conn, "roll-1") == []


def test_annotations_cascade_delete_on_moment_delete(db_with_moments):
    conn, moment_ids = db_with_moments
    insert_annotation(conn, moment_id=moment_ids[0], body="x", created_at=1)
    conn.execute("DELETE FROM moments WHERE id = ?", (moment_ids[0],))
    conn.commit()
    assert get_annotations_by_moment(conn, moment_ids[0]) == []
