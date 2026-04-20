import time
from pathlib import Path

import pytest

from server.db import connect, create_roll, get_roll, init_db


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def test_create_roll_inserts_and_returns_row(db):
    now = int(time.time())
    row = create_roll(
        db,
        id="roll-1",
        title="Test roll",
        date="2026-04-20",
        video_path="assets/roll-1/source.mp4",
        duration_s=123.4,
        partner="Anthony",
        result="unknown",
        created_at=now,
    )

    assert row["id"] == "roll-1"
    assert row["title"] == "Test roll"
    assert row["duration_s"] == 123.4
    assert row["result"] == "unknown"
    assert row["created_at"] == now


def test_get_roll_returns_inserted_row(db):
    now = int(time.time())
    create_roll(
        db,
        id="roll-2",
        title="Another",
        date="2026-04-20",
        video_path="assets/roll-2/source.mp4",
        duration_s=60.0,
        partner=None,
        result="unknown",
        created_at=now,
    )

    row = get_roll(db, "roll-2")
    assert row is not None
    assert row["id"] == "roll-2"
    assert row["partner"] is None


def test_get_roll_returns_none_for_unknown_id(db):
    assert get_roll(db, "does-not-exist") is None
