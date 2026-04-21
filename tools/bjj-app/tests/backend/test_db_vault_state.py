"""Tests for set_vault_state / get_vault_state helpers."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from server.db import (
    connect,
    create_roll,
    get_vault_state,
    init_db,
    set_vault_state,
)


@pytest.fixture
def db_with_roll(tmp_path: Path):
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
    try:
        yield conn
    finally:
        conn.close()


def test_get_vault_state_returns_all_none_when_never_published(db_with_roll):
    state = get_vault_state(db_with_roll, "roll-1")
    assert state == {"vault_path": None, "vault_your_notes_hash": None, "vault_published_at": None}


def test_set_vault_state_then_get_round_trips(db_with_roll):
    set_vault_state(
        db_with_roll,
        roll_id="roll-1",
        vault_path="Roll Log/2026-04-21 - T.md",
        vault_your_notes_hash="abcd1234",
        vault_published_at=1700000000,
    )
    state = get_vault_state(db_with_roll, "roll-1")
    assert state == {
        "vault_path": "Roll Log/2026-04-21 - T.md",
        "vault_your_notes_hash": "abcd1234",
        "vault_published_at": 1700000000,
    }


def test_set_vault_state_overwrites_previous_values(db_with_roll):
    set_vault_state(
        db_with_roll,
        roll_id="roll-1",
        vault_path="Roll Log/old.md",
        vault_your_notes_hash="old",
        vault_published_at=100,
    )
    set_vault_state(
        db_with_roll,
        roll_id="roll-1",
        vault_path="Roll Log/new.md",
        vault_your_notes_hash="new",
        vault_published_at=200,
    )
    state = get_vault_state(db_with_roll, "roll-1")
    assert state["vault_path"] == "Roll Log/new.md"
    assert state["vault_your_notes_hash"] == "new"
    assert state["vault_published_at"] == 200


def test_get_vault_state_returns_none_for_unknown_roll(db_with_roll):
    assert get_vault_state(db_with_roll, "no-such-roll") is None
