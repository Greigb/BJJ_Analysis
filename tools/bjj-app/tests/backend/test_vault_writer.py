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


# ---------- slugify_filename tests ----------


from server.analysis.vault_writer import slugify_filename  # noqa: E402


def test_slugify_filename_basic(tmp_path: Path):
    path = slugify_filename(title="Greig vs Anthony", date="2026-04-21", vault_root=tmp_path)
    assert path == tmp_path / "Roll Log" / "2026-04-21 - Greig vs Anthony.md"


def test_slugify_filename_strips_unsafe_characters(tmp_path: Path):
    # Slashes, colons, and quotes would be problematic in a filename.
    path = slugify_filename(
        title='Roll: "A vs B" / final',
        date="2026-04-21",
        vault_root=tmp_path,
    )
    name = path.name
    # No slashes, colons, or double-quotes in the name.
    for ch in ("/", ":", '"'):
        assert ch not in name
    # Still matches the template shape.
    assert name.startswith("2026-04-21 - ")
    assert name.endswith(".md")


def test_slugify_filename_appends_suffix_on_collision(tmp_path: Path):
    roll_log = tmp_path / "Roll Log"
    roll_log.mkdir()
    (roll_log / "2026-04-21 - Sparring.md").write_text("# existing")

    path = slugify_filename(title="Sparring", date="2026-04-21", vault_root=tmp_path)
    assert path.name == "2026-04-21 - Sparring (2).md"


def test_slugify_filename_appends_higher_suffix_when_2_is_also_taken(tmp_path: Path):
    roll_log = tmp_path / "Roll Log"
    roll_log.mkdir()
    (roll_log / "2026-04-21 - Sparring.md").write_text("x")
    (roll_log / "2026-04-21 - Sparring (2).md").write_text("x")

    path = slugify_filename(title="Sparring", date="2026-04-21", vault_root=tmp_path)
    assert path.name == "2026-04-21 - Sparring (3).md"


def test_slugify_filename_result_stays_under_roll_log(tmp_path: Path):
    # Security invariant: even if the title contains ../, the result must live under Roll Log/.
    path = slugify_filename(title="../evil", date="2026-04-21", vault_root=tmp_path)
    # Resolve to detect any traversal shenanigans.
    resolved = path.resolve()
    roll_log = (tmp_path / "Roll Log").resolve()
    # resolved must be under roll_log
    assert resolved.is_relative_to(roll_log)


# ---------- publish tests ----------


from server.analysis.vault_writer import ConflictError, publish  # noqa: E402
from server.db import (  # noqa: E402
    connect,
    create_roll,
    init_db,
    insert_annotation,
    insert_moments,
    get_vault_state,
)


@pytest.fixture
def db_roll_annotations(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn,
        id="r-1",
        title="Sample Roll",
        date="2026-04-21",
        video_path="assets/r-1/source.mp4",
        duration_s=225.0,
        partner="Anthony",
        result="unknown",
        created_at=1700000000,
    )
    moments = insert_moments(
        conn,
        roll_id="r-1",
        moments=[
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 10, "timestamp_s": 10.0, "pose_delta": 0.9},
        ],
    )
    insert_annotation(conn, moment_id=moments[0]["id"], body="first thought", created_at=1700000100)
    insert_annotation(conn, moment_id=moments[1]["id"], body="second thought", created_at=1700000200)
    try:
        yield conn, tmp_path
    finally:
        conn.close()


def test_publish_first_time_creates_file_with_frontmatter_title_and_your_notes(db_roll_annotations):
    conn, vault_root = db_roll_annotations

    result = publish(conn, roll_id="r-1", vault_root=vault_root)

    # File exists at returned path (under Roll Log/)
    full = vault_root / result.vault_path
    assert full.exists()
    assert full.parent.name == "Roll Log"

    text = full.read_text()
    # Frontmatter present with roll_id and tags
    assert text.startswith("---\n")
    assert "roll_id: r-1" in text
    assert "date: 2026-04-21" in text
    assert "partner: Anthony" in text
    assert "tags: [roll]" in text
    # Title + Your Notes
    assert "# Sample Roll" in text
    assert "## Your Notes" in text
    assert "first thought" in text
    assert "second thought" in text

    # DB state updated.
    state = get_vault_state(conn, "r-1")
    assert state["vault_path"] == result.vault_path
    assert state["vault_your_notes_hash"] == result.your_notes_hash
    assert state["vault_published_at"] == result.vault_published_at


def test_publish_second_time_splices_only_your_notes(db_roll_annotations):
    conn, vault_root = db_roll_annotations
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path

    # Simulate a user edit to a section OTHER than Your Notes.
    existing = full.read_text()
    existing += "\n## Overall Notes\n\nThis was a great roll.\n"
    full.write_text(existing)

    # Now add a new annotation and re-publish.
    moment_id = conn.execute(
        "SELECT id FROM moments WHERE roll_id = 'r-1' ORDER BY timestamp_s LIMIT 1"
    ).fetchone()["id"]
    insert_annotation(conn, moment_id=moment_id, body="follow-up thought", created_at=1700000300)

    second = publish(conn, roll_id="r-1", vault_root=vault_root)
    text_after = full.read_text()

    # New annotation in Your Notes
    assert "follow-up thought" in text_after
    # Unrelated section untouched
    assert "## Overall Notes" in text_after
    assert "This was a great roll." in text_after
    # Hash updated
    assert second.your_notes_hash != first.your_notes_hash


def test_publish_raises_conflict_when_your_notes_edited_externally(db_roll_annotations):
    conn, vault_root = db_roll_annotations
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path

    # Hand-edit Your Notes section (simulating Obsidian).
    text = full.read_text()
    text = text.replace("first thought", "first thought — edited in Obsidian")
    full.write_text(text)

    # Add a new annotation; re-publish without force → ConflictError.
    moment_id = conn.execute(
        "SELECT id FROM moments WHERE roll_id = 'r-1' ORDER BY timestamp_s LIMIT 1"
    ).fetchone()["id"]
    insert_annotation(conn, moment_id=moment_id, body="new", created_at=1700000400)

    with pytest.raises(ConflictError) as exc:
        publish(conn, roll_id="r-1", vault_root=vault_root)
    assert exc.value.current_hash != exc.value.stored_hash


def test_publish_force_overrides_conflict(db_roll_annotations):
    conn, vault_root = db_roll_annotations
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path

    # External edit.
    text = full.read_text()
    text = text.replace("first thought", "first thought — edited in Obsidian")
    full.write_text(text)

    moment_id = conn.execute(
        "SELECT id FROM moments WHERE roll_id = 'r-1' ORDER BY timestamp_s LIMIT 1"
    ).fetchone()["id"]
    insert_annotation(conn, moment_id=moment_id, body="forcey", created_at=1700000500)

    result = publish(conn, roll_id="r-1", vault_root=vault_root, force=True)
    text_after = full.read_text()
    # Force overwrites — external edit is gone.
    assert "edited in Obsidian" not in text_after
    # New annotation is present.
    assert "forcey" in text_after
    # Hash updated.
    assert result.your_notes_hash != first.your_notes_hash


def test_publish_recreates_when_file_was_deleted(db_roll_annotations):
    conn, vault_root = db_roll_annotations
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path
    # User deleted the file in Obsidian.
    full.unlink()
    assert not full.exists()

    result = publish(conn, roll_id="r-1", vault_root=vault_root)
    # Recreated at same path, new hash OK.
    assert (vault_root / result.vault_path).exists()
    assert result.vault_path == first.vault_path


def test_publish_writes_atomically_leaves_no_tmp_file_on_success(db_roll_annotations):
    conn, vault_root = db_roll_annotations
    publish(conn, roll_id="r-1", vault_root=vault_root)
    roll_log = vault_root / "Roll Log"
    tmp_files = list(roll_log.glob("*.tmp"))
    assert tmp_files == []


def test_publish_refuses_to_write_outside_roll_log(db_roll_annotations, monkeypatch):
    """Security: a malicious title that tries to traverse must be neutralised by slugify
    before publish gets it, so the write target always lies under Roll Log/."""
    conn, vault_root = db_roll_annotations
    # Update the roll's title to something adversarial.
    conn.execute("UPDATE rolls SET title = ? WHERE id = 'r-1'", ("../../../etc/evil",))
    conn.commit()

    result = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = (vault_root / result.vault_path).resolve()
    roll_log = (vault_root / "Roll Log").resolve()
    assert full.is_relative_to(roll_log)


def test_publish_raises_for_unknown_roll(db_roll_annotations):
    conn, vault_root = db_roll_annotations
    with pytest.raises(LookupError):
        publish(conn, roll_id="no-such-roll", vault_root=vault_root)
