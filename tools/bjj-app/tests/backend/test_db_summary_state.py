"""Tests for set_summary_state / set_vault_summary_hashes helpers."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from server.db import (
    connect,
    create_roll,
    init_db,
    set_summary_state,
    set_vault_summary_hashes,
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


def test_set_summary_state_persists_scores_json_and_finalised_at(db_with_roll):
    payload = {
        "summary": "Tight roll.",
        "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["a", "b", "c"],
        "strengths": ["x"],
        "key_moments": [],
    }
    set_summary_state(
        db_with_roll,
        roll_id="roll-1",
        scores_payload=payload,
        finalised_at=1714579500,
    )
    row = db_with_roll.execute(
        "SELECT scores_json, finalised_at FROM rolls WHERE id = ?", ("roll-1",)
    ).fetchone()
    assert row["finalised_at"] == 1714579500
    assert json.loads(row["scores_json"]) == payload


def test_set_summary_state_overwrites_previous(db_with_roll):
    set_summary_state(
        db_with_roll,
        roll_id="roll-1",
        scores_payload={"summary": "first"},
        finalised_at=100,
    )
    set_summary_state(
        db_with_roll,
        roll_id="roll-1",
        scores_payload={"summary": "second"},
        finalised_at=200,
    )
    row = db_with_roll.execute(
        "SELECT scores_json, finalised_at FROM rolls WHERE id = ?", ("roll-1",)
    ).fetchone()
    assert json.loads(row["scores_json"])["summary"] == "second"
    assert row["finalised_at"] == 200


def test_set_vault_summary_hashes_round_trips(db_with_roll):
    hashes = {"summary": "abc", "scores": "def", "key_moments": "ghi"}
    set_vault_summary_hashes(db_with_roll, roll_id="roll-1", hashes=hashes)
    row = db_with_roll.execute(
        "SELECT vault_summary_hashes FROM rolls WHERE id = ?", ("roll-1",)
    ).fetchone()
    assert json.loads(row["vault_summary_hashes"]) == hashes


def test_set_vault_summary_hashes_accepts_none_for_unfinalised_rolls(db_with_roll):
    # First set, then clear.
    set_vault_summary_hashes(db_with_roll, roll_id="roll-1", hashes={"summary": "abc"})
    set_vault_summary_hashes(db_with_roll, roll_id="roll-1", hashes=None)
    row = db_with_roll.execute(
        "SELECT vault_summary_hashes FROM rolls WHERE id = ?", ("roll-1",)
    ).fetchone()
    assert row["vault_summary_hashes"] is None
