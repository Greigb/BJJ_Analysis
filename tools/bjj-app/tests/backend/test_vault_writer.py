"""Tests for vault_writer: render_your_notes, slugify_filename, publish."""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

import pytest

from server.analysis.vault_writer import render_your_notes


def _row(**kwargs):
    """Shim for tests: build a dict that quacks like sqlite3.Row for render_your_notes."""
    return kwargs


def test_render_your_notes_groups_by_moment_as_h3():
    rows = [
        _row(moment_id="m1", timestamp_s=83.0, body="flat; framed too late.", created_at=1710000000),
        _row(moment_id="m2", timestamp_s=165.0, body="good sweep.", created_at=1710000060),
    ]
    body = render_your_notes(rows)
    # Two H3 headers
    assert "### 1:23" in body
    assert "### 2:45" in body
    # The bullet bodies are present
    assert "flat; framed too late." in body
    assert "good sweep." in body


def test_render_your_notes_sorts_moments_by_timestamp_and_bullets_by_created_at():
    rows = [
        # Out-of-order intentionally — render must sort.
        _row(moment_id="m2", timestamp_s=10.0, body="A on m2 late", created_at=200),
        _row(moment_id="m1", timestamp_s=3.0,  body="C on m1 earliest", created_at=100),
        _row(moment_id="m1", timestamp_s=3.0,  body="D on m1 latest", created_at=300),
        _row(moment_id="m2", timestamp_s=10.0, body="B on m2 early", created_at=50),
    ]
    body = render_your_notes(rows)

    # m1 section (t=3) before m2 (t=10)
    m1_idx = body.index("### 0:03")
    m2_idx = body.index("### 0:10")
    assert m1_idx < m2_idx

    # Within m1: C before D
    c_idx = body.index("C on m1 earliest")
    d_idx = body.index("D on m1 latest")
    assert c_idx < d_idx

    # Within m2: B before A
    b_idx = body.index("B on m2 early")
    a_idx = body.index("A on m2 late")
    assert b_idx < a_idx


def test_render_your_notes_includes_readable_timestamp_stamp_on_each_bullet():
    # 1700000000 = 2023-11-14 22:13:20 UTC. Locale-independent, checks the
    # YYYY-MM-DD HH:MM prefix is present regardless of actual time.
    rows = [_row(moment_id="m1", timestamp_s=0.0, body="x", created_at=1700000000)]
    body = render_your_notes(rows)
    # Match _(YYYY-MM-DD HH:MM)_ anywhere in the body.
    assert re.search(r"_\(\d{4}-\d{2}-\d{2} \d{2}:\d{2}\)_", body)


def test_render_your_notes_returns_empty_string_for_no_rows():
    assert render_your_notes([]) == ""


def test_render_your_notes_formats_minute_colon_seconds_from_timestamp_s():
    # 125 seconds → "2:05"
    rows = [_row(moment_id="m1", timestamp_s=125.0, body="x", created_at=1)]
    body = render_your_notes(rows)
    assert "### 2:05" in body


def test_render_your_notes_is_deterministic_for_identical_input():
    rows = [
        _row(moment_id="m1", timestamp_s=1.0, body="note", created_at=1),
        _row(moment_id="m1", timestamp_s=1.0, body="note2", created_at=2),
    ]
    a = render_your_notes(rows)
    b = render_your_notes(rows)
    assert a == b
