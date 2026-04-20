"""Tests for insert_analyses / get_analyses helpers."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from server.db import (
    connect,
    create_roll,
    get_analyses,
    init_db,
    insert_analyses,
    insert_moments,
)


@pytest.fixture
def db_with_moment(tmp_path: Path):
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
        moments=[{"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2}],
    )
    moment_id = moments[0]["id"]
    try:
        yield conn, moment_id
    finally:
        conn.close()


def test_insert_analyses_persists_one_row_per_player(db_with_moment):
    conn, moment_id = db_with_moment
    rows = insert_analyses(
        conn,
        moment_id=moment_id,
        players=[
            {
                "player": "greig",
                "position_id": "closed_guard_bottom",
                "confidence": 0.8,
                "description": "Greig is in closed guard.",
                "coach_tip": "Break posture.",
            },
            {
                "player": "anthony",
                "position_id": "closed_guard_top",
                "confidence": 0.75,
                "description": None,
                "coach_tip": None,
            },
        ],
        claude_version="2.1.114",
    )
    assert len(rows) == 2
    players = sorted(r["player"] for r in rows)
    assert players == ["anthony", "greig"]


def test_get_analyses_returns_both_rows_for_a_moment(db_with_moment):
    conn, moment_id = db_with_moment
    insert_analyses(
        conn,
        moment_id=moment_id,
        players=[
            {
                "player": "greig", "position_id": "p1", "confidence": 1.0,
                "description": "x", "coach_tip": "y",
            },
            {
                "player": "anthony", "position_id": "p2", "confidence": 0.5,
                "description": None, "coach_tip": None,
            },
        ],
        claude_version="2.1.114",
    )
    fetched = get_analyses(conn, moment_id)
    assert len(fetched) == 2


def test_insert_analyses_replaces_previous_analyses_for_the_same_moment(db_with_moment):
    conn, moment_id = db_with_moment
    insert_analyses(
        conn,
        moment_id=moment_id,
        players=[
            {"player": "greig", "position_id": "old", "confidence": 0.3,
             "description": None, "coach_tip": None},
            {"player": "anthony", "position_id": "old2", "confidence": 0.3,
             "description": None, "coach_tip": None},
        ],
        claude_version="2.1.114",
    )
    insert_analyses(
        conn,
        moment_id=moment_id,
        players=[
            {"player": "greig", "position_id": "new", "confidence": 0.9,
             "description": "d", "coach_tip": "t"},
            {"player": "anthony", "position_id": "new2", "confidence": 0.85,
             "description": None, "coach_tip": None},
        ],
        claude_version="2.1.114",
    )
    rows = get_analyses(conn, moment_id)
    assert len(rows) == 2
    assert {r["position_id"] for r in rows} == {"new", "new2"}


def test_get_analyses_returns_empty_list_for_moment_with_none(db_with_moment):
    conn, moment_id = db_with_moment
    assert get_analyses(conn, moment_id) == []
