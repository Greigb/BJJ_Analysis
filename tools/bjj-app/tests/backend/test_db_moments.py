import time
from pathlib import Path

import pytest

from server.db import connect, create_roll, get_moments, init_db, insert_moments


@pytest.fixture
def db_with_roll(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn,
        id="roll-1",
        title="T",
        date="2026-04-20",
        video_path="assets/roll-1/source.mp4",
        duration_s=10.0,
        partner=None,
        result="unknown",
        created_at=int(time.time()),
    )
    try:
        yield conn
    finally:
        conn.close()


def test_insert_moments_persists_rows(db_with_roll):
    inserted = insert_moments(
        db_with_roll,
        roll_id="roll-1",
        moments=[
            {"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": 0.5},
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
        ],
    )
    assert len(inserted) == 2
    for row in inserted:
        assert row["roll_id"] == "roll-1"
        assert row["selected_for_analysis"] == 0


def test_get_moments_returns_rows_in_timestamp_order(db_with_roll):
    insert_moments(
        db_with_roll,
        roll_id="roll-1",
        moments=[
            {"frame_idx": 10, "timestamp_s": 10.0, "pose_delta": 0.3},
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": 0.5},
        ],
    )

    rows = get_moments(db_with_roll, "roll-1")
    assert [r["timestamp_s"] for r in rows] == [0.0, 3.0, 10.0]


def test_get_moments_returns_empty_for_roll_with_no_moments(db_with_roll):
    assert get_moments(db_with_roll, "roll-1") == []


def test_insert_moments_replaces_previous_moments(db_with_roll):
    insert_moments(
        db_with_roll,
        roll_id="roll-1",
        moments=[{"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": 0.5}],
    )
    insert_moments(
        db_with_roll,
        roll_id="roll-1",
        moments=[{"frame_idx": 5, "timestamp_s": 5.0, "pose_delta": 1.0}],
    )

    rows = get_moments(db_with_roll, "roll-1")
    # Re-analysing a roll should replace, not append.
    assert len(rows) == 1
    assert rows[0]["frame_idx"] == 5
