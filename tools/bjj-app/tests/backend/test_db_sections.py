"""Tests for M9 sections DB helpers."""
from __future__ import annotations

import sqlite3

import pytest

from server.db import (
    connect,
    create_roll,
    delete_section_and_moments,
    get_moments,
    get_sections_by_roll,
    init_db,
    insert_moments,
    insert_section,
)


def _make_roll(conn, roll_id: str = "r1") -> str:
    create_roll(
        conn,
        id=roll_id,
        title="Test",
        date="2026-04-22",
        video_path=f"assets/{roll_id}/source.mp4",
        duration_s=60.0,
        partner=None,
        result="unknown",
        created_at=1713700000,
        player_a_name="Player A",
        player_b_name="Player B",
    )
    return roll_id


def test_insert_section_returns_row_with_id(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        row = insert_section(
            conn, roll_id="r1", start_s=3.0, end_s=7.0, sample_interval_s=1.0
        )
        assert row["id"]
        assert row["roll_id"] == "r1"
        assert row["start_s"] == 3.0
        assert row["end_s"] == 7.0
        assert row["sample_interval_s"] == 1.0
        assert row["created_at"] > 0
    finally:
        conn.close()


def test_get_sections_by_roll_returns_ordered_by_start(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        insert_section(
            conn, roll_id="r1", start_s=10.0, end_s=14.0, sample_interval_s=1.0
        )
        insert_section(
            conn, roll_id="r1", start_s=3.0, end_s=7.0, sample_interval_s=0.5
        )
        rows = get_sections_by_roll(conn, roll_id="r1")
        assert len(rows) == 2
        assert rows[0]["start_s"] == 3.0
        assert rows[1]["start_s"] == 10.0
    finally:
        conn.close()


def test_get_sections_by_roll_empty(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        assert get_sections_by_roll(conn, roll_id="r1") == []
    finally:
        conn.close()


def test_delete_section_and_moments_removes_both(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        section_row = insert_section(
            conn, roll_id="r1", start_s=3.0, end_s=7.0, sample_interval_s=1.0
        )
        section_id = section_row["id"]
        insert_moments(
            conn,
            roll_id="r1",
            moments=[
                {"frame_idx": 0, "timestamp_s": 3.0, "pose_delta": None, "section_id": section_id},
                {"frame_idx": 1, "timestamp_s": 4.0, "pose_delta": None, "section_id": section_id},
            ],
        )
        assert len(get_moments(conn, "r1")) == 2

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        delete_section_and_moments(conn, section_id=section_id, frames_dir=frames_dir)

        assert get_sections_by_roll(conn, roll_id="r1") == []
        assert get_moments(conn, "r1") == []
    finally:
        conn.close()


def test_insert_moments_accepts_section_id(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        section_row = insert_section(
            conn, roll_id="r1", start_s=3.0, end_s=5.0, sample_interval_s=1.0
        )
        rows = insert_moments(
            conn,
            roll_id="r1",
            moments=[
                {
                    "frame_idx": 0,
                    "timestamp_s": 3.0,
                    "pose_delta": None,
                    "section_id": section_row["id"],
                },
            ],
        )
        assert rows[0]["section_id"] == section_row["id"]
    finally:
        conn.close()


def test_insert_moments_section_id_defaults_to_null(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        rows = insert_moments(
            conn,
            roll_id="r1",
            moments=[{"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": None}],
        )
        assert rows[0]["section_id"] is None
    finally:
        conn.close()


def test_unique_index_rejects_duplicate_frame_idx(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_moments(
                conn,
                roll_id="r1",
                moments=[
                    {"frame_idx": 5, "timestamp_s": 5.0, "pose_delta": None},
                    {"frame_idx": 5, "timestamp_s": 5.0, "pose_delta": None},
                ],
            )
    finally:
        conn.close()


def test_update_section_analysis_writes_narrative_and_tip(tmp_path):
    from server.db import (
        connect, create_roll, get_sections_by_roll, init_db,
        insert_section, update_section_analysis,
    )
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        create_roll(
            conn, id="r1", title="T", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=10.0,
            partner=None, result="unknown", created_at=1,
        )
        row = insert_section(conn, roll_id="r1", start_s=0.0, end_s=4.0, sample_interval_s=1.0)
        update_section_analysis(
            conn, section_id=row["id"],
            narrative="Player A recovers guard.",
            coach_tip="Keep elbows tight.",
            analysed_at=1713700000,
        )
        got = get_sections_by_roll(conn, "r1")[0]
        assert got["narrative"] == "Player A recovers guard."
        assert got["coach_tip"] == "Keep elbows tight."
        assert got["analysed_at"] == 1713700000
    finally:
        conn.close()


def test_delete_section_and_moments_removes_frame_files(tmp_path):
    from server.db import (
        connect, create_roll, delete_section_and_moments,
        get_moments, get_sections_by_roll, init_db, insert_moments, insert_section,
    )

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        create_roll(
            conn, id="r1", title="T", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=10.0,
            partner=None, result="unknown", created_at=1,
        )
        sec = insert_section(conn, roll_id="r1", start_s=0.0, end_s=2.0, sample_interval_s=1.0)
        inserted = insert_moments(conn, roll_id="r1", moments=[
            {"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": None, "section_id": sec["id"]},
            {"frame_idx": 1, "timestamp_s": 1.0, "pose_delta": None, "section_id": sec["id"]},
        ])
        assert len(inserted) == 2

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        f0 = frames_dir / "frame_000000.jpg"
        f1 = frames_dir / "frame_000001.jpg"
        f0.write_bytes(b"x")
        f1.write_bytes(b"y")

        delete_section_and_moments(conn, section_id=sec["id"], frames_dir=frames_dir)

        assert get_sections_by_roll(conn, "r1") == []
        assert get_moments(conn, "r1") == []
        assert not f0.exists()
        assert not f1.exists()
    finally:
        conn.close()


def test_delete_section_and_moments_tolerates_missing_frame_files(tmp_path):
    """Deleting a section whose frame files were already removed must not raise."""
    from server.db import (
        connect, create_roll, delete_section_and_moments,
        init_db, insert_moments, insert_section,
    )

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        create_roll(
            conn, id="r1", title="T", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=10.0,
            partner=None, result="unknown", created_at=1,
        )
        sec = insert_section(conn, roll_id="r1", start_s=0.0, end_s=1.0, sample_interval_s=1.0)
        insert_moments(conn, roll_id="r1", moments=[
            {"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": None, "section_id": sec["id"]},
        ])
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        # No file on disk at all — helper must still complete.
        delete_section_and_moments(conn, section_id=sec["id"], frames_dir=frames_dir)
    finally:
        conn.close()
