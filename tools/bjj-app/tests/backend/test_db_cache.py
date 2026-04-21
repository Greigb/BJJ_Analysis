"""Tests for claude_cache helpers in server.db."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.db import cache_get, cache_put, connect, init_db


@pytest.fixture
def db(tmp_path: Path):
    path = tmp_path / "test.db"
    init_db(path)
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def test_cache_get_returns_none_for_unknown_key(db):
    assert cache_get(db, prompt_hash="p", frame_hash="f") is None


def test_cache_put_then_get_round_trip(db):
    payload = {"hello": "world", "n": 1}
    cache_put(db, prompt_hash="p", frame_hash="f", response=payload)
    assert cache_get(db, prompt_hash="p", frame_hash="f") == payload


def test_cache_put_is_idempotent_on_same_key(db):
    cache_put(db, prompt_hash="p", frame_hash="f", response={"a": 1})
    cache_put(db, prompt_hash="p", frame_hash="f", response={"a": 2})
    assert cache_get(db, prompt_hash="p", frame_hash="f") == {"a": 2}


def test_cache_distinguishes_by_both_hash_components(db):
    cache_put(db, prompt_hash="p1", frame_hash="f", response={"v": 1})
    cache_put(db, prompt_hash="p2", frame_hash="f", response={"v": 2})
    cache_put(db, prompt_hash="p1", frame_hash="g", response={"v": 3})

    assert cache_get(db, prompt_hash="p1", frame_hash="f") == {"v": 1}
    assert cache_get(db, prompt_hash="p2", frame_hash="f") == {"v": 2}
    assert cache_get(db, prompt_hash="p1", frame_hash="g") == {"v": 3}
