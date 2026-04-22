# BJJ App M9 — User-Picked Sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the auto pose-pre-pass with explicit user-picked time-range sections, persisted as first-class DB records, with per-section frame-density control (1s / 0.5s / 2s). Each picked range produces moments at the requested interval; Claude classifies on chip-click as today.

**Architecture:** New `sections` table + nullable `moments.section_id` FK (with a unique `(roll_id, frame_idx)` index as a safety net against overlaps). Backend rewrites `pipeline.run_section_analysis` to extract frames for only the picked ranges and persist section rows inside the same transaction as their moments. MediaPipe pose-pre-pass code and dep are deleted. Frontend gets a new `SectionPicker.svelte` with Mark-start/Mark-end buttons driven by the existing `<video>` element; the review page swaps its Analyse button for the picker.

**Tech Stack:** Python 3.12 + FastAPI + SQLite (existing); OpenCV for frame seeking (no MediaPipe); SvelteKit + TypeScript + Svelte 5 runes on the frontend; vitest + @testing-library/svelte for frontend tests.

---

## File structure

**New files (backend):**
- `tools/bjj-app/server/analysis/sections.py` — pure helper `build_sample_timestamps`.
- `tools/bjj-app/tests/backend/test_sections.py` — unit tests for `build_sample_timestamps` and `extract_frames_at_timestamps`.
- `tools/bjj-app/tests/backend/test_db_schema_m9.py` — schema migration tests.
- `tools/bjj-app/tests/backend/test_db_sections.py` — tests for DB helpers.
- `tools/bjj-app/tests/backend/test_api_analyse_sections.py` — endpoint integration tests (replaces `test_api_analyse.py`).

**New files (frontend):**
- `tools/bjj-app/web/src/lib/components/SectionPicker.svelte`
- `tools/bjj-app/web/tests/section-picker.test.ts`

**Modified files (backend):**
- `tools/bjj-app/server/db.py` — add `sections` DDL, migration helper, DB helpers.
- `tools/bjj-app/server/analysis/frames.py` — add `extract_frames_at_timestamps`; remove the old fps-based `extract_frames`.
- `tools/bjj-app/server/analysis/pipeline.py` — rewrite as `run_section_analysis`.
- `tools/bjj-app/server/api/analyse.py` — accept `sections` body, validate, call new pipeline.
- `tools/bjj-app/server/api/rolls.py` — add `sections` to `RollDetailOut`; add `section_id` to `MomentOut`.
- `tools/bjj-app/pyproject.toml` — drop `mediapipe`.
- `tools/bjj-app/README.md` — M9 subsection.

**Modified files (frontend):**
- `tools/bjj-app/web/src/lib/types.ts` — `Section` type; extend `RollDetail` and `Moment`.
- `tools/bjj-app/web/src/lib/api.ts` — `analyseRoll(id, sections)` signature change.
- `tools/bjj-app/web/src/routes/review/[id]/+page.svelte` — swap header Analyse button for the picker.
- `tools/bjj-app/web/tests/review-analyse.test.ts` — rewrite SSE mocks (no pose stage).

**Deleted files (backend):**
- `tools/bjj-app/server/analysis/pose.py`
- Any `tools/bjj-app/tests/backend/test_pose.py` (check before deleting).
- `tools/bjj-app/tests/backend/test_api_analyse.py` (replaced by `test_api_analyse_sections.py`).

---

## Task 1: DB schema — `sections` table + `moments.section_id` + unique index

**Files:**
- Modify: `tools/bjj-app/server/db.py`
- Create: `tools/bjj-app/tests/backend/test_db_schema_m9.py`

- [ ] **Step 1: Write the failing schema test**

Create `tools/bjj-app/tests/backend/test_db_schema_m9.py`:

```python
"""Verify M9 schema: sections table, moments.section_id column, unique index."""
from __future__ import annotations

from server.db import connect, init_db


def test_sections_table_exists(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sections'"
        ).fetchone()
        assert row is not None, "sections table missing"

        cols = {r[1] for r in conn.execute("PRAGMA table_info(sections)")}
        assert {
            "id",
            "roll_id",
            "start_s",
            "end_s",
            "sample_interval_s",
            "created_at",
        } <= cols
    finally:
        conn.close()


def test_moments_has_section_id(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(moments)")}
        assert "section_id" in cols
    finally:
        conn.close()


def test_unique_index_on_roll_frame(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)
    try:
        idx_names = {
            r[1] for r in conn.execute("PRAGMA index_list(moments)")
        }
        assert "idx_moments_roll_frame" in idx_names
        # Verify it is UNIQUE.
        row = conn.execute(
            "SELECT \"unique\" FROM pragma_index_list('moments') "
            "WHERE name = 'idx_moments_roll_frame'"
        ).fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    # Second call must not error and must not duplicate anything.
    init_db(db_path)
    conn = connect(db_path)
    try:
        idx_names = [
            r[1] for r in conn.execute("PRAGMA index_list(moments)")
        ]
        assert idx_names.count("idx_moments_roll_frame") == 1
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_db_schema_m9.py -v
```

Expected: 4 failures — all about missing `sections` table / missing `section_id` column / missing index.

- [ ] **Step 3: Extend `SCHEMA_SQL` and add the M9 migration**

Edit `tools/bjj-app/server/db.py`. Append to `SCHEMA_SQL` (before the closing `"""`):

```python
"""
CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    roll_id TEXT NOT NULL REFERENCES rolls(id) ON DELETE CASCADE,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    sample_interval_s REAL NOT NULL,
    created_at INTEGER NOT NULL
);
"""
```

So the full `SCHEMA_SQL` now ends with the `sections` CREATE TABLE before the triple-quote close.

Then add the migration helper below `_backfill_default_player_names`:

```python
def _migrate_moments_m9(conn: sqlite3.Connection) -> None:
    """Idempotently add M9 fields to moments + create the unique index.

    - Adds `section_id` column if missing.
    - Creates `idx_moments_roll_frame` UNIQUE on (roll_id, frame_idx) if missing.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(moments)").fetchall()}
    if "section_id" not in existing:
        conn.execute(
            "ALTER TABLE moments ADD COLUMN section_id TEXT "
            "REFERENCES sections(id) ON DELETE SET NULL"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_moments_roll_frame ON moments(roll_id, frame_idx)"
    )
```

Wire it into `init_db` (line ~123):

```python
def init_db(db_path: Path) -> None:
    """Create the schema if it doesn't already exist. Safe to call every startup."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_rolls_m4(conn)
        _backfill_default_player_names(conn)
        _migrate_analyses_player_enum(conn)
        _migrate_moments_m9(conn)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_db_schema_m9.py -v
```

Expected: 4/4 passing.

- [ ] **Step 5: Run full backend suite to confirm no regressions**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend -q
```

Expected: same pre-M9 count of passes + 4 new passes; no new failures.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_schema_m9.py
git commit -m "feat(bjj-app): add M9 schema — sections table + moments.section_id + unique index"
```

---

## Task 2: DB helpers — `insert_section`, `get_sections_by_roll`, `delete_section_and_moments`, extended `insert_moments`

**Files:**
- Modify: `tools/bjj-app/server/db.py`
- Create: `tools/bjj-app/tests/backend/test_db_sections.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/tests/backend/test_db_sections.py`:

```python
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

        delete_section_and_moments(conn, section_id=section_id)

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
        insert_moments(
            conn,
            roll_id="r1",
            moments=[{"frame_idx": 5, "timestamp_s": 5.0, "pose_delta": None}],
        )
        with pytest.raises(sqlite3.IntegrityError):
            insert_moments(
                conn,
                roll_id="r1",
                moments=[{"frame_idx": 5, "timestamp_s": 5.0, "pose_delta": None}],
            )
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_db_sections.py -v
```

Expected: ImportError — `insert_section`, `get_sections_by_roll`, `delete_section_and_moments` don't exist yet.

- [ ] **Step 3: Implement the helpers**

Edit `tools/bjj-app/server/db.py`. Locate `insert_moments` (around line 179) and replace its body so it accepts `section_id` per moment dict and writes it:

```python
def insert_moments(
    conn,
    *,
    roll_id: str,
    moments: list[dict],
) -> list[sqlite3.Row]:
    """Replace all moments for `roll_id` with the supplied list.

    Each moment dict must contain: frame_idx (int), timestamp_s (float),
    pose_delta (float or None), and may include section_id (str or None).
    Returns the newly inserted rows in insertion order.
    """
    conn.execute("DELETE FROM moments WHERE roll_id = ?", (roll_id,))
    inserted_ids: list[str] = []
    for m in moments:
        moment_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO moments (
                id, roll_id, frame_idx, timestamp_s, pose_delta,
                selected_for_analysis, section_id
            )
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                moment_id,
                roll_id,
                int(m["frame_idx"]),
                float(m["timestamp_s"]),
                None if m.get("pose_delta") is None else float(m["pose_delta"]),
                m.get("section_id"),
            ),
        )
        inserted_ids.append(moment_id)
    conn.commit()

    if not inserted_ids:
        return []

    cur = conn.execute(
        f"SELECT * FROM moments WHERE id IN ({','.join('?' * len(inserted_ids))})",
        inserted_ids,
    )
    rows_by_id = {r["id"]: r for r in cur.fetchall()}
    return [rows_by_id[i] for i in inserted_ids]
```

Append three new helpers at the bottom of `db.py`:

```python
def insert_section(
    conn,
    *,
    roll_id: str,
    start_s: float,
    end_s: float,
    sample_interval_s: float,
) -> sqlite3.Row:
    """Insert one section. Returns the full row."""
    section_id = uuid.uuid4().hex
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO sections (
            id, roll_id, start_s, end_s, sample_interval_s, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (section_id, roll_id, float(start_s), float(end_s), float(sample_interval_s), now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    return row


def get_sections_by_roll(conn, roll_id: str) -> list[sqlite3.Row]:
    """Return all sections for a roll, ordered by start_s ascending."""
    cur = conn.execute(
        "SELECT * FROM sections WHERE roll_id = ? ORDER BY start_s ASC, created_at ASC",
        (roll_id,),
    )
    return cur.fetchall()


def delete_section_and_moments(conn, *, section_id: str) -> None:
    """Delete a section and all its moments in one transaction."""
    conn.execute("DELETE FROM moments WHERE section_id = ?", (section_id,))
    conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_db_sections.py -v
```

Expected: 7/7 passing.

- [ ] **Step 5: Run full backend suite**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend -q
```

Expected: all prior passing tests still pass + 7 new; no regressions.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_sections.py
git commit -m "feat(bjj-app): add M9 sections DB helpers + extend insert_moments with section_id"
```

---

## Task 3: Pure helper — `build_sample_timestamps`

**Files:**
- Create: `tools/bjj-app/server/analysis/sections.py`
- Create: `tools/bjj-app/tests/backend/test_sections.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/tests/backend/test_sections.py`:

```python
"""Unit tests for M9 sections pure helpers."""
from __future__ import annotations

import pytest

from server.analysis.sections import build_sample_timestamps


class TestBuildSampleTimestamps:
    def test_simple_1s_interval(self):
        assert build_sample_timestamps(0.0, 4.0, 1.0) == [0.0, 1.0, 2.0, 3.0]

    def test_excludes_end_s(self):
        # end_s is EXCLUSIVE — 4.0 is not part of the list for start=0, end=4, step=1
        result = build_sample_timestamps(0.0, 4.0, 1.0)
        assert 4.0 not in result

    def test_includes_start_s(self):
        result = build_sample_timestamps(3.0, 7.0, 1.0)
        assert result[0] == 3.0

    def test_half_second_interval(self):
        assert build_sample_timestamps(0.0, 2.0, 0.5) == [0.0, 0.5, 1.0, 1.5]

    def test_two_second_interval(self):
        assert build_sample_timestamps(0.0, 10.0, 2.0) == [0.0, 2.0, 4.0, 6.0, 8.0]

    def test_empty_when_start_equals_end(self):
        assert build_sample_timestamps(3.0, 3.0, 1.0) == []

    def test_single_point_when_interval_exceeds_range(self):
        # interval 2.0 > range 1.5 → only start_s is emitted
        assert build_sample_timestamps(3.0, 4.5, 2.0) == [3.0]

    def test_rounds_to_millisecond(self):
        # Guard against floating-point drift: each value rounded to 3 decimal places
        result = build_sample_timestamps(0.0, 1.0, 0.1)
        assert result == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

    def test_raises_when_start_negative(self):
        with pytest.raises(ValueError, match="start_s"):
            build_sample_timestamps(-1.0, 3.0, 1.0)

    def test_raises_when_end_less_than_start(self):
        with pytest.raises(ValueError, match="end_s"):
            build_sample_timestamps(5.0, 3.0, 1.0)

    def test_raises_when_interval_not_positive(self):
        with pytest.raises(ValueError, match="interval_s"):
            build_sample_timestamps(0.0, 3.0, 0.0)
        with pytest.raises(ValueError, match="interval_s"):
            build_sample_timestamps(0.0, 3.0, -1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_sections.py -v
```

Expected: ModuleNotFoundError — `server.analysis.sections` doesn't exist.

- [ ] **Step 3: Implement the helper**

Create `tools/bjj-app/server/analysis/sections.py`:

```python
"""M9 pure helpers for user-picked section timestamp generation.

Deterministic, no IO. Tests hit these directly; the pipeline consumes
them in `run_section_analysis`.
"""
from __future__ import annotations


def build_sample_timestamps(
    start_s: float,
    end_s: float,
    interval_s: float,
) -> list[float]:
    """Return timestamps in [start_s, end_s) stepped by interval_s.

    Inclusive at start_s, strictly less than end_s. Values are rounded to
    3 decimal places to avoid floating-point drift across section boundaries.

    Raises ValueError for invalid input: negative start, end < start, or
    interval <= 0.
    """
    if start_s < 0:
        raise ValueError(f"start_s must be >= 0, got {start_s}")
    if end_s < start_s:
        raise ValueError(f"end_s ({end_s}) must be >= start_s ({start_s})")
    if interval_s <= 0:
        raise ValueError(f"interval_s must be > 0, got {interval_s}")

    out: list[float] = []
    # Use integer step counter to avoid accumulating float error.
    n = 0
    while True:
        t = round(start_s + n * interval_s, 3)
        if t >= end_s:
            break
        out.append(t)
        n += 1
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_sections.py -v
```

Expected: 11/11 passing.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/analysis/sections.py tools/bjj-app/tests/backend/test_sections.py
git commit -m "feat(bjj-app): add build_sample_timestamps pure helper for M9"
```

---

## Task 4: `extract_frames_at_timestamps` in `frames.py`

**Files:**
- Modify: `tools/bjj-app/server/analysis/frames.py`
- Modify: `tools/bjj-app/tests/backend/test_sections.py`

- [ ] **Step 1: Append failing tests**

Append to `tools/bjj-app/tests/backend/test_sections.py`:

```python
from pathlib import Path

from server.analysis.frames import extract_frames_at_timestamps


def _short_video_path() -> Path:
    # The repo ships a short fixture at tests/backend/fixtures/short_video.mp4
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


class TestExtractFramesAtTimestamps:
    def test_writes_one_file_per_timestamp(self, tmp_path):
        video = _short_video_path()
        paths = extract_frames_at_timestamps(
            video, timestamps=[0.0, 0.5, 1.0], out_dir=tmp_path
        )
        assert len(paths) == 3
        for p in paths:
            assert p.exists()
            assert p.suffix == ".jpg"

    def test_sequential_filenames_starting_at_zero(self, tmp_path):
        video = _short_video_path()
        paths = extract_frames_at_timestamps(
            video, timestamps=[0.0, 0.5, 1.0], out_dir=tmp_path
        )
        assert paths[0].name == "frame_000000.jpg"
        assert paths[1].name == "frame_000001.jpg"
        assert paths[2].name == "frame_000002.jpg"

    def test_start_index_offsets_filenames(self, tmp_path):
        video = _short_video_path()
        paths = extract_frames_at_timestamps(
            video, timestamps=[0.0, 0.5], out_dir=tmp_path, start_index=10
        )
        assert paths[0].name == "frame_000010.jpg"
        assert paths[1].name == "frame_000011.jpg"

    def test_empty_timestamps_returns_empty(self, tmp_path):
        video = _short_video_path()
        paths = extract_frames_at_timestamps(
            video, timestamps=[], out_dir=tmp_path
        )
        assert paths == []

    def test_out_dir_created_if_missing(self, tmp_path):
        video = _short_video_path()
        nested = tmp_path / "a" / "b" / "c"
        paths = extract_frames_at_timestamps(
            video, timestamps=[0.0], out_dir=nested
        )
        assert nested.is_dir()
        assert paths[0].exists()

    def test_missing_video_raises(self, tmp_path):
        import pytest as _pytest
        with _pytest.raises(FileNotFoundError):
            extract_frames_at_timestamps(
                tmp_path / "nope.mp4", timestamps=[0.0], out_dir=tmp_path
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_sections.py -v
```

Expected: the 6 new tests fail — `extract_frames_at_timestamps` doesn't exist.

- [ ] **Step 3: Implement `extract_frames_at_timestamps`; remove old `extract_frames`**

Rewrite `tools/bjj-app/server/analysis/frames.py`:

```python
"""OpenCV frame extraction for uploaded videos.

After M9 this module exposes only `extract_frames_at_timestamps` — the
old whole-video fps-sampling `extract_frames` is gone since the pose
pre-pass was retired.
"""
from __future__ import annotations

from pathlib import Path

import cv2


def extract_frames_at_timestamps(
    video_path: Path,
    timestamps: list[float],
    out_dir: Path,
    start_index: int = 0,
) -> list[Path]:
    """Write one JPEG frame per requested timestamp (seconds) to out_dir.

    Files are named `frame_NNNNNN.jpg` with NNNNNN = start_index,
    start_index+1, ... in request order. `timestamps` is consumed in order;
    the caller is responsible for sorting or deduping if that matters.

    Raises:
        FileNotFoundError: if video_path does not exist.
        ValueError: if the video can't be opened.
    """
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    if not timestamps:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Not a readable video: {video_path}")

        paths: list[Path] = []
        for i, ts in enumerate(timestamps):
            # POS_MSEC is more reliable than POS_FRAMES for fractional seconds
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
            ok, image = cap.read()
            if not ok:
                raise ValueError(
                    f"Could not read frame at timestamp {ts}s from {video_path}"
                )
            path = out_dir / f"frame_{start_index + i:06d}.jpg"
            cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 85])
            paths.append(path)

        return paths
    finally:
        cap.release()
```

- [ ] **Step 4: Run the frames tests**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_sections.py -v
```

Expected: all 17 tests pass (11 timestamp + 6 extract).

- [ ] **Step 5: Ensure old `extract_frames` has no callers**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && grep -rn "extract_frames[^_]" server tests
```

Expected: only import lines inside `server/analysis/pipeline.py` still reference the old symbol. Task 5 replaces that import. Don't panic if pipeline.py fails to import — it'll be rewritten next.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/analysis/frames.py tools/bjj-app/tests/backend/test_sections.py
git commit -m "feat(bjj-app): replace extract_frames with extract_frames_at_timestamps (M9)"
```

---

## Task 5: Rewrite `pipeline.run_section_analysis`

**Files:**
- Modify: `tools/bjj-app/server/analysis/pipeline.py`
- Create: `tools/bjj-app/tests/backend/test_pipeline_sections.py`

- [ ] **Step 1: Write the failing integration test**

Create `tools/bjj-app/tests/backend/test_pipeline_sections.py`:

```python
"""Integration test for M9 section-based pipeline."""
from __future__ import annotations

from pathlib import Path

from server.analysis.pipeline import run_section_analysis
from server.db import connect, create_roll, get_sections_by_roll, init_db


def _short_video_path() -> Path:
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


def _make_roll(conn) -> None:
    create_roll(
        conn,
        id="r1",
        title="Test",
        date="2026-04-22",
        video_path="assets/r1/source.mp4",
        duration_s=2.0,
        partner=None,
        result="unknown",
        created_at=1713700000,
        player_a_name="Player A",
        player_b_name="Player B",
    )


def test_run_section_analysis_emits_frames_and_done(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        frames_dir = tmp_path / "frames"

        events = list(
            run_section_analysis(
                conn=conn,
                roll_id="r1",
                video_path=_short_video_path(),
                frames_dir=frames_dir,
                sections=[
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0},
                ],
                duration_s=2.0,
            )
        )

        # At least one "frames" event and exactly one terminal "done" event.
        stages = [e["stage"] for e in events]
        assert "frames" in stages
        assert stages[-1] == "done"

        done = events[-1]
        assert done["total"] == 1  # one timestamp at 0.0
        assert len(done["moments"]) == 1
        assert done["moments"][0]["section_id"]
    finally:
        conn.close()


def test_run_section_analysis_persists_sections_row(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        frames_dir = tmp_path / "frames"

        list(
            run_section_analysis(
                conn=conn,
                roll_id="r1",
                video_path=_short_video_path(),
                frames_dir=frames_dir,
                sections=[
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0},
                    {"start_s": 1.0, "end_s": 2.0, "sample_interval_s": 0.5},
                ],
                duration_s=2.0,
            )
        )

        sections = get_sections_by_roll(conn, "r1")
        assert len(sections) == 2
        assert sections[0]["start_s"] == 0.0
        assert sections[1]["start_s"] == 1.0
        assert sections[1]["sample_interval_s"] == 0.5
    finally:
        conn.close()


def test_run_section_analysis_dedupes_overlapping_timestamps(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        frames_dir = tmp_path / "frames"

        events = list(
            run_section_analysis(
                conn=conn,
                roll_id="r1",
                video_path=_short_video_path(),
                frames_dir=frames_dir,
                sections=[
                    {"start_s": 0.0, "end_s": 1.5, "sample_interval_s": 1.0},   # 0, 1
                    {"start_s": 1.0, "end_s": 2.0, "sample_interval_s": 1.0},   # 1 (dup), 
                ],
                duration_s=2.0,
            )
        )

        done = events[-1]
        timestamps = sorted({m["timestamp_s"] for m in done["moments"]})
        assert timestamps == [0.0, 1.0]  # 1.0 deduped
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_pipeline_sections.py -v
```

Expected: ImportError — `run_section_analysis` doesn't exist (and the old `run_analysis` imports `PoseDetector`/`pose_delta` which will soon be gone).

- [ ] **Step 3: Rewrite `pipeline.py`**

Replace the entire contents of `tools/bjj-app/server/analysis/pipeline.py`:

```python
"""M9 section-based analysis pipeline.

Takes a list of user-picked sections, extracts frames at each section's
requested interval, persists sections + moments in one transaction, and
yields SSE-shaped events the caller feeds into a StreamingResponse.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from server.analysis.frames import extract_frames_at_timestamps
from server.analysis.sections import build_sample_timestamps
from server.db import insert_moments, insert_section


def run_section_analysis(
    *,
    conn,
    roll_id: str,
    video_path: Path,
    frames_dir: Path,
    sections: list[dict],
    duration_s: float,
) -> Iterator[dict]:
    """Extract frames for each section, persist rows, yield progress events.

    Events:
        {"stage": "frames", "pct": 0..100}
        {"stage": "done", "total": int, "moments": [...]}

    Each moment dict in the done event has `id`, `frame_idx`, `timestamp_s`,
    and `section_id`.

    Sections are validated by the caller (api/analyse.py) — this function
    trusts the input shape.
    """
    # Insert section rows first so moments can reference them.
    section_rows = [
        insert_section(
            conn,
            roll_id=roll_id,
            start_s=s["start_s"],
            end_s=s["end_s"],
            sample_interval_s=s["sample_interval_s"],
        )
        for s in sections
    ]

    # Build a flat list of (timestamp, section_id), dedup by timestamp
    # (first-wins), sort ascending.
    pairs: dict[float, str] = {}
    for section_row, section_in in zip(section_rows, sections):
        for t in build_sample_timestamps(
            section_in["start_s"],
            section_in["end_s"],
            section_in["sample_interval_s"],
        ):
            pairs.setdefault(t, section_row["id"])

    ordered: list[tuple[float, str]] = sorted(pairs.items(), key=lambda x: x[0])
    timestamps = [p[0] for p in ordered]
    section_ids = [p[1] for p in ordered]

    yield {"stage": "frames", "pct": 0}

    # Extract frames. Progress events yielded in chunks of ~10%.
    total = len(timestamps)
    if total > 0:
        frame_paths = extract_frames_at_timestamps(
            video_path, timestamps=timestamps, out_dir=frames_dir
        )
    else:
        frame_paths = []
    yield {"stage": "frames", "pct": 100, "total": total}

    moment_inputs = [
        {
            "frame_idx": i,
            "timestamp_s": timestamps[i],
            "pose_delta": None,
            "section_id": section_ids[i],
        }
        for i in range(total)
    ]
    inserted_rows = insert_moments(conn, roll_id=roll_id, moments=moment_inputs)

    yield {
        "stage": "done",
        "total": len(inserted_rows),
        "moments": [
            {
                "id": r["id"],
                "frame_idx": r["frame_idx"],
                "timestamp_s": r["timestamp_s"],
                "section_id": r["section_id"],
            }
            for r in inserted_rows
        ],
    }
```

- [ ] **Step 4: Run the pipeline tests**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_pipeline_sections.py -v
```

Expected: 3/3 passing.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/analysis/pipeline.py tools/bjj-app/tests/backend/test_pipeline_sections.py
git commit -m "feat(bjj-app): replace pose pre-pass with section-based pipeline (M9)"
```

---

## Task 6: Rewrite API endpoint — `POST /api/rolls/:id/analyse`

**Files:**
- Modify: `tools/bjj-app/server/api/analyse.py`
- Create: `tools/bjj-app/tests/backend/test_api_analyse_sections.py`

- [ ] **Step 1: Write the failing endpoint tests**

Create `tools/bjj-app/tests/backend/test_api_analyse_sections.py`:

```python
"""Integration tests for POST /api/rolls/:id/analyse (M9 sections)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _short_video_path() -> Path:
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))
    (tmp_path / "Roll Log").mkdir()
    (tmp_path / "assets").mkdir()
    # Minimal taxonomy so create_app doesn't error.
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "taxonomy.json").write_text(json.dumps({
        "events": {}, "categories": {}, "positions": [], "valid_transitions": [],
    }))

    from server.main import create_app
    from server.db import connect, create_roll, init_db

    init_db(tmp_path / "test.db")
    roll_id = "r1"
    # Copy the short-video fixture into place so the endpoint can seek it.
    import shutil
    roll_dir = tmp_path / "assets" / roll_id
    roll_dir.mkdir()
    shutil.copy(_short_video_path(), roll_dir / "source.mp4")

    conn = connect(tmp_path / "test.db")
    try:
        create_roll(
            conn,
            id=roll_id,
            title="Fixture",
            date="2026-04-22",
            video_path=f"assets/{roll_id}/source.mp4",
            duration_s=2.0,
            partner=None,
            result="unknown",
            created_at=1713700000,
            player_a_name="Player A",
            player_b_name="Player B",
        )
    finally:
        conn.close()

    app = create_app()
    with TestClient(app) as c:
        yield c, tmp_path, roll_id


class TestAnalyseSectionsEndpoint:
    def test_400_when_sections_missing(self, app_client):
        client, _, roll_id = app_client
        r = client.post(f"/api/rolls/{roll_id}/analyse", json={})
        assert r.status_code == 400

    def test_400_when_sections_empty(self, app_client):
        client, _, roll_id = app_client
        r = client.post(f"/api/rolls/{roll_id}/analyse", json={"sections": []})
        assert r.status_code == 400

    def test_400_when_end_before_start(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={
                "sections": [
                    {"start_s": 2.0, "end_s": 1.0, "sample_interval_s": 1.0}
                ]
            },
        )
        assert r.status_code == 400

    def test_400_when_end_exceeds_duration(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={
                "sections": [
                    {"start_s": 0.0, "end_s": 999.0, "sample_interval_s": 1.0}
                ]
            },
        )
        assert r.status_code == 400

    def test_400_when_interval_not_allowed(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={
                "sections": [
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 0.25}
                ]
            },
        )
        assert r.status_code == 400

    def test_404_when_roll_missing(self, app_client):
        client, _, _ = app_client
        r = client.post(
            "/api/rolls/no-such-roll/analyse",
            json={
                "sections": [
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0}
                ]
            },
        )
        assert r.status_code == 404

    def test_happy_path_streams_events_and_persists(self, app_client):
        client, root, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={
                "sections": [
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0},
                ]
            },
        )
        assert r.status_code == 200
        body = r.text
        assert "stage" in body
        assert "\"done\"" in body

        # DB has a section + moment
        from server.db import connect, get_moments, get_sections_by_roll
        conn = connect(root / "test.db")
        try:
            assert len(get_sections_by_roll(conn, roll_id)) == 1
            assert len(get_moments(conn, roll_id)) == 1
        finally:
            conn.close()

        # Frame on disk
        assert (root / "assets" / roll_id / "frames" / "frame_000000.jpg").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_api_analyse_sections.py -v
```

Expected: many failures — old endpoint returns 422 or 200 on empty body, behaviour doesn't match new contract.

- [ ] **Step 3: Rewrite `analyse.py`**

Replace `tools/bjj-app/server/api/analyse.py`:

```python
"""POST /api/rolls/:id/analyse — SSE stream of the M9 section-based pipeline."""
from __future__ import annotations

import json
import logging
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.analysis.pipeline import run_section_analysis
from server.config import Settings, load_settings
from server.db import connect, get_roll

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analyse"])

_ALLOWED_INTERVALS = {0.5, 1.0, 2.0}
# Small slop to absorb fps/duration rounding in uploaded videos.
_DURATION_EPSILON = 0.5


class _SectionIn(BaseModel):
    start_s: float = Field(..., ge=0)
    end_s: float = Field(..., ge=0)
    sample_interval_s: float


class _AnalyseIn(BaseModel):
    sections: list[_SectionIn] = Field(..., min_length=1)


@router.post("/rolls/{roll_id}/analyse")
def analyse_roll(
    roll_id: str,
    payload: _AnalyseIn,
    settings: Settings = Depends(load_settings),
) -> StreamingResponse:
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
        )

    duration_s = float(row["duration_s"] or 0.0)

    # Validate each section.
    for idx, s in enumerate(payload.sections):
        if s.end_s <= s.start_s:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Section {idx}: end_s must be > start_s",
            )
        if s.end_s > duration_s + _DURATION_EPSILON:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Section {idx}: end_s ({s.end_s}) exceeds roll "
                    f"duration ({duration_s})"
                ),
            )
        if s.sample_interval_s not in _ALLOWED_INTERVALS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Section {idx}: sample_interval_s must be one of "
                    f"{sorted(_ALLOWED_INTERVALS)}"
                ),
            )

    video_path = settings.project_root / row["video_path"]
    frames_dir = settings.project_root / "assets" / roll_id / "frames"
    sections_payload = [s.model_dump() for s in payload.sections]

    def event_stream() -> Iterator[bytes]:
        conn2 = connect(settings.db_path)
        try:
            for event in run_section_analysis(
                conn=conn2,
                roll_id=roll_id,
                video_path=video_path,
                frames_dir=frames_dir,
                sections=sections_payload,
                duration_s=duration_s,
            ):
                yield f"data: {json.dumps(event)}\n\n".encode("utf-8")
        except Exception:
            logger.exception("Analyse pipeline failed for %s", roll_id)
            yield b'data: {"stage":"done","total":0,"moments":[]}\n\n'
        finally:
            conn2.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Delete the old test file**

```bash
rm tools/bjj-app/tests/backend/test_api_analyse.py
```

- [ ] **Step 5: Run the endpoint tests**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_api_analyse_sections.py -v
```

Expected: 7/7 passing.

- [ ] **Step 6: Run full backend suite**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend -q
```

Expected: all green. If any test fails because it imports `run_analysis` or `PoseDetector`, flag it — Task 7 deletes those.

- [ ] **Step 7: Commit**

```bash
git add tools/bjj-app/server/api/analyse.py tools/bjj-app/tests/backend/test_api_analyse_sections.py
git rm tools/bjj-app/tests/backend/test_api_analyse.py
git commit -m "feat(bjj-app): rewrite POST /analyse for M9 section body"
```

---

## Task 7: Delete MediaPipe dep + pose module

**Files:**
- Delete: `tools/bjj-app/server/analysis/pose.py`
- Modify: `tools/bjj-app/pyproject.toml`

- [ ] **Step 1: Confirm no callers of `pose.py` remain**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && grep -rn "from server.analysis.pose\|import pose\b\|PoseDetector\|pose_delta" server tests
```

Expected: no matches. If any appear in test files, they're leftovers — delete those tests.

- [ ] **Step 2: Delete `server/analysis/pose.py`**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis && git rm tools/bjj-app/server/analysis/pose.py
```

If `tools/bjj-app/tests/backend/test_pose.py` exists:

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis && git rm tools/bjj-app/tests/backend/test_pose.py
```

- [ ] **Step 3: Remove `mediapipe` from `pyproject.toml`**

Edit `tools/bjj-app/pyproject.toml`. Remove the line `"mediapipe>=0.10.18",` from the `dependencies` list. Resulting list:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "aiofiles>=24.1.0",
    "python-frontmatter>=1.1.0",
    "python-multipart>=0.0.12",
    "pydantic>=2.9.0",
    "opencv-python-headless>=4.10.0",
    "Pillow>=10.4.0",
    "weasyprint>=62.0",
    "jinja2>=3.1.0",
]
```

- [ ] **Step 4: Refresh the venv**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/pip install -e .
```

Expected: installs complete; `mediapipe` is marked as no longer required but the wheel stays cached (that's fine).

Optional (cleans up disk): `.venv/bin/pip uninstall -y mediapipe`.

- [ ] **Step 5: Run full backend suite**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend -q
```

Expected: all green, no import errors.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/pyproject.toml
git commit -m "chore(bjj-app): drop mediapipe dep + delete pose module (M9)"
```

---

## Task 8: Expose sections via `GET /api/rolls/:id`

**Files:**
- Modify: `tools/bjj-app/server/api/rolls.py`
- Modify: `tools/bjj-app/tests/backend/test_rolls_api.py` (or append to an existing rolls test file)

- [ ] **Step 1: Write failing test**

Append to the rolls API test file. If none exists, create `tools/bjj-app/tests/backend/test_rolls_sections.py`:

```python
"""Test that GET /api/rolls/:id returns sections."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))
    (tmp_path / "Roll Log").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "taxonomy.json").write_text(json.dumps({
        "events": {}, "categories": {}, "positions": [], "valid_transitions": [],
    }))

    from server.db import connect, create_roll, init_db, insert_section
    init_db(tmp_path / "test.db")
    conn = connect(tmp_path / "test.db")
    try:
        create_roll(
            conn,
            id="r1",
            title="Fixture",
            date="2026-04-22",
            video_path="assets/r1/source.mp4",
            duration_s=60.0,
            partner=None,
            result="unknown",
            created_at=1713700000,
            player_a_name="Player A",
            player_b_name="Player B",
        )
        insert_section(conn, roll_id="r1", start_s=3.0, end_s=7.0, sample_interval_s=1.0)
        insert_section(conn, roll_id="r1", start_s=10.0, end_s=14.0, sample_interval_s=0.5)
    finally:
        conn.close()

    from server.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_roll_detail_includes_sections(app_client):
    r = app_client.get("/api/rolls/r1")
    assert r.status_code == 200
    body = r.json()
    assert "sections" in body
    assert len(body["sections"]) == 2
    assert body["sections"][0]["start_s"] == 3.0
    assert body["sections"][0]["sample_interval_s"] == 1.0
    assert body["sections"][1]["start_s"] == 10.0
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_rolls_sections.py -v
```

Expected: fails — `sections` key missing from response.

- [ ] **Step 3: Extend `RollDetailOut`**

Edit `tools/bjj-app/server/api/rolls.py`. Add a `SectionOut` model and extend `RollDetailOut` and `MomentOut`:

```python
class SectionOut(BaseModel):
    id: str
    start_s: float
    end_s: float
    sample_interval_s: float


class MomentOut(BaseModel):
    id: str
    frame_idx: int
    timestamp_s: float
    pose_delta: float | None
    section_id: str | None = None
    analyses: list[AnalysisOut] = []
    annotations: list[AnnotationOut] = []


class RollDetailOut(BaseModel):
    """Full roll shape used by POST /api/rolls response and GET /api/rolls/:id."""

    id: str
    title: str
    date: str
    partner: str | None
    duration_s: float | None
    result: str
    video_url: str
    vault_path: str | None = None
    vault_published_at: int | None = None
    player_a_name: str = "Player A"
    player_b_name: str = "Player B"
    finalised_at: int | None = None
    scores: dict | None = None
    distribution: dict | None = None
    moments: list[MomentOut] = []
    sections: list[SectionOut] = []
```

In the `get_roll_detail` handler, load sections and populate them. Add near the top of the handler (after `row` is fetched and before returning `RollDetailOut(...)`):

```python
from server.db import get_sections_by_roll
section_rows = get_sections_by_roll(conn, roll_id)
sections_out = [
    SectionOut(
        id=s["id"],
        start_s=s["start_s"],
        end_s=s["end_s"],
        sample_interval_s=s["sample_interval_s"],
    )
    for s in section_rows
]
```

Pass `sections=sections_out` to the final `RollDetailOut(...)` constructor. Also update the `MomentOut` constructions in the handler to pass `section_id=m["section_id"]`.

The `POST /api/rolls` handler also returns `RollDetailOut`; pass `sections=[]` there explicitly for newly-created rolls.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_rolls_sections.py -v
```

Expected: test passes.

- [ ] **Step 5: Run full backend suite**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/api/rolls.py tools/bjj-app/tests/backend/test_rolls_sections.py
git commit -m "feat(bjj-app): expose sections + moment.section_id in RollDetail response"
```

---

## Task 9: Frontend types + API client

**Files:**
- Modify: `tools/bjj-app/web/src/lib/types.ts`
- Modify: `tools/bjj-app/web/src/lib/api.ts`

- [ ] **Step 1: Add the `Section` type**

Edit `tools/bjj-app/web/src/lib/types.ts`. Find the `Moment` interface and add `section_id`; find `RollDetail` and add `sections`. Add a new `Section` interface:

```typescript
export interface Section {
  id: string;
  start_s: number;
  end_s: number;
  sample_interval_s: number;
}
```

Inside the existing `Moment` interface, add:

```typescript
  section_id: string | null;
```

Inside the existing `RollDetail` interface, add:

```typescript
  sections: Section[];
```

- [ ] **Step 2: Update `analyseRoll` in `api.ts`**

Edit `tools/bjj-app/web/src/lib/api.ts`. Locate the current `analyseRoll` function (returns an SSE `Response`). Change its signature and body:

```typescript
export interface SectionInput {
  start_s: number;
  end_s: number;
  sample_interval_s: number;
}

export async function analyseRoll(
  rollId: string,
  sections: SectionInput[],
): Promise<Response> {
  return fetch(`/api/rolls/${encodeURIComponent(rollId)}/analyse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sections }),
  });
}
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web && npm run check 2>&1 | tail -20
```

Expected: new errors flagged in `+page.svelte` (Task 12 fixes them) but no errors in `api.ts` or `types.ts` themselves.

- [ ] **Step 4: Commit**

```bash
git add tools/bjj-app/web/src/lib/types.ts tools/bjj-app/web/src/lib/api.ts
git commit -m "feat(bjj-app): add Section type + sections-body analyseRoll signature"
```

---

## Task 10: `SectionPicker.svelte` — failing component tests

**Files:**
- Create: `tools/bjj-app/web/tests/section-picker.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/web/tests/section-picker.test.ts`:

```typescript
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import SectionPicker from '../src/lib/components/SectionPicker.svelte';

function makeVideoEl(currentTime = 0, duration = 60) {
  const el: any = document.createElement('video');
  Object.defineProperty(el, 'currentTime', {
    writable: true,
    value: currentTime,
  });
  Object.defineProperty(el, 'duration', {
    writable: true,
    value: duration,
  });
  return el as HTMLVideoElement;
}

describe('SectionPicker', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the Mark start button', () => {
    const video = makeVideoEl(0, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });
    expect(screen.getByRole('button', { name: /mark start/i })).toBeInTheDocument();
  });

  it('Mark end is disabled until Mark start has been pressed', async () => {
    const video = makeVideoEl(0, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });
    const end = screen.getByRole('button', { name: /mark end/i });
    expect(end).toBeDisabled();
  });

  it('pressing Mark start then Mark end commits a new chip', async () => {
    const user = userEvent.setup();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });

    await user.click(screen.getByRole('button', { name: /mark start/i }));
    // Move the playhead to 7.
    (video as any).currentTime = 7;
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    await waitFor(() => {
      expect(screen.getByText(/0:03/)).toBeInTheDocument();
      expect(screen.getByText(/0:07/)).toBeInTheDocument();
    });
  });

  it('Cancel resets the pending start without committing', async () => {
    const user = userEvent.setup();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });

    await user.click(screen.getByRole('button', { name: /mark start/i }));
    await user.click(screen.getByRole('button', { name: /cancel/i }));

    expect(screen.getByRole('button', { name: /mark end/i })).toBeDisabled();
  });

  it('delete button removes a chip', async () => {
    const user = userEvent.setup();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });

    await user.click(screen.getByRole('button', { name: /mark start/i }));
    (video as any).currentTime = 5;
    await user.click(screen.getByRole('button', { name: /mark end/i }));
    expect(screen.getByText(/0:03/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /delete/i }));
    expect(screen.queryByText(/0:03/)).not.toBeInTheDocument();
  });

  it('density dropdown changes sample_interval_s', async () => {
    const user = userEvent.setup();
    const onAnalyse = vi.fn();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse, busy: false },
    });

    await user.click(screen.getByRole('button', { name: /mark start/i }));
    (video as any).currentTime = 5;
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    const dropdown = screen.getByRole('combobox', { name: /density/i });
    await user.selectOptions(dropdown, '0.5');

    await user.click(screen.getByRole('button', { name: /analyse ranges/i }));
    expect(onAnalyse).toHaveBeenCalledWith([
      expect.objectContaining({ sample_interval_s: 0.5 }),
    ]);
  });

  it('Analyse ranges is disabled when no sections', () => {
    const video = makeVideoEl(0, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });
    const btn = screen.getByRole('button', { name: /analyse ranges/i });
    expect(btn).toBeDisabled();
  });

  it('Analyse ranges is disabled while busy', async () => {
    const user = userEvent.setup();
    const video = makeVideoEl(3, 60);
    const { rerender } = render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: false },
    });
    await user.click(screen.getByRole('button', { name: /mark start/i }));
    (video as any).currentTime = 5;
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    await rerender({ videoEl: video, durationS: 60, onAnalyse: vi.fn(), busy: true });

    expect(screen.getByRole('button', { name: /analyse ranges/i })).toBeDisabled();
  });

  it('editing mm:ss input updates the section timestamps', async () => {
    const user = userEvent.setup();
    const onAnalyse = vi.fn();
    const video = makeVideoEl(3, 60);
    render(SectionPicker, {
      props: { videoEl: video, durationS: 60, onAnalyse, busy: false },
    });
    await user.click(screen.getByRole('button', { name: /mark start/i }));
    (video as any).currentTime = 5;
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    const startInput = screen.getByLabelText(/section start/i) as HTMLInputElement;
    await user.clear(startInput);
    await user.type(startInput, '0:02');
    startInput.blur();

    await user.click(screen.getByRole('button', { name: /analyse ranges/i }));
    expect(onAnalyse).toHaveBeenCalledWith([
      expect.objectContaining({ start_s: 2.0, end_s: 5.0 }),
    ]);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web && npx vitest run tests/section-picker.test.ts
```

Expected: all 9 fail — component doesn't exist.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tools/bjj-app/web/tests/section-picker.test.ts
git commit -m "test(bjj-app): add SectionPicker tests (failing — no impl)"
```

---

## Task 11: `SectionPicker.svelte` implementation

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/SectionPicker.svelte`

- [ ] **Step 1: Implement the component**

Create `tools/bjj-app/web/src/lib/components/SectionPicker.svelte`:

```svelte
<script lang="ts">
  import type { SectionInput } from '$lib/api';

  interface StagedSection {
    id: string;
    start_s: number;
    end_s: number;
    sample_interval_s: number;
  }

  let {
    videoEl,
    durationS,
    onAnalyse,
    busy,
  }: {
    videoEl: HTMLVideoElement | undefined;
    durationS: number;
    onAnalyse: (sections: SectionInput[]) => void;
    busy: boolean;
  } = $props();

  let sections = $state<StagedSection[]>([]);
  let pendingStart = $state<number | null>(null);

  function formatMmSs(s: number): string {
    const total = Math.max(0, Math.floor(s));
    const m = Math.floor(total / 60);
    const sec = total % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  }

  function parseMmSs(value: string): number | null {
    const match = value.trim().match(/^(\d+):([0-5]?\d)$/);
    if (!match) return null;
    return parseInt(match[1], 10) * 60 + parseInt(match[2], 10);
  }

  function currentT(): number {
    return videoEl ? videoEl.currentTime : 0;
  }

  function onMarkStart() {
    if (!videoEl) return;
    pendingStart = currentT();
  }

  function onMarkEnd() {
    if (pendingStart === null || !videoEl) return;
    const start = pendingStart;
    const end = currentT();
    if (end <= start) return;
    sections = [
      ...sections,
      {
        id: crypto.randomUUID(),
        start_s: Math.round(start * 10) / 10,
        end_s: Math.round(end * 10) / 10,
        sample_interval_s: 1.0,
      },
    ];
    pendingStart = null;
  }

  function onCancel() {
    pendingStart = null;
  }

  function onDelete(id: string) {
    sections = sections.filter((s) => s.id !== id);
  }

  function onEditStart(id: string, value: string) {
    const parsed = parseMmSs(value);
    if (parsed === null) return;
    sections = sections.map((s) => (s.id === id ? { ...s, start_s: parsed } : s));
  }

  function onEditEnd(id: string, value: string) {
    const parsed = parseMmSs(value);
    if (parsed === null) return;
    sections = sections.map((s) => (s.id === id ? { ...s, end_s: parsed } : s));
  }

  function onDensityChange(id: string, value: string) {
    const interval = parseFloat(value);
    sections = sections.map((s) =>
      s.id === id ? { ...s, sample_interval_s: interval } : s,
    );
  }

  function onSeek(start_s: number) {
    if (videoEl) {
      videoEl.currentTime = start_s;
      void videoEl.play();
    }
  }

  function onAnalyseClick() {
    if (busy || sections.length === 0) return;
    onAnalyse(
      sections.map(({ start_s, end_s, sample_interval_s }) => ({
        start_s,
        end_s,
        sample_interval_s,
      })),
    );
  }
</script>

<section class="flex flex-col gap-3 rounded-lg border border-white/10 bg-white/[0.02] p-4">
  <div class="flex flex-wrap items-center gap-2 text-xs">
    <button
      type="button"
      class="rounded-md border border-emerald-400/40 bg-emerald-500/15 px-3 py-1.5 font-medium text-emerald-100 hover:bg-emerald-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      onclick={onMarkStart}
      disabled={pendingStart !== null}
    >
      Mark start
    </button>
    <button
      type="button"
      class="rounded-md border border-rose-400/40 bg-rose-500/15 px-3 py-1.5 font-medium text-rose-100 hover:bg-rose-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      onclick={onMarkEnd}
      disabled={pendingStart === null}
    >
      Mark end
    </button>
    {#if pendingStart !== null}
      <span class="text-white/60">
        Pending section starting at {formatMmSs(pendingStart)} — play and click Mark end.
      </span>
      <button
        type="button"
        class="rounded-md border border-white/15 bg-white/[0.04] px-2 py-1 text-white/70 hover:bg-white/[0.08] transition-colors"
        onclick={onCancel}
      >
        Cancel
      </button>
    {/if}
  </div>

  {#if sections.length > 0}
    <ul class="flex flex-col gap-2">
      {#each sections as section (section.id)}
        <li class="flex items-center gap-2 rounded-md border border-white/12 bg-white/[0.03] px-3 py-2">
          <input
            type="text"
            aria-label="Section start"
            class="w-14 rounded bg-black/30 px-1 py-0.5 text-xs text-white/85 font-mono"
            value={formatMmSs(section.start_s)}
            onblur={(e) => onEditStart(section.id, (e.target as HTMLInputElement).value)}
          />
          <span class="text-white/50">–</span>
          <input
            type="text"
            aria-label="Section end"
            class="w-14 rounded bg-black/30 px-1 py-0.5 text-xs text-white/85 font-mono"
            value={formatMmSs(section.end_s)}
            onblur={(e) => onEditEnd(section.id, (e.target as HTMLInputElement).value)}
          />
          <label class="flex items-center gap-1 text-xs text-white/60">
            <span class="sr-only">Density</span>
            <select
              aria-label="Density"
              class="rounded bg-black/30 px-1 py-0.5 text-white/85"
              value={String(section.sample_interval_s)}
              onchange={(e) =>
                onDensityChange(section.id, (e.target as HTMLSelectElement).value)}
            >
              <option value="1">1s</option>
              <option value="0.5">0.5s</option>
              <option value="2">2s</option>
            </select>
          </label>
          <button
            type="button"
            class="rounded border border-white/15 bg-white/[0.04] px-2 py-0.5 text-xs text-white/70 hover:bg-white/[0.08]"
            onclick={() => onSeek(section.start_s)}
            aria-label="Seek to section"
          >
            Seek
          </button>
          <button
            type="button"
            class="ml-auto rounded border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-xs text-rose-100 hover:bg-rose-500/25"
            onclick={() => onDelete(section.id)}
            aria-label="Delete section"
          >
            Delete
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  <button
    type="button"
    class="self-start rounded-md border border-blue-400/40 bg-blue-500/15 px-3 py-1.5 text-xs font-medium text-blue-100 hover:bg-blue-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
    onclick={onAnalyseClick}
    disabled={busy || sections.length === 0}
  >
    {busy ? 'Analysing…' : 'Analyse ranges'}
  </button>
</section>
```

- [ ] **Step 2: Run component tests**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web && npx vitest run tests/section-picker.test.ts
```

Expected: 9/9 passing.

- [ ] **Step 3: Commit**

```bash
git add tools/bjj-app/web/src/lib/components/SectionPicker.svelte
git commit -m "feat(bjj-app): add SectionPicker component (M9)"
```

---

## Task 12: Wire `SectionPicker` into the review page

**Files:**
- Modify: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`
- Modify: `tools/bjj-app/web/tests/review-analyse.test.ts`

- [ ] **Step 1: Rewrite `web/tests/review-analyse.test.ts`**

Replace the entire file with this version (same cytoscape + `$app/stores` mocks as before; SSE mocks drop the `pose` stage; add a case exercising Mark start / Mark end / Analyse ranges):

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('cytoscape', () => {
  const cyInstance: any = {
    on: vi.fn(), add: vi.fn(), remove: vi.fn(),
    getElementById: vi.fn(() => ({
      length: 0, style: vi.fn(), position: vi.fn(),
      addClass: vi.fn(), removeClass: vi.fn(),
    })),
    nodes: vi.fn(() => ({ forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn() })),
    edges: vi.fn(() => ({
      forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn(),
      length: 0, remove: vi.fn(),
    })),
    elements: vi.fn(() => ({ removeClass: vi.fn(), addClass: vi.fn(), remove: vi.fn() })),
    layout: vi.fn(() => ({ run: vi.fn(), stop: vi.fn() })),
    fit: vi.fn(), resize: vi.fn(), destroy: vi.fn(),
  };
  const cytoscape = vi.fn(() => cyInstance);
  (cytoscape as any).use = vi.fn();
  return { default: cytoscape };
});
vi.mock('cytoscape-cose-bilkent', () => ({ default: () => {} }));
vi.mock('marked', () => ({ marked: { parse: (s: string) => s } }));

import Page from '../src/routes/review/[id]/+page.svelte';

const { mockId } = vi.hoisted(() => ({ mockId: { value: 'abc123' } }));

vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: {
      params: { id: string };
      url: { searchParams: { get: () => null } };
    }) => void) => {
      run({ params: { id: mockId.value }, url: { searchParams: { get: () => null } } });
      return () => {};
    },
  },
}));

function detailWithoutMoments() {
  return {
    id: 'abc123',
    title: 'Review M9 test',
    date: '2026-04-22',
    partner: null,
    duration_s: 30.0,
    result: 'unknown',
    video_url: '/assets/abc123/source.mp4',
    vault_path: null,
    vault_published_at: null,
    player_a_name: 'Player A',
    player_b_name: 'Player B',
    finalised_at: null,
    scores: null,
    distribution: null,
    moments: [],
    sections: [],
  };
}

function detailWithMoments() {
  return {
    ...detailWithoutMoments(),
    moments: [
      { id: 'm1', frame_idx: 0, timestamp_s: 3.0, pose_delta: null, section_id: 's1', analyses: [], annotations: [] },
      { id: 'm2', frame_idx: 1, timestamp_s: 4.0, pose_delta: null, section_id: 's1', analyses: [], annotations: [] },
    ],
    sections: [
      { id: 's1', start_s: 3.0, end_s: 5.0, sample_interval_s: 1.0 },
    ],
  };
}

function sseBody(events: object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const e of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
      }
      controller.close();
    },
  });
}

describe('Review page — M9 section flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders the SectionPicker when the roll has no moments yet', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => detailWithoutMoments(),
      }),
    );
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Review M9 test')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /mark start/i })).toBeInTheDocument();
  });

  it('renders existing moments as chips when the roll was already analysed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => detailWithMoments(),
      }),
    );
    render(Page);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /0:03/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /0:04/i })).toBeInTheDocument();
    });
  });

  it('Mark start + Mark end + Analyse ranges streams progress and renders new chips', async () => {
    const fetchMock = vi.fn();
    // GET roll detail
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => detailWithoutMoments(),
    });
    // graph taxonomy fails; swallowed
    fetchMock.mockRejectedValueOnce(new Error('graph not needed'));
    // POST /analyse returns SSE
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: sseBody([
        { stage: 'frames', pct: 0 },
        { stage: 'frames', pct: 100, total: 2 },
        {
          stage: 'done',
          total: 2,
          moments: [
            { id: 'm-a', frame_idx: 0, timestamp_s: 3.0, section_id: 'sec-a' },
            { id: 'm-b', frame_idx: 1, timestamp_s: 4.0, section_id: 'sec-a' },
          ],
        },
      ]),
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Review M9 test')).toBeInTheDocument();
    });

    const video = document.querySelector('video') as HTMLVideoElement;
    Object.defineProperty(video, 'currentTime', { writable: true, value: 3 });
    await user.click(screen.getByRole('button', { name: /mark start/i }));
    Object.defineProperty(video, 'currentTime', { writable: true, value: 5 });
    await user.click(screen.getByRole('button', { name: /mark end/i }));

    await user.click(screen.getByRole('button', { name: /analyse ranges/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /0:03/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /0:04/i })).toBeInTheDocument();
    });
  });

  it('clicking Finalise on a roll with analyses calls POST /summarise and shows the scores panel', async () => {
    // This mirrors the M6a test. Keep it to lock in the finalise flow.
    const fetchMock = vi.fn();
    // GET detail — roll already has analyses
    const detailWithAnalyses = {
      ...detailWithMoments(),
      moments: [
        {
          id: 'm1', frame_idx: 0, timestamp_s: 3.0, pose_delta: null,
          section_id: 's1',
          analyses: [{
            id: 'a1', player: 'a', position_id: 'closed_guard_bottom',
            confidence: 0.8, description: 'd', coach_tip: 't',
          }],
          annotations: [],
        },
      ],
    };
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => detailWithAnalyses });
    fetchMock.mockRejectedValueOnce(new Error('graph not needed'));
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        finalised_at: 1713700000,
        scores: {
          summary: 'Solid.',
          scores: { guard_retention: 7, positional_awareness: 6, transition_quality: 7 },
          top_improvements: ['a'], strengths: ['b'], key_moments: [],
        },
        distribution: { timeline: [], counts: {}, percentages: { guard_bottom: 100 } },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);
    await waitFor(() => {
      expect(screen.getByText('Review M9 test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /finalise/i }));

    await waitFor(() => {
      expect(screen.getByText(/solid/i)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Update `+page.svelte`**

Edit `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`:

- Add an import: `import SectionPicker from '$lib/components/SectionPicker.svelte';`
- Remove the existing `onAnalyseClick` function body — replace it with `onAnalyseSections`:

```typescript
async function onAnalyseSections(sections: SectionInput[]) {
  if (!roll || analysing) return;
  analysing = true;
  progress = null;
  try {
    const response = await analyseRoll(roll.id, sections);
    if (!response.ok || !response.body) {
      error = `Analyse failed (${response.status})`;
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (!chunk.startsWith('data: ')) continue;
        const event = JSON.parse(chunk.slice(6)) as AnalyseEvent;
        handleAnalyseEvent(event);
      }
    }
  } finally {
    analysing = false;
  }
}
```

- Replace the header's "Analyse" button (around lines 249-257) with a lighter-weight "Picker below" hint OR just remove it. The real button now lives inside `<SectionPicker>`.
- Insert `<SectionPicker>` in the same place the old Analyse button rendered, passing `videoEl`, `durationS={roll.duration_s ?? 0}`, `onAnalyse={onAnalyseSections}`, `busy={analysing}`.
- Ensure `SectionInput` is imported from `$lib/api`.

- [ ] **Step 3: Run the rewritten review-analyse tests**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web && npx vitest run tests/review-analyse.test.ts
```

Expected: all pass.

- [ ] **Step 4: Run full frontend suite**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web && npm test
```

Expected: section-picker + review-analyse + all prior tests green.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/web/src/routes/review/[id]/+page.svelte tools/bjj-app/web/tests/review-analyse.test.ts
git commit -m "feat(bjj-app): wire SectionPicker into review page (M9)"
```

---

## Task 13: README M9 section

**Files:**
- Modify: `tools/bjj-app/README.md`

- [ ] **Step 1: Add the M9 bullet in the Milestones section**

Edit `tools/bjj-app/README.md`. Find the Milestones list and insert after the M8 line:

```markdown
- **M9 (this milestone):** Replaced the auto pose pre-pass with user-picked time-range sections. Users play the video, click **Mark start** / **Mark end** for each section of interest, tune per-section sampling density (1s / 0.5s / 2s), and click **Analyse ranges** to run Claude classification densely inside the picked ranges. Sections persist in a new `sections` table; `moments.section_id` FKs back. MediaPipe dep and pose-pre-pass code retired. Design at `docs/superpowers/specs/2026-04-22-bjj-app-m9-user-picked-sections-design.md`.
```

Also update the M8 line's `(this milestone)` marker to `(shipped)`.

Also update the top-level repo `README.md` flow description if the M9 change shifts what "Pose pre-pass" means there. Replace the current step 2 "Pose pre-pass picks ~20-40 interesting moments" with:

```markdown
2. **Pick sections** by playing the video and clicking Mark start / Mark end; set density per section.
```

- [ ] **Step 2: Commit**

```bash
git add tools/bjj-app/README.md README.md
git commit -m "docs(bjj-app): document M9 (user-picked sections) in README"
```

---

## Task 14: Manual browser smoke test

**Files:** none — smoke protocol only.

- [ ] **Step 1: Start the servers**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m uvicorn server.main:app --reload --port 8001 &
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web && npm run dev -- --port 5173 &
```

- [ ] **Step 2: Upload a fresh roll**

1. Open http://127.0.0.1:5173 and upload a short clip (20-30s is ideal for smoke).
2. Navigate to the review page for the new roll. Expect the new `SectionPicker` visible; no chips on the timeline yet.

- [ ] **Step 3: Pick two sections**

1. Press Play; at ~0:03 click **Mark start**. Watch until ~0:07 and click **Mark end**. A chip appears showing `0:03 – 0:07 @ 1s`.
2. Seek/play to 0:15. **Mark start**. Play to 0:25. **Mark end**. Change that chip's dropdown to `0.5s`. Second chip: `0:15 – 0:25 @ 0.5s`.

- [ ] **Step 4: Analyse**

1. Click **Analyse ranges**.
2. Expect an SSE progress bar to tick 0 → 100 for the frames stage.
3. After completion, the timeline row shows chips: 4 chips from section 1 (timestamps 3, 4, 5, 6) and 20 chips from section 2 (0.5s steps in [15, 25)).

- [ ] **Step 5: Verify persistence**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && sqlite3 bjj-app.db \
  "SELECT start_s, end_s, sample_interval_s FROM sections WHERE roll_id='<roll_id>'"
```

Expected: two rows matching the picked ranges.

```bash
ls assets/<roll_id>/frames/ | wc -l
```

Expected: 24 frames.

- [ ] **Step 6: Classify a moment**

Click any chip. Expected: the existing per-moment Claude analyse flow fires and `MomentDetail` renders the classification as before.

- [ ] **Step 7: Report outcome**

If any step fails, fix and commit before considering M9 merge-ready.

---

## Integration checkpoint (before declaring M9 done)

- [ ] Full backend suite passes:

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && .venv/bin/python -m pytest tests/backend -q
```

Expected: all green, no new failures.

- [ ] Full frontend suite passes:

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web && npm test
```

Expected: all green (section-picker + review-analyse + all prior).

- [ ] Smoke test (Task 14) completed end-to-end.

- [ ] Invoke `superpowers:finishing-a-development-branch` to complete the merge.
