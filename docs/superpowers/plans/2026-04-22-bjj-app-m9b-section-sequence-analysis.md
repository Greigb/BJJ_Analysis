# BJJ App M9b — Section Sequence Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot BJJ review from per-frame moment classification to one-Claude-call-per-section narrative analysis. Each user-picked time range becomes a section card with narrative + coach_tip; moments persist internally but never surface in the UI. Annotations migrate to section-level, the finalise / vault / PDF paths rewrite against sections, and the graph page is hidden.

**Architecture:** Sections grow three columns (`narrative`, `coach_tip`, `analysed_at`); the `annotations` table is rebuilt with a `section_id` FK (smoke-test-only data is discarded). `run_section_analysis` becomes async and sequential — per section: extract frames at 1 fps (cap 8), insert section + moments, call `run_claude` with a multi-image prompt, update the section, stream `section_started` / `section_queued` / `section_done` / `section_error` / `done` SSE events. Append semantics replace M9's replace-on-re-run. Frontend drops `MomentDetail` / chips / mini-graph, introduces `SectionCard`, and updates the `/api/annotations` endpoint + nav.

**Tech Stack:** Python 3.12 + FastAPI + SQLite; OpenCV (frames); `claude` CLI via existing `run_claude` adapter. SvelteKit + TypeScript + Svelte 5 runes; vitest + @testing-library/svelte.

---

## File structure

**New files (backend):**
- `tools/bjj-app/tests/backend/test_db_schema_m9b.py` — schema migration tests (new columns + annotations FK rebuild).

**New files (frontend):**
- `tools/bjj-app/web/src/lib/components/SectionCard.svelte`
- `tools/bjj-app/web/tests/section-card.test.ts`

**Modified files (backend):**
- `tools/bjj-app/server/db.py` — new `sections` columns, annotations FK rebuild, `update_section_analysis`, renamed annotation helpers, frame-file cleanup in `delete_section_and_moments`.
- `tools/bjj-app/server/analysis/prompt.py` — new `build_section_prompt`, `parse_section_response`, `SectionResponseError`.
- `tools/bjj-app/server/analysis/pipeline.py` — async, per-section Claude call, append semantics, rate-limit queued retry.
- `tools/bjj-app/server/analysis/summarise.py` — `build_summary_prompt` rewritten for sections, `parse_summary_response` takes `valid_section_ids`, `compute_distribution` deleted.
- `tools/bjj-app/server/analysis/vault_writer.py` — drop `position_distribution` from `_SUMMARY_SECTION_ORDER`, `render_key_moments_body` by section_id, `render_your_notes` groups by section range.
- `tools/bjj-app/server/api/analyse.py` — async handler, new SSE events, drop `sample_interval_s` validation, threads limiter + player names + settings into pipeline.
- `tools/bjj-app/server/api/annotations.py` — `POST /api/rolls/:id/sections/:section_id/annotations`.
- `tools/bjj-app/server/api/rolls.py` — `SectionOut` gains `narrative / coach_tip / analysed_at / annotations`; `distribution` always None; new `DELETE /api/sections/:id`.
- `tools/bjj-app/server/api/summarise.py` — loads sections + annotations_by_section; distribution dropped from response.
- `tools/bjj-app/server/api/export_pdf.py` — key_moments resolve by section_id; distribution passes through as empty.
- `tools/bjj-app/server/export/pdf.py` — `build_report_context` resolves by `section_by_id`; template guards `{% if distribution_bar %}`.
- `tools/bjj-app/server/export/templates/report.html.j2` — wrap Position Flow block in `{% if distribution_bar %}`.
- `tools/bjj-app/tests/backend/test_db_annotations.py` — rewrite for section FK.
- `tools/bjj-app/tests/backend/test_db_sections.py` — add `update_section_analysis` and frame-file-cleanup tests.
- `tools/bjj-app/tests/backend/test_pipeline_sections.py` — retire replace-on-re-run test; add append / unique-frame-idx / error-continues-batch / queued-retry.
- `tools/bjj-app/tests/backend/test_api_analyse_sections.py` — SSE event shape.
- `tools/bjj-app/tests/backend/test_api_annotations.py` — section_id URL + body.
- `tools/bjj-app/tests/backend/test_api_get_roll.py` + `test_rolls_sections.py` — SectionOut shape.
- `tools/bjj-app/tests/backend/test_api_summarise.py` — fixture shape (sections + annotations_by_section).
- `tools/bjj-app/tests/backend/test_summarise.py` — `build_summary_prompt` / `parse_summary_response` rewrite; drop `compute_distribution`.
- `tools/bjj-app/tests/backend/test_prompt.py` — add `build_section_prompt` tests.
- `tools/bjj-app/tests/backend/test_vault_writer_summary.py` — drop position_distribution, key_moments resolve by section_id, your_notes by section range.
- `tools/bjj-app/tests/backend/test_export_pdf.py` / `test_api_export_pdf.py` — key_moments fixtures use section_id.

**Modified files (frontend):**
- `tools/bjj-app/web/src/lib/types.ts` — `Section` gains `narrative / coach_tip / analysed_at / annotations`; `AnalyseEvent` discriminated union updated; `KeyMoment.moment_id` → `section_id`.
- `tools/bjj-app/web/src/lib/api.ts` — `analyseRoll` return-shape comment updated; `addAnnotation(rollId, sectionId, body)`; new `deleteSection(rollId, sectionId)`.
- `tools/bjj-app/web/src/routes/+layout.svelte` — remove `/graph` nav link.
- `tools/bjj-app/web/src/routes/review/[id]/+page.svelte` — drop chips / MomentDetail / GraphCluster; render `SectionCard` list; new SSE handler; queued banner.
- `tools/bjj-app/web/src/lib/components/SectionPicker.svelte` — drop density dropdown.
- `tools/bjj-app/web/src/lib/components/ScoresPanel.svelte` — key_moments lookup by `section_id`; wrap distribution-related UI in `{#if distribution}`.
- `tools/bjj-app/web/tests/section-picker.test.ts` — drop density-dropdown assertion.
- `tools/bjj-app/web/tests/review-analyse.test.ts` — rewrite for section flow.
- `tools/bjj-app/web/tests/scores-panel.test.ts` — drop distribution assertion; key_moments use section_id.
- `tools/bjj-app/web/tests/export-pdf.test.ts` — key_moments fixture uses section_id.

**Deleted files (frontend):**
- `tools/bjj-app/web/src/lib/components/MomentDetail.svelte`
- `tools/bjj-app/web/tests/moment-detail.test.ts`

**Documentation:**
- `tools/bjj-app/README.md` — add M9b line, mark M9 as (shipped).

---

## Task 1: DB schema — sections columns + annotations FK rebuild

**Files:**
- Modify: `tools/bjj-app/server/db.py`
- Create: `tools/bjj-app/tests/backend/test_db_schema_m9b.py`

- [ ] **Step 1: Write the failing schema test**

Create `tools/bjj-app/tests/backend/test_db_schema_m9b.py`:

```python
"""M9b schema: sections narrative/coach_tip/analysed_at + annotations.section_id FK."""
from __future__ import annotations

from server.db import connect, init_db


def test_sections_has_narrative_coach_tip_analysed_at(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(sections)")}
        assert "narrative" in cols
        assert "coach_tip" in cols
        assert "analysed_at" in cols
        assert cols["narrative"].upper() == "TEXT"
        assert cols["coach_tip"].upper() == "TEXT"
        assert cols["analysed_at"].upper() == "INTEGER"
    finally:
        conn.close()


def test_annotations_uses_section_id_fk(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
        assert "section_id" in cols
        assert "moment_id" not in cols

        fks = list(conn.execute("PRAGMA foreign_key_list(annotations)"))
        assert any(fk[2] == "sections" for fk in fks), (
            "annotations should reference sections"
        )
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path):
    """Running init_db twice must not raise or duplicate data."""
    db = tmp_path / "db.sqlite"
    init_db(db)
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sections)")}
        assert "narrative" in cols
        cols_an = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
        assert "section_id" in cols_an
    finally:
        conn.close()


def test_migration_drops_pre_m9b_annotation_rows(tmp_path):
    """Pre-M9b annotations (moment_id FK) are smoke-test-only — dropped on migration.

    Simulate a pre-M9b DB, then run init_db, and assert the annotations table is empty.
    """
    import sqlite3

    db = tmp_path / "db.sqlite"
    # First init creates the table at the current schema.
    init_db(db)
    conn = sqlite3.connect(db)
    # Force the table back to pre-M9b shape so we can seed a legacy row.
    conn.execute("DROP TABLE annotations")
    conn.execute(
        "CREATE TABLE annotations ("
        "  id TEXT PRIMARY KEY, moment_id TEXT NOT NULL, "
        "  body TEXT NOT NULL, created_at INTEGER NOT NULL, "
        "  updated_at INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO annotations VALUES ('a1', 'm1', 'legacy', 1, 1)"
    )
    conn.commit()
    conn.close()

    # Re-run init_db — migration should rebuild the table.
    init_db(db)
    conn = connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
        assert "section_id" in cols and "moment_id" not in cols
        n = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        assert n == 0
    finally:
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_db_schema_m9b.py -v`
Expected: FAIL (columns missing / annotations table still has moment_id).

- [ ] **Step 3: Update `SCHEMA_SQL` and add M9b migration helper**

In `tools/bjj-app/server/db.py`, modify the `sections` CREATE TABLE in `SCHEMA_SQL` to include the new columns for fresh installs:

```python
CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    roll_id TEXT NOT NULL REFERENCES rolls(id) ON DELETE CASCADE,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    sample_interval_s REAL NOT NULL,
    created_at INTEGER NOT NULL,
    narrative TEXT,
    coach_tip TEXT,
    analysed_at INTEGER
);
```

And rewrite the `annotations` CREATE TABLE block in `SCHEMA_SQL` to reference sections:

```python
CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
```

Add the migration helper below `_migrate_moments_m9`:

```python
_SECTIONS_M9B_COLUMNS: tuple[tuple[str, str], ...] = (
    ("narrative",   "TEXT"),
    ("coach_tip",   "TEXT"),
    ("analysed_at", "INTEGER"),
)


def _migrate_sections_m9b(conn: sqlite3.Connection) -> None:
    """Idempotently add M9b columns to an existing sections table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sections)").fetchall()}
    for name, sql_type in _SECTIONS_M9B_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE sections ADD COLUMN {name} {sql_type}")


def _migrate_annotations_m9b(conn: sqlite3.Connection) -> None:
    """Rebuild annotations with section_id FK if still on moment_id FK.

    SQLite can't ALTER FK in place — recreate the table. Pre-M9b rows are
    smoke-test-only, so the migration discards them (spec decision).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(annotations)").fetchall()}
    if "section_id" in cols and "moment_id" not in cols:
        return  # already migrated
    conn.execute("DROP TABLE IF EXISTS annotations")
    conn.execute(
        "CREATE TABLE annotations ("
        "  id TEXT PRIMARY KEY, "
        "  section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE, "
        "  body TEXT NOT NULL, "
        "  created_at INTEGER NOT NULL, "
        "  updated_at INTEGER NOT NULL"
        ")"
    )
```

Wire both into `init_db`:

```python
def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_rolls_m4(conn)
        _backfill_default_player_names(conn)
        _migrate_analyses_player_enum(conn)
        _migrate_moments_m9(conn)
        _migrate_sections_m9b(conn)
        _migrate_annotations_m9b(conn)
        conn.commit()
```

- [ ] **Step 4: Run schema tests to verify they pass**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_db_schema_m9b.py -v`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_schema_m9b.py
git commit -m "feat(bjj-app): M9b schema — sections narrative/coach_tip/analysed_at + annotations section_id FK"
```

---

## Task 2: DB helper — `update_section_analysis`

**Files:**
- Modify: `tools/bjj-app/server/db.py`
- Modify: `tools/bjj-app/tests/backend/test_db_sections.py`

- [ ] **Step 1: Write the failing test**

Append to `tools/bjj-app/tests/backend/test_db_sections.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_db_sections.py::test_update_section_analysis_writes_narrative_and_tip -v`
Expected: FAIL with `ImportError: cannot import name 'update_section_analysis'`.

- [ ] **Step 3: Implement `update_section_analysis`**

Append to `tools/bjj-app/server/db.py` (below `delete_section_and_moments`):

```python
def update_section_analysis(
    conn,
    *,
    section_id: str,
    narrative: str,
    coach_tip: str,
    analysed_at: int,
) -> None:
    """Write Claude's per-section narrative + coach_tip + completion timestamp."""
    conn.execute(
        "UPDATE sections "
        "   SET narrative = ?, coach_tip = ?, analysed_at = ? "
        " WHERE id = ?",
        (narrative, coach_tip, analysed_at, section_id),
    )
    conn.commit()
```

- [ ] **Step 4: Run to verify it passes**

Run the same pytest command; expect PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_sections.py
git commit -m "feat(bjj-app): M9b update_section_analysis helper"
```

---

## Task 3: DB helpers — rename annotation helpers to section-level

**Files:**
- Modify: `tools/bjj-app/server/db.py`
- Modify: `tools/bjj-app/tests/backend/test_db_annotations.py` (full rewrite)

- [ ] **Step 1: Rewrite `test_db_annotations.py`**

Replace the file contents with:

```python
"""Tests for insert_annotation / get_annotations_by_section / get_annotations_by_roll."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from server.db import (
    connect,
    create_roll,
    get_annotations_by_roll,
    get_annotations_by_section,
    init_db,
    insert_annotation,
    insert_section,
)


@pytest.fixture
def db_with_sections(tmp_path: Path):
    path = tmp_path / "test.db"
    init_db(path)
    conn = connect(path)
    create_roll(
        conn, id="roll-1", title="T", date="2026-04-21",
        video_path="assets/roll-1/source.mp4", duration_s=10.0,
        partner=None, result="unknown", created_at=int(time.time()),
    )
    s1 = insert_section(conn, roll_id="roll-1", start_s=3.0, end_s=5.0, sample_interval_s=1.0)
    s2 = insert_section(conn, roll_id="roll-1", start_s=7.0, end_s=9.0, sample_interval_s=1.0)
    try:
        yield conn, [s1["id"], s2["id"]]
    finally:
        conn.close()


def test_insert_annotation_persists_row(db_with_sections):
    conn, section_ids = db_with_sections
    row = insert_annotation(
        conn, section_id=section_ids[0], body="first note", created_at=1700000000
    )
    assert row["body"] == "first note"
    assert row["section_id"] == section_ids[0]
    assert row["created_at"] == 1700000000


def test_multiple_annotations_per_section_are_allowed(db_with_sections):
    conn, section_ids = db_with_sections
    insert_annotation(conn, section_id=section_ids[0], body="one", created_at=1)
    insert_annotation(conn, section_id=section_ids[0], body="two", created_at=2)
    rows = get_annotations_by_section(conn, section_ids[0])
    assert [r["body"] for r in rows] == ["one", "two"]


def test_get_annotations_by_section_orders_by_created_at(db_with_sections):
    conn, section_ids = db_with_sections
    insert_annotation(conn, section_id=section_ids[0], body="later", created_at=200)
    insert_annotation(conn, section_id=section_ids[0], body="earlier", created_at=100)
    rows = get_annotations_by_section(conn, section_ids[0])
    assert [r["body"] for r in rows] == ["earlier", "later"]


def test_get_annotations_by_roll_joins_section_timestamp(db_with_sections):
    conn, section_ids = db_with_sections
    # s1 spans 3.0-5.0, s2 spans 7.0-9.0
    insert_annotation(conn, section_id=section_ids[1], body="on s2", created_at=50)
    insert_annotation(conn, section_id=section_ids[0], body="on s1", created_at=60)
    rows = get_annotations_by_roll(conn, "roll-1")
    assert [(r["start_s"], r["end_s"], r["body"]) for r in rows] == [
        (3.0, 5.0, "on s1"),
        (7.0, 9.0, "on s2"),
    ]


def test_get_annotations_by_roll_returns_empty_for_roll_with_none(db_with_sections):
    conn, _ = db_with_sections
    assert get_annotations_by_roll(conn, "roll-1") == []


def test_annotations_cascade_delete_on_section_delete(db_with_sections):
    conn, section_ids = db_with_sections
    insert_annotation(conn, section_id=section_ids[0], body="x", created_at=1)
    conn.execute("DELETE FROM sections WHERE id = ?", (section_ids[0],))
    conn.commit()
    assert get_annotations_by_section(conn, section_ids[0]) == []
```

- [ ] **Step 2: Run to verify all fail**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_db_annotations.py -v`
Expected: FAIL (helpers not renamed yet).

- [ ] **Step 3: Rewrite the helpers in `server/db.py`**

Replace `insert_annotation`:

```python
def insert_annotation(
    conn,
    *,
    section_id: str,
    body: str,
    created_at: int,
) -> sqlite3.Row:
    """Append a new annotation to a section. Returns the inserted row."""
    annotation_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO annotations (id, section_id, body, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (annotation_id, section_id, body, created_at, created_at),
    )
    conn.commit()
    cur = conn.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    return cur.fetchone()
```

Replace `get_annotations_by_moment` with:

```python
def get_annotations_by_section(conn, section_id: str) -> list[sqlite3.Row]:
    """Return all annotations for a section ordered by created_at ascending."""
    cur = conn.execute(
        "SELECT * FROM annotations WHERE section_id = ? ORDER BY created_at",
        (section_id,),
    )
    return list(cur.fetchall())
```

Replace `get_annotations_by_roll` with a sections-based join:

```python
def get_annotations_by_roll(conn, roll_id: str) -> list[sqlite3.Row]:
    """Return all annotations for a roll, joined with their section's time range.

    Ordered for vault rendering: by section start_s ascending, then by
    created_at ascending within each section.
    Each row carries: id, section_id, body, created_at, updated_at, start_s, end_s.
    """
    cur = conn.execute(
        """
        SELECT a.id, a.section_id, a.body, a.created_at, a.updated_at,
               s.start_s, s.end_s
          FROM annotations a
          JOIN sections s ON s.id = a.section_id
         WHERE s.roll_id = ?
         ORDER BY s.start_s ASC, a.created_at ASC
        """,
        (roll_id,),
    )
    return list(cur.fetchall())
```

- [ ] **Step 4: Run to verify annotation tests pass**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_db_annotations.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_annotations.py
git commit -m "feat(bjj-app): M9b annotations FK rename — insert/get_by_section, get_by_roll joins sections"
```

---

## Task 4: DB helper — `delete_section_and_moments` cleans frame files

**Files:**
- Modify: `tools/bjj-app/server/db.py`
- Modify: `tools/bjj-app/tests/backend/test_db_sections.py`

- [ ] **Step 1: Write the failing test**

Append to `tools/bjj-app/tests/backend/test_db_sections.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_db_sections.py -k delete_section_and_moments -v`
Expected: FAIL (`TypeError: unexpected keyword argument 'frames_dir'`).

- [ ] **Step 3: Update `delete_section_and_moments`**

Replace the existing function body in `server/db.py`:

```python
def delete_section_and_moments(conn, *, section_id: str, frames_dir: Path) -> None:
    """Delete a section, all its moments, and their frame files on disk.

    `frames_dir` is the directory that holds `frame_NNNNNN.jpg` files for the roll.
    Missing files are tolerated silently (never leave a DB delete blocked on a
    missing disk file).
    """
    rows = conn.execute(
        "SELECT frame_idx FROM moments WHERE section_id = ?", (section_id,)
    ).fetchall()
    conn.execute("DELETE FROM moments WHERE section_id = ?", (section_id,))
    conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
    conn.commit()
    for row in rows:
        path = frames_dir / f"frame_{int(row['frame_idx']):06d}.jpg"
        try:
            path.unlink()
        except FileNotFoundError:
            pass
```

Make sure `from pathlib import Path` is already imported at module top (it is).

- [ ] **Step 4: Run to verify the tests pass**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_db_sections.py -v`
Expected: all PASS (including the pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_sections.py
git commit -m "feat(bjj-app): M9b delete_section_and_moments removes frame files from disk"
```

---

## Task 5: Prompt helper — `build_section_prompt` + `parse_section_response`

**Files:**
- Modify: `tools/bjj-app/server/analysis/prompt.py`
- Modify: `tools/bjj-app/tests/backend/test_prompt.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/bjj-app/tests/backend/test_prompt.py`:

```python
def test_build_section_prompt_contains_frame_refs_and_names(tmp_path):
    from server.analysis.prompt import build_section_prompt

    frames = [tmp_path / f"frame_{i:06d}.jpg" for i in range(3)]
    for f in frames:
        f.write_bytes(b"x")

    prompt = build_section_prompt(
        start_s=3.0,
        end_s=7.0,
        frame_paths=frames,
        timestamps=[3.0, 4.0, 5.0],
        player_a_name="Greig",
        player_b_name="Sam",
    )
    assert "Greig" in prompt
    assert "Sam" in prompt
    assert "4s" in prompt  # duration
    for f in frames:
        assert f"@{f}" in prompt
    assert '"narrative"' in prompt
    assert '"coach_tip"' in prompt


def test_parse_section_response_happy_path():
    from server.analysis.prompt import parse_section_response

    raw = '{"narrative": "Player A passes to side control.", "coach_tip": "Stay heavy."}'
    out = parse_section_response(raw)
    assert out["narrative"] == "Player A passes to side control."
    assert out["coach_tip"] == "Stay heavy."


def test_parse_section_response_rejects_malformed_json():
    import pytest
    from server.analysis.prompt import parse_section_response, SectionResponseError
    with pytest.raises(SectionResponseError):
        parse_section_response("not json")


def test_parse_section_response_rejects_missing_field():
    import pytest
    from server.analysis.prompt import parse_section_response, SectionResponseError
    with pytest.raises(SectionResponseError):
        parse_section_response('{"narrative": "x"}')


def test_parse_section_response_rejects_empty_string_field():
    import pytest
    from server.analysis.prompt import parse_section_response, SectionResponseError
    with pytest.raises(SectionResponseError):
        parse_section_response('{"narrative": "", "coach_tip": "x"}')
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_prompt.py -v`
Expected: 5 new tests fail with import errors.

- [ ] **Step 3: Implement the new prompt helpers**

Append to `tools/bjj-app/server/analysis/prompt.py`:

```python
class SectionResponseError(Exception):
    """Raised when Claude's section narrative output fails schema validation."""


_SECTION_SCHEMA_HINT = (
    'Output ONE JSON object and nothing else. No prose outside JSON. No markdown fences.\n'
    '{\n'
    '  "narrative": "<one paragraph, 2-5 sentences>",\n'
    '  "coach_tip": "<one actionable sentence for player_a>"\n'
    '}'
)


def build_section_prompt(
    *,
    start_s: float,
    end_s: float,
    frame_paths: list[Path],
    timestamps: list[float],
    player_a_name: str,
    player_b_name: str,
) -> str:
    """Build the multi-image section narrative prompt.

    Caller must have already written the frames to disk. `frame_paths` and
    `timestamps` are parallel lists in chronological order.
    """
    if len(frame_paths) != len(timestamps):
        raise ValueError(
            f"frame_paths ({len(frame_paths)}) and timestamps "
            f"({len(timestamps)}) must be same length"
        )
    if not frame_paths:
        raise ValueError("build_section_prompt requires at least one frame")

    duration_s = round(end_s - start_s, 2)
    preamble = (
        f"You are analysing a Brazilian Jiu-Jitsu sequence between "
        f"{player_a_name} (player_a in output) and {player_b_name} (player_b in output)."
    )
    intro = (
        f"Below are {len(frame_paths)} chronologically ordered frames spanning "
        f"{duration_s}s of footage. Review all frames as one continuous sequence "
        f"and describe what happens."
    )
    frame_lines = [
        f"Frame {i + 1} @t={timestamps[i]}s: @{frame_paths[i]}"
        for i in range(len(frame_paths))
    ]
    guidance = (
        "Describe the positions, transitions, who initiates what, and where the "
        "sequence ends. Use standard BJJ vocabulary (e.g. \"closed guard bottom\", "
        "\"passes half guard to side control\", \"triangle attempt\"). Follow with "
        "one actionable coach tip directed at player_a."
    )
    return "\n\n".join([
        preamble,
        intro,
        "\n".join(frame_lines),
        guidance,
        _SECTION_SCHEMA_HINT,
    ])


def parse_section_response(raw: str) -> dict:
    """Strict JSON parse + schema validation. Raises SectionResponseError on bad input."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SectionResponseError(f"not valid JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise SectionResponseError(
            f"expected an object, got {type(data).__name__}"
        )
    for key in ("narrative", "coach_tip"):
        if key not in data:
            raise SectionResponseError(f"missing required key: {key}")
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            raise SectionResponseError(f"{key} must be a non-empty string")
    return {"narrative": data["narrative"].strip(), "coach_tip": data["coach_tip"].strip()}
```

- [ ] **Step 4: Run to verify tests pass**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_prompt.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/analysis/prompt.py tools/bjj-app/tests/backend/test_prompt.py
git commit -m "feat(bjj-app): M9b build_section_prompt + parse_section_response"
```

---

## Task 6: Pipeline rewrite — async, per-section multi-image, append semantics

**Files:**
- Modify: `tools/bjj-app/server/analysis/pipeline.py`
- Modify: `tools/bjj-app/tests/backend/test_pipeline_sections.py`

- [ ] **Step 1: Rewrite `test_pipeline_sections.py`**

Replace the file content with (retires `test_re_running_replaces_prior_sections`, adds append + unique-frame-idx + error-continues-batch + queued-retry):

```python
"""Integration tests for the M9b async section pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.analysis.pipeline import run_section_analysis
from server.analysis.rate_limit import SlidingWindowLimiter
from server.db import connect, create_roll, get_moments, get_sections_by_roll, init_db


def _short_video_path() -> Path:
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


def _make_roll(conn) -> None:
    create_roll(
        conn, id="r1", title="Test", date="2026-04-22",
        video_path="assets/r1/source.mp4", duration_s=2.0,
        partner=None, result="unknown", created_at=1713700000,
        player_a_name="Greig", player_b_name="Sam",
    )


def _fake_settings(tmp_path):
    from server.config import Settings
    return Settings(
        project_root=tmp_path,
        vault_root=tmp_path,
        db_path=tmp_path / "db.sqlite",
        host="0.0.0.0",
        port=8000,
        frontend_build_dir=tmp_path / "build",
        claude_bin=Path("/usr/bin/false"),  # never actually invoked in tests
        claude_model="test",
        claude_max_calls=100,
        claude_window_seconds=60.0,
        taxonomy_path=tmp_path / "taxonomy.json",
    )


async def _drain(agen):
    events = []
    async for e in agen:
        events.append(e)
    return events


@pytest.mark.asyncio
async def test_emits_section_started_and_section_done(tmp_path, monkeypatch):
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return '{"narrative": "A recovers guard.", "coach_tip": "Elbows tight."}'

    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        events = await _drain(run_section_analysis(
            conn=conn,
            roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.5}],
            duration_s=2.0,
            player_a_name="Greig",
            player_b_name="Sam",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        stages = [e["stage"] for e in events]
        assert stages[0] == "section_started"
        assert "section_done" in stages
        assert stages[-1] == "done"
        done = events[-1]
        assert done["total"] == 1

        sections = get_sections_by_roll(conn, "r1")
        assert len(sections) == 1
        assert sections[0]["narrative"] == "A recovers guard."
        assert sections[0]["coach_tip"] == "Elbows tight."
        assert sections[0]["analysed_at"] is not None
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_adding_sections_preserves_prior_sections(tmp_path, monkeypatch):
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return '{"narrative": "x", "coach_tip": "y"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="Greig", player_b_name="Sam",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 1.0, "end_s": 2.0}],
            duration_s=2.0,
            player_a_name="Greig", player_b_name="Sam",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        sections = get_sections_by_roll(conn, "r1")
        assert len(sections) == 2
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_assigns_unique_frame_idx_across_runs(tmp_path, monkeypatch):
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return '{"narrative": "x", "coach_tip": "y"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 1.0, "end_s": 2.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        moments = get_moments(conn, "r1")
        idxs = [m["frame_idx"] for m in moments]
        assert len(idxs) == len(set(idxs)), f"frame_idx collisions: {idxs}"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_section_error_continues_batch(tmp_path, monkeypatch):
    """A parse error on section 1 must not block section 2."""
    calls = {"n": 0}
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json"
        return '{"narrative": "ok", "coach_tip": "tip"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        events = await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[
                {"start_s": 0.0, "end_s": 1.0},
                {"start_s": 1.0, "end_s": 2.0},
            ],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        stages = [e["stage"] for e in events]
        assert "section_error" in stages
        assert stages.count("section_done") == 1
        assert stages[-1] == "done"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_rate_limit_retry_emits_queued_then_succeeds(tmp_path, monkeypatch):
    from server.analysis.claude_cli import RateLimitedError

    calls = {"n": 0}
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitedError(retry_after_s=0.01)
        return '{"narrative": "ok", "coach_tip": "tip"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    async def fake_sleep(s): pass
    monkeypatch.setattr("server.analysis.pipeline.asyncio.sleep", fake_sleep)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        events = await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        stages = [e["stage"] for e in events]
        assert "section_queued" in stages
        assert "section_done" in stages
    finally:
        conn.close()
```

Add `pytest-asyncio` if not already installed. If the project doesn't yet use `@pytest.mark.asyncio`, check `pyproject.toml` — it's needed. If missing, add this to `tools/bjj-app/pyproject.toml` `[project.optional-dependencies].dev` or the `tool.pytest.ini_options` block:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

(If `asyncio_mode = "auto"` is set, remove the `@pytest.mark.asyncio` decorators from the tests above. Check `tools/bjj-app/pyproject.toml` before committing to match the project's existing convention — check any other `async def test_` in `tests/backend/` for the pattern already used.)

- [ ] **Step 2: Run the tests to verify failure**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_pipeline_sections.py -v`
Expected: multiple failures (signature mismatch, sync→async).

- [ ] **Step 3: Rewrite `server/analysis/pipeline.py`**

Replace the file contents with:

```python
"""M9b section-sequence analysis pipeline.

Per user-picked section: extract 1 fps frames (cap 8), persist section + moments,
call Claude Opus with a multi-image narrative prompt, stream SSE progress events.
Append semantics — a second Analyse click adds new sections rather than replacing
prior ones.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import AsyncIterator

from server.analysis.claude_cli import (
    ClaudeProcessError,
    ClaudeResponseError,
    RateLimitedError,
    run_claude,
)
from server.analysis.frames import extract_frames_at_timestamps
from server.analysis.prompt import (
    SectionResponseError,
    build_section_prompt,
    parse_section_response,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import Settings
from server.db import (
    insert_moments,
    insert_section,
    update_section_analysis,
)

_MAX_FRAMES_PER_SECTION = 8
_MAX_RATE_LIMIT_RETRIES = 3


def _section_timestamps(start_s: float, end_s: float) -> list[float]:
    """1 fps sampling, capped at _MAX_FRAMES_PER_SECTION, rounded to 3dp."""
    duration = max(0.0, end_s - start_s)
    n = min(_MAX_FRAMES_PER_SECTION, max(1, int(round(duration))))
    if n <= 1:
        return [round(start_s, 3)]
    step = duration / n
    return [round(start_s + i * step, 3) for i in range(n)]


def _next_frame_idx(conn, roll_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(frame_idx), -1) AS m FROM moments WHERE roll_id = ?",
        (roll_id,),
    ).fetchone()
    return int(row["m"]) + 1


async def run_section_analysis(
    *,
    conn,
    roll_id: str,
    video_path: Path,
    frames_dir: Path,
    sections: list[dict],
    duration_s: float,
    player_a_name: str,
    player_b_name: str,
    settings: Settings,
    limiter: SlidingWindowLimiter,
) -> AsyncIterator[dict]:
    """Process each section sequentially. Yields SSE-shaped dicts.

    Event shapes:
      {"stage": "section_started", "section_id", "start_s", "end_s", "idx", "total"}
      {"stage": "section_queued",  "section_id", "retry_after_s"}
      {"stage": "section_done",    "section_id", "start_s", "end_s",
                                   "narrative", "coach_tip"}
      {"stage": "section_error",   "section_id", "error"}
      {"stage": "done",            "total"}

    Caller validates input (see server/api/analyse.py).
    """
    total = len(sections)
    for idx, sec_in in enumerate(sections):
        start_s = float(sec_in["start_s"])
        end_s = float(sec_in["end_s"])
        timestamps = _section_timestamps(start_s, end_s)

        start_index = _next_frame_idx(conn, roll_id)
        frame_paths = extract_frames_at_timestamps(
            video_path=video_path,
            timestamps=timestamps,
            out_dir=frames_dir,
            start_index=start_index,
        )

        section_row = insert_section(
            conn,
            roll_id=roll_id,
            start_s=start_s,
            end_s=end_s,
            sample_interval_s=1.0,
        )
        section_id = section_row["id"]

        insert_moments(
            conn,
            roll_id=roll_id,
            moments=[
                {
                    "frame_idx": start_index + i,
                    "timestamp_s": timestamps[i],
                    "pose_delta": None,
                    "section_id": section_id,
                }
                for i in range(len(timestamps))
            ],
        )

        yield {
            "stage": "section_started",
            "section_id": section_id,
            "start_s": start_s,
            "end_s": end_s,
            "idx": idx,
            "total": total,
        }

        prompt = build_section_prompt(
            start_s=start_s,
            end_s=end_s,
            frame_paths=frame_paths,
            timestamps=timestamps,
            player_a_name=player_a_name,
            player_b_name=player_b_name,
        )

        error_msg: str | None = None
        raw: str | None = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES):
            try:
                raw = await run_claude(prompt, settings=settings, limiter=limiter)
                break
            except RateLimitedError as exc:
                if attempt == _MAX_RATE_LIMIT_RETRIES - 1:
                    error_msg = f"rate-limited after {_MAX_RATE_LIMIT_RETRIES} retries"
                    break
                yield {
                    "stage": "section_queued",
                    "section_id": section_id,
                    "retry_after_s": exc.retry_after_s,
                }
                await asyncio.sleep(exc.retry_after_s)
            except (ClaudeProcessError, ClaudeResponseError) as exc:
                error_msg = f"claude failed: {exc}"
                break

        if error_msg is None and raw is not None:
            try:
                parsed = parse_section_response(raw)
            except SectionResponseError as exc:
                error_msg = f"malformed output: {exc}"
            else:
                update_section_analysis(
                    conn,
                    section_id=section_id,
                    narrative=parsed["narrative"],
                    coach_tip=parsed["coach_tip"],
                    analysed_at=int(time.time()),
                )
                yield {
                    "stage": "section_done",
                    "section_id": section_id,
                    "start_s": start_s,
                    "end_s": end_s,
                    "narrative": parsed["narrative"],
                    "coach_tip": parsed["coach_tip"],
                }
                continue

        yield {
            "stage": "section_error",
            "section_id": section_id,
            "error": error_msg or "unknown error",
        }

    yield {"stage": "done", "total": total}
```

- [ ] **Step 4: Run tests**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_pipeline_sections.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/analysis/pipeline.py tools/bjj-app/tests/backend/test_pipeline_sections.py
git commit -m "feat(bjj-app): M9b pipeline rewrite — async per-section multi-image call, append semantics, queued retry"
```

---

## Task 7: API `POST /analyse` — async handler, new SSE events

**Files:**
- Modify: `tools/bjj-app/server/api/analyse.py`
- Modify: `tools/bjj-app/tests/backend/test_api_analyse_sections.py`

- [ ] **Step 1: Update the tests**

Replace the contents of `tests/backend/test_api_analyse_sections.py` with a rewritten version (keep the `app_client` fixture; rewrite the happy path + drop the `interval not allowed` test since M9b ignores `sample_interval_s`). Use the file below verbatim:

```python
"""Integration tests for POST /api/rolls/:id/analyse (M9b sections)."""
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
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "taxonomy.json").write_text(json.dumps({
        "events": {}, "categories": {}, "positions": [], "valid_transitions": [],
    }))

    # Stub run_claude so no real subprocess is spawned.
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return '{"narrative": "test narrative", "coach_tip": "test tip"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    from server.main import create_app
    from server.db import connect, create_roll, init_db

    init_db(tmp_path / "test.db")
    roll_id = "r1"
    import shutil
    roll_dir = tmp_path / "assets" / roll_id
    roll_dir.mkdir()
    shutil.copy(_short_video_path(), roll_dir / "source.mp4")

    conn = connect(tmp_path / "test.db")
    try:
        create_roll(
            conn, id=roll_id, title="Fixture", date="2026-04-22",
            video_path=f"assets/{roll_id}/source.mp4",
            duration_s=2.0, partner=None, result="unknown",
            created_at=1713700000,
            player_a_name="Player A", player_b_name="Player B",
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
        assert r.status_code in (400, 422)

    def test_400_when_sections_empty(self, app_client):
        client, _, roll_id = app_client
        r = client.post(f"/api/rolls/{roll_id}/analyse", json={"sections": []})
        assert r.status_code in (400, 422)

    def test_400_when_end_before_start(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [{"start_s": 2.0, "end_s": 1.0}]},
        )
        assert r.status_code == 400

    def test_400_when_end_exceeds_duration(self, app_client):
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [{"start_s": 0.0, "end_s": 999.0}]},
        )
        assert r.status_code == 400

    def test_accepts_sample_interval_s_but_ignores_it(self, app_client):
        """Old frontends may still send sample_interval_s — backend accepts, ignores."""
        client, _, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [
                {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 0.25},
            ]},
        )
        assert r.status_code == 200

    def test_404_when_roll_missing(self, app_client):
        client, _, _ = app_client
        r = client.post(
            "/api/rolls/no-such-roll/analyse",
            json={"sections": [{"start_s": 0.0, "end_s": 1.0}]},
        )
        assert r.status_code == 404

    def test_happy_path_streams_section_events_and_persists(self, app_client):
        client, root, roll_id = app_client
        r = client.post(
            f"/api/rolls/{roll_id}/analyse",
            json={"sections": [{"start_s": 0.0, "end_s": 1.0}]},
        )
        assert r.status_code == 200
        body = r.text
        assert "section_started" in body
        assert "section_done" in body
        assert '"stage": "done"' in body or '"stage":"done"' in body

        from server.db import connect, get_sections_by_roll
        conn = connect(root / "test.db")
        try:
            sections = get_sections_by_roll(conn, roll_id)
            assert len(sections) == 1
            assert sections[0]["narrative"] == "test narrative"
            assert sections[0]["coach_tip"] == "test tip"
            assert sections[0]["analysed_at"] is not None
        finally:
            conn.close()

        # Frame on disk — one per second of duration, capped at 8.
        assert (root / "assets" / roll_id / "frames" / "frame_000000.jpg").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_api_analyse_sections.py -v`
Expected: mostly FAIL (handler still sync, old SSE shape).

- [ ] **Step 3: Rewrite `server/api/analyse.py`**

Replace the file contents with:

```python
"""POST /api/rolls/:id/analyse — SSE stream of the M9b section-narrative pipeline."""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.analysis.pipeline import run_section_analysis
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import Settings, load_settings
from server.db import connect, get_roll

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analyse"])

_DURATION_EPSILON = 0.5

# Module-level singleton for per-section Claude rate limiting.
_SECTION_LIMITER: SlidingWindowLimiter | None = None


def _get_limiter(settings: Settings) -> SlidingWindowLimiter:
    global _SECTION_LIMITER
    if _SECTION_LIMITER is None:
        _SECTION_LIMITER = SlidingWindowLimiter(
            max_calls=settings.claude_max_calls,
            window_seconds=settings.claude_window_seconds,
        )
    return _SECTION_LIMITER


class _SectionIn(BaseModel):
    start_s: float = Field(..., ge=0)
    end_s: float = Field(..., ge=0)
    # Accepted for frontend-transition compatibility; ignored by the pipeline.
    sample_interval_s: float | None = None


class _AnalyseIn(BaseModel):
    sections: list[_SectionIn] = Field(..., min_length=1)


@router.post("/rolls/{roll_id}/analyse")
async def analyse_roll(
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

    video_path = settings.project_root / row["video_path"]
    frames_dir = settings.project_root / "assets" / roll_id / "frames"
    sections_payload = [
        {"start_s": s.start_s, "end_s": s.end_s} for s in payload.sections
    ]
    player_a_name = row["player_a_name"] or "Player A"
    player_b_name = row["player_b_name"] or "Player B"
    limiter = _get_limiter(settings)

    async def event_stream() -> AsyncIterator[bytes]:
        conn2 = connect(settings.db_path)
        try:
            async for event in run_section_analysis(
                conn=conn2,
                roll_id=roll_id,
                video_path=video_path,
                frames_dir=frames_dir,
                sections=sections_payload,
                duration_s=duration_s,
                player_a_name=player_a_name,
                player_b_name=player_b_name,
                settings=settings,
                limiter=limiter,
            ):
                yield f"data: {json.dumps(event)}\n\n".encode("utf-8")
        except Exception:
            logger.exception("Analyse pipeline failed for %s", roll_id)
            yield b'data: {"stage":"done","total":0}\n\n'
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

Also update `tests/backend/conftest.py` to reset the new singleton. Add this to the `_reset_claude_limiter` fixture:

```python
    try:
        import server.api.analyse as analyse_mod
        analyse_mod._SECTION_LIMITER = None
    except Exception:
        pass
```

- [ ] **Step 4: Run to verify tests pass**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_api_analyse_sections.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/api/analyse.py tools/bjj-app/tests/backend/conftest.py tools/bjj-app/tests/backend/test_api_analyse_sections.py
git commit -m "feat(bjj-app): M9b /analyse async handler with new section_started/queued/done/error SSE events"
```

---

## Task 8: API `DELETE /api/rolls/:id/sections/:section_id` + `POST /annotations` rewrite

**Files:**
- Modify: `tools/bjj-app/server/api/rolls.py` (add DELETE route, update SectionOut shape)
- Modify: `tools/bjj-app/server/api/annotations.py`
- Modify: `tools/bjj-app/tests/backend/test_api_annotations.py`
- Modify: `tools/bjj-app/tests/backend/test_rolls_sections.py`

- [ ] **Step 1: Rewrite `test_api_annotations.py`**

Replace file content with a section-id variant. Use the existing test as template — change URL from `/moments/{moment_id}/annotations` to `/sections/{section_id}/annotations`. For the fixture, replace `insert_moments` seeding with `insert_section`. Match the existing test structure: `test_annotation_appends_to_section`, `test_annotation_missing_section_returns_404`, `test_annotation_empty_body_returns_400`. Example test:

```python
"""Tests for POST /api/rolls/:id/sections/:section_id/annotations."""
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
            conn, id="r1", title="T", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=10.0,
            partner=None, result="unknown", created_at=1713700000,
        )
        sec = insert_section(conn, roll_id="r1", start_s=0.0, end_s=4.0, sample_interval_s=1.0)
    finally:
        conn.close()

    from server.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c, sec["id"]


def test_annotation_appends_to_section(app_client):
    client, section_id = app_client
    r = client.patch(
        f"/api/rolls/r1/sections/{section_id}/annotations",
        json={"body": "keep elbows in"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["body"] == "keep elbows in"
    assert body["id"]


def test_annotation_missing_section_returns_404(app_client):
    client, _ = app_client
    r = client.patch(
        "/api/rolls/r1/sections/no-such/annotations",
        json={"body": "x"},
    )
    assert r.status_code == 404


def test_annotation_empty_body_returns_400(app_client):
    client, section_id = app_client
    r = client.patch(
        f"/api/rolls/r1/sections/{section_id}/annotations",
        json={"body": "   "},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_api_annotations.py -v`
Expected: FAIL (route mismatch).

- [ ] **Step 3: Rewrite `server/api/annotations.py`**

Replace the file content with:

```python
"""PATCH /api/rolls/:id/sections/:section_id/annotations — append-only annotations."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from server.config import Settings, load_settings
from server.db import connect, get_roll, get_sections_by_roll, insert_annotation

router = APIRouter(prefix="/api", tags=["annotations"])


class _AnnotationIn(BaseModel):
    body: str


class _AnnotationOut(BaseModel):
    id: str
    body: str
    created_at: int


@router.patch(
    "/rolls/{roll_id}/sections/{section_id}/annotations",
    response_model=_AnnotationOut,
    status_code=status.HTTP_201_CREATED,
)
def add_annotation(
    roll_id: str,
    section_id: str,
    payload: _AnnotationIn,
    settings: Settings = Depends(load_settings),
) -> _AnnotationOut:
    body = payload.body.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Annotation body must not be empty",
        )
    conn = connect(settings.db_path)
    try:
        if get_roll(conn, roll_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        sections = get_sections_by_roll(conn, roll_id)
        if not any(s["id"] == section_id for s in sections):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
            )
        row = insert_annotation(
            conn, section_id=section_id, body=body, created_at=int(time.time())
        )
    finally:
        conn.close()
    return _AnnotationOut(id=row["id"], body=row["body"], created_at=row["created_at"])
```

- [ ] **Step 4: Add `DELETE /api/rolls/:id/sections/:section_id` to `server/api/rolls.py`**

Append to `server/api/rolls.py`, importing `delete_section_and_moments` at the top:

```python
from server.db import (
    connect,
    create_roll,
    delete_section_and_moments,
    get_analyses,
    get_annotations_by_roll,
    get_annotations_by_section,
    get_moments,
    get_roll,
    get_sections_by_roll,
)
```

And at the bottom of the router:

```python
@router.delete("/rolls/{roll_id}/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_section(
    roll_id: str,
    section_id: str,
    settings: Settings = Depends(load_settings),
) -> Response:
    conn = connect(settings.db_path)
    try:
        if get_roll(conn, roll_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        sections = get_sections_by_roll(conn, roll_id)
        if not any(s["id"] == section_id for s in sections):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
            )
        frames_dir = settings.project_root / "assets" / roll_id / "frames"
        delete_section_and_moments(conn, section_id=section_id, frames_dir=frames_dir)
    finally:
        conn.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Import `Response` from `fastapi` at the top of the file if not already present.

- [ ] **Step 5: Run annotations tests + add a quick DELETE test**

Append to `tools/bjj-app/tests/backend/test_rolls_sections.py`:

```python
def test_delete_section_removes_row_and_moments(app_client):
    # Existing fixture populates r1 with two sections; delete the first.
    r0 = app_client.get("/api/rolls/r1").json()
    section_id = r0["sections"][0]["id"]
    r = app_client.delete(f"/api/rolls/r1/sections/{section_id}")
    assert r.status_code == 204
    r1 = app_client.get("/api/rolls/r1").json()
    assert section_id not in {s["id"] for s in r1["sections"]}
```

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_api_annotations.py tests/backend/test_rolls_sections.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/api/annotations.py tools/bjj-app/server/api/rolls.py tools/bjj-app/tests/backend/test_api_annotations.py tools/bjj-app/tests/backend/test_rolls_sections.py
git commit -m "feat(bjj-app): M9b /annotations section-level + DELETE /sections/:id endpoint"
```

---

## Task 9: API `GET /rolls/:id` — SectionOut shape + drop per-moment annotations

**Files:**
- Modify: `tools/bjj-app/server/api/rolls.py`
- Modify: `tools/bjj-app/tests/backend/test_rolls_sections.py`
- Modify: `tools/bjj-app/tests/backend/test_api_get_roll.py` (if it references `distribution` / per-moment annotations)

- [ ] **Step 1: Update the roll-detail fixture test**

Extend `tests/backend/test_rolls_sections.py` to exercise the new SectionOut fields. Seed the fixture with `update_section_analysis` + `insert_annotation` for one section; assert the response shape:

```python
def test_roll_detail_sections_include_narrative_coach_tip_annotations(app_client):
    # The fixture already inserts two sections; update the first with analysis
    # + annotation and assert the response shape.
    from server.db import (
        connect, insert_annotation, update_section_analysis,
    )
    import os
    db_path = os.environ["BJJ_DB_OVERRIDE"]
    conn = connect(db_path)
    try:
        r0 = app_client.get("/api/rolls/r1").json()
        section_id = r0["sections"][0]["id"]
        update_section_analysis(
            conn, section_id=section_id,
            narrative="A passes to side control.",
            coach_tip="Stay heavy.",
            analysed_at=1713700100,
        )
        insert_annotation(
            conn, section_id=section_id, body="first note", created_at=1713700200,
        )
    finally:
        conn.close()

    r1 = app_client.get("/api/rolls/r1").json()
    s0 = r1["sections"][0]
    assert s0["narrative"] == "A passes to side control."
    assert s0["coach_tip"] == "Stay heavy."
    assert s0["analysed_at"] == 1713700100
    assert len(s0["annotations"]) == 1
    assert s0["annotations"][0]["body"] == "first note"


def test_roll_detail_distribution_is_null(app_client):
    r = app_client.get("/api/rolls/r1").json()
    assert r["distribution"] is None
```

Note: `BJJ_DB_OVERRIDE` is set by the fixture; accessing it via `os.environ` works inside the test.

- [ ] **Step 2: Run to verify failure**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_rolls_sections.py -v`
Expected: FAIL (missing fields).

- [ ] **Step 3: Update `server/api/rolls.py`**

Rewrite the `SectionOut` model and the `get_roll_detail` handler. Replace `SectionOut`:

```python
class SectionOut(BaseModel):
    id: str
    start_s: float
    end_s: float
    sample_interval_s: float
    narrative: str | None = None
    coach_tip: str | None = None
    analysed_at: int | None = None
    annotations: list[AnnotationOut] = []
```

Rewrite the `sections` block in `get_roll_detail` so each SectionOut carries its annotations and new fields. Replace the `sections=[... ]` tail:

```python
    annotations_by_section = {
        s["id"]: get_annotations_by_section(conn, s["id"]) for s in section_rows
    }
```

(Move the `annotations_by_section` gather *inside* the `try` block before `finally: conn.close()`.)

Then:

```python
    sections_out = [
        SectionOut(
            id=s["id"],
            start_s=s["start_s"],
            end_s=s["end_s"],
            sample_interval_s=s["sample_interval_s"],
            narrative=s["narrative"],
            coach_tip=s["coach_tip"],
            analysed_at=s["analysed_at"],
            annotations=[
                AnnotationOut(id=a["id"], body=a["body"], created_at=a["created_at"])
                for a in annotations_by_section[s["id"]]
            ],
        )
        for s in section_rows
    ]
```

Also: **delete the `distribution` computation** in `get_roll_detail` entirely — it always returns `None` post-M9b. And **delete the `annotations_by_moment` lookup** — `MomentOut.annotations` defaults to `[]` and is no longer populated (moments are internal). Drop the `from server.analysis.summarise import compute_distribution` import at the top — it's about to be deleted anyway (Task 11).

Remove `get_annotations_by_moment` from the imports at the top (it's been renamed). Replace `annotations=[...]` in `MomentOut` construction with `annotations=[]`.

Finally, change the return statement to use `sections=sections_out` and `distribution=None`.

- [ ] **Step 4: Run tests**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_rolls_sections.py tests/backend/test_api_get_roll.py -v`
Expected: all PASS (may need to update `test_api_get_roll.py` if any test hard-codes `distribution != null` — grep first: `grep -n distribution tools/bjj-app/tests/backend/test_api_get_roll.py`).

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/api/rolls.py tools/bjj-app/tests/backend/test_rolls_sections.py tools/bjj-app/tests/backend/test_api_get_roll.py
git commit -m "feat(bjj-app): M9b SectionOut gains narrative/coach_tip/analysed_at/annotations; distribution dropped"
```

---

## Task 10: Summarise rewrite — sections in, no distribution

**Files:**
- Modify: `tools/bjj-app/server/analysis/summarise.py`
- Modify: `tools/bjj-app/server/api/summarise.py`
- Modify: `tools/bjj-app/tests/backend/test_summarise.py`
- Modify: `tools/bjj-app/tests/backend/test_api_summarise.py`

- [ ] **Step 1: Rewrite `test_summarise.py`**

Keep one legacy-style helper test (`_format_mm_ss` / `_clamp_score` stays). Replace the `build_summary_prompt` and `parse_summary_response` tests with section-based versions, and **delete** any `compute_distribution` tests. Example new prompt test:

```python
def test_build_summary_prompt_includes_section_narratives_and_annotations():
    from server.analysis.summarise import build_summary_prompt
    roll = {
        "player_a_name": "Greig", "player_b_name": "Sam",
        "duration_s": 60.0, "date": "2026-04-22",
    }
    sections = [
        {
            "id": "sec1", "start_s": 3.0, "end_s": 7.0,
            "narrative": "Greig recovers closed guard.",
            "coach_tip": "Stay elbows in.",
        },
        {
            "id": "sec2", "start_s": 15.0, "end_s": 22.0,
            "narrative": "Sam passes half guard.",
            "coach_tip": "Frame on hips.",
        },
    ]
    annotations_by_section = {
        "sec1": [{"body": "triangle was there", "created_at": 1713700000}],
        "sec2": [],
    }
    out = build_summary_prompt(
        roll_row=roll, sections=sections,
        annotations_by_section=annotations_by_section,
    )
    assert "Greig recovers closed guard." in out
    assert "Sam passes half guard." in out
    assert "triangle was there" in out
    assert "sec1" in out  # for key_moments matching
    assert "0:03" in out  # mm:ss
    assert "0:15" in out


def test_parse_summary_response_validates_section_ids():
    import pytest
    from server.analysis.summarise import (
        SummaryResponseError, parse_summary_response,
    )
    raw = """{
      "summary": "ok",
      "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 7},
      "top_improvements": ["a", "b", "c"],
      "strengths": ["x", "y"],
      "key_moments": [
        {"section_id": "sec1", "note": "first"},
        {"section_id": "sec2", "note": "second"},
        {"section_id": "sec3", "note": "third"}
      ]
    }"""
    out = parse_summary_response(raw, {"sec1", "sec2", "sec3"})
    assert out["key_moments"][0]["section_id"] == "sec1"

    with pytest.raises(SummaryResponseError):
        parse_summary_response(raw, {"sec1", "sec2"})  # sec3 unknown
```

**Delete** any `test_compute_distribution_*` tests and imports of `compute_distribution` from this file.

- [ ] **Step 2: Run to verify failure**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_summarise.py -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `server/analysis/summarise.py`**

Delete `compute_distribution` and `CATEGORY_EMOJI` (no callers remain post-Task 11-13 — see forward-step notes). Rewrite `build_summary_prompt` + `parse_summary_response`.

Full replacement for the file:

```python
"""Pure helpers for the summary step — no IO, no subprocess.

- build_summary_prompt: assembles the Claude coach-summary prompt (sections in).
- parse_summary_response: validates Claude's JSON output.
"""
from __future__ import annotations

import json


class SummaryResponseError(Exception):
    """Raised when Claude's summary output fails schema or reference validation."""


_OUTPUT_SCHEMA_HINT = (
    'Output ONE JSON object with this exact shape — no prose, no markdown fences:\n'
    '{\n'
    '  "summary": "<one-sentence summary>",\n'
    '  "scores": {\n'
    '    "guard_retention": <integer 0..10>,\n'
    '    "positional_awareness": <integer 0..10>,\n'
    '    "transition_quality": <integer 0..10>\n'
    '  },\n'
    '  "top_improvements": ["<sentence>", "<sentence>", "<sentence>"],\n'
    '  "strengths": ["<short phrase>", ...],\n'
    '  "key_moments": [\n'
    '    {"section_id": "<from the list above>", "note": "<brief pointer sentence>"},\n'
    '    {"section_id": "<...>", "note": "<...>"},\n'
    '    {"section_id": "<...>", "note": "<...>"}\n'
    '  ]\n'
    '}'
)


def _format_mm_ss(seconds: float) -> str:
    total = int(round(seconds))
    m = total // 60
    s = total % 60
    return f"{m}:{s:02d}"


def build_summary_prompt(
    roll_row: dict,
    sections: list[dict],
    annotations_by_section: dict[str, list[dict]],
) -> str:
    """Construct the summary prompt for Claude (M9b section-based)."""
    a_name = roll_row["player_a_name"]
    b_name = roll_row["player_b_name"]
    duration_s = roll_row.get("duration_s") or 0.0
    date = roll_row.get("date", "")

    preamble = (
        f"You are a BJJ coach reviewing a roll. Analyse the sections below and produce "
        f"a concise coaching report. The practitioner is {a_name} (the person being coached); "
        f"{b_name} is their partner."
    )
    analysed_count = sum(1 for s in sections if (s.get("narrative") or "").strip())
    meta = (
        f"Roll metadata:\n"
        f"- Duration: {_format_mm_ss(duration_s)}\n"
        f"- Date: {date}\n"
        f"- Total sections analysed: {analysed_count}"
    )

    section_blocks: list[str] = []
    for s in sections:
        narrative = (s.get("narrative") or "").strip()
        if not narrative:
            continue
        start = _format_mm_ss(s["start_s"])
        end = _format_mm_ss(s["end_s"])
        coach_tip = (s.get("coach_tip") or "").strip()
        notes = annotations_by_section.get(s["id"], [])
        block = [
            f"Section section_id={s['id']} ({start} – {end}):",
            f"  Narrative: {narrative}",
        ]
        if coach_tip:
            block.append(f"  Coach tip: {coach_tip}")
        if notes:
            block.append(f"  {a_name}'s notes:")
            for note in notes:
                body = (note["body"] or "").replace("\n", " ").strip()
                block.append(f"    - {body}")
        section_blocks.append("\n".join(block))

    if section_blocks:
        sections_block = "Per-section analyses (chronological):\n" + "\n\n".join(section_blocks)
    else:
        sections_block = "Per-section analyses (chronological):\n(no sections analysed)"

    return "\n\n".join([preamble, meta, sections_block, _OUTPUT_SCHEMA_HINT])


_REQUIRED_SCORES = ("guard_retention", "positional_awareness", "transition_quality")


def _clamp_score(value) -> int:
    if isinstance(value, bool):
        raise SummaryResponseError(f"score must not be a bool: {value!r}")
    if not isinstance(value, (int, float)):
        raise SummaryResponseError(f"score is not a number: {value!r}")
    return max(0, min(10, int(round(value))))


def parse_summary_response(raw: str, valid_section_ids: set[str]) -> dict:
    """Parse + validate Claude's summary JSON output. Raises SummaryResponseError."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SummaryResponseError(f"not valid JSON: {raw[:200]!r}") from exc

    if not isinstance(data, dict):
        raise SummaryResponseError(f"expected an object, got {type(data).__name__}")

    for key in ("summary", "scores", "top_improvements", "strengths", "key_moments"):
        if key not in data:
            raise SummaryResponseError(f"missing required key: {key}")

    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise SummaryResponseError("summary must be a non-empty string")

    scores = data["scores"]
    if not isinstance(scores, dict):
        raise SummaryResponseError("scores must be an object")
    for metric in _REQUIRED_SCORES:
        if metric not in scores:
            raise SummaryResponseError(f"missing score metric: {metric}")
    data["scores"] = {m: _clamp_score(scores[m]) for m in _REQUIRED_SCORES}

    ti = data["top_improvements"]
    if not isinstance(ti, list) or len(ti) != 3:
        raise SummaryResponseError("top_improvements must be a list of exactly 3 items")
    for item in ti:
        if not isinstance(item, str) or not item.strip():
            raise SummaryResponseError("each top_improvements item must be a non-empty string")

    st = data["strengths"]
    if not isinstance(st, list) or len(st) < 2 or len(st) > 4:
        raise SummaryResponseError("strengths must be a list of 2 to 4 items")
    for item in st:
        if not isinstance(item, str) or not item.strip():
            raise SummaryResponseError("each strengths item must be a non-empty string")

    km = data["key_moments"]
    if not isinstance(km, list) or len(km) != 3:
        raise SummaryResponseError("key_moments must be a list of exactly 3 items")
    seen: set[str] = set()
    for entry in km:
        if not isinstance(entry, dict):
            raise SummaryResponseError("each key_moments entry must be an object")
        sid = entry.get("section_id")
        note = entry.get("note")
        if not isinstance(sid, str) or not sid:
            raise SummaryResponseError("key_moments[*].section_id must be a non-empty string")
        if sid in seen:
            raise SummaryResponseError(f"duplicate key_moments section_id: {sid}")
        if sid not in valid_section_ids:
            raise SummaryResponseError(f"key_moments references unknown section_id: {sid}")
        if not isinstance(note, str) or not note.strip():
            raise SummaryResponseError("key_moments[*].note must be a non-empty string")
        seen.add(sid)

    return data
```

- [ ] **Step 4: Rewrite `server/api/summarise.py`**

Replace the file content with:

```python
"""POST /api/rolls/:id/summarise — one Claude call across all sections + annotations."""
from __future__ import annotations

import math
import time

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.analysis.claude_cli import (
    ClaudeProcessError,
    RateLimitedError,
    run_claude,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.analysis.summarise import (
    SummaryResponseError,
    build_summary_prompt,
    parse_summary_response,
)
from server.config import Settings, load_settings
from server.db import (
    connect,
    get_annotations_by_section,
    get_roll,
    get_sections_by_roll,
    set_summary_state,
)

router = APIRouter(prefix="/api", tags=["summarise"])


class _SummariseIn(BaseModel):
    pass


class _SummariseOut(BaseModel):
    finalised_at: int
    scores: dict


_SUMMARY_LIMITER: SlidingWindowLimiter | None = None


def _get_limiter(settings: Settings) -> SlidingWindowLimiter:
    global _SUMMARY_LIMITER
    if _SUMMARY_LIMITER is None:
        _SUMMARY_LIMITER = SlidingWindowLimiter(
            max_calls=settings.claude_max_calls,
            window_seconds=settings.claude_window_seconds,
        )
    return _SUMMARY_LIMITER


@router.post("/rolls/{roll_id}/summarise", response_model=_SummariseOut)
async def summarise_roll(
    roll_id: str,
    payload: _SummariseIn,
    settings: Settings = Depends(load_settings),
):
    conn = connect(settings.db_path)
    try:
        roll_row = get_roll(conn, roll_id)
        if roll_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        section_rows = [dict(s) for s in get_sections_by_roll(conn, roll_id)]
        annotations_by_section = {
            s["id"]: [dict(a) for a in get_annotations_by_section(conn, s["id"])]
            for s in section_rows
        }
    finally:
        conn.close()

    analysed_sections = [s for s in section_rows if s.get("narrative")]
    if not analysed_sections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Roll has no analysed sections — analyse at least one section before finalising.",
        )

    prompt = build_summary_prompt(
        roll_row=dict(roll_row),
        sections=section_rows,
        annotations_by_section=annotations_by_section,
    )

    limiter = _get_limiter(settings)
    try:
        raw = await run_claude(prompt, settings=settings, limiter=limiter)
    except RateLimitedError as exc:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": f"Claude cooldown — {math.ceil(exc.retry_after_s)}s until next call",
                "retry_after_s": math.ceil(exc.retry_after_s),
            },
            headers={"Retry-After": str(math.ceil(exc.retry_after_s))},
        )
    except ClaudeProcessError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude subprocess failed: {exc}",
        )

    valid_section_ids = {s["id"] for s in section_rows}
    try:
        parsed = parse_summary_response(raw, valid_section_ids)
    except SummaryResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude gave malformed output: {exc}",
        )

    now = int(time.time())
    conn = connect(settings.db_path)
    try:
        set_summary_state(conn, roll_id=roll_id, scores_payload=parsed, finalised_at=now)
    finally:
        conn.close()

    return _SummariseOut(finalised_at=now, scores=parsed)
```

- [ ] **Step 5: Update `test_api_summarise.py`**

Open `tools/bjj-app/tests/backend/test_api_summarise.py`, replace any `insert_moments` / `insert_analyses` / `insert_annotation(moment_id=...)` fixture seed calls with the new section-based seeding:

```python
from server.db import insert_section, update_section_analysis, insert_annotation
# ...
sec = insert_section(conn, roll_id=..., start_s=3.0, end_s=7.0, sample_interval_s=1.0)
update_section_analysis(
    conn, section_id=sec["id"],
    narrative="Greig recovers guard.",
    coach_tip="Stay elbows in.",
    analysed_at=1713700000,
)
insert_annotation(conn, section_id=sec["id"], body="triangle was there", created_at=1713700050)
```

Update the Claude stub response to include `section_id` in `key_moments` instead of `moment_id`, using the section's id.

If the existing file has assertions on `distribution` in the response — delete them; the M9b endpoint no longer returns `distribution`.

- [ ] **Step 6: Run all summarise tests**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_summarise.py tests/backend/test_api_summarise.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/bjj-app/server/analysis/summarise.py tools/bjj-app/server/api/summarise.py tools/bjj-app/tests/backend/test_summarise.py tools/bjj-app/tests/backend/test_api_summarise.py
git commit -m "feat(bjj-app): M9b summarise rewrite — sections in, section_id key_moments, no distribution"
```

---

## Task 11: Vault writer — drop position_distribution, render by section

**Files:**
- Modify: `tools/bjj-app/server/analysis/vault_writer.py`
- Modify: `tools/bjj-app/tests/backend/test_vault_writer_summary.py`
- Modify: `tools/bjj-app/tests/backend/test_vault_writer.py` (if it asserts distribution)

- [ ] **Step 1: Update the tests**

In `tools/bjj-app/tests/backend/test_vault_writer_summary.py`:
- Delete every test that asserts `position_distribution` or `CATEGORY_EMOJI` rendering.
- Update `render_summary_sections` call sites to the new signature (no `distribution`, no `categories`, sections instead of moments).
- `render_your_notes` is now keyed by section range — fixture rows must carry `section_id / start_s / end_s` instead of `moment_id / timestamp_s`. Assert headers are `### 0:03 – 0:07`.
- Add assertions for `## Key Moments` range rendering: `- **0:03 – 0:07** — <note>`.

Keep representative tests like:

```python
def test_render_summary_sections_has_no_position_distribution_key():
    from server.analysis.vault_writer import render_summary_sections
    out = render_summary_sections(
        scores_payload={
            "summary": "ok",
            "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 7},
            "top_improvements": ["a", "b", "c"],
            "strengths": ["x", "y"],
            "key_moments": [
                {"section_id": "sec1", "note": "n1"},
                {"section_id": "sec2", "note": "n2"},
                {"section_id": "sec3", "note": "n3"},
            ],
        },
        sections=[
            {"id": "sec1", "start_s": 3.0, "end_s": 7.0},
            {"id": "sec2", "start_s": 15.0, "end_s": 22.0},
            {"id": "sec3", "start_s": 30.0, "end_s": 34.0},
        ],
    )
    assert "position_distribution" not in out
    assert "0:03 – 0:07" in out["key_moments"]


def test_render_your_notes_groups_by_section_range():
    from server.analysis.vault_writer import render_your_notes
    rows = [
        {"section_id": "sec1", "start_s": 3.0, "end_s": 7.0,
         "body": "first", "created_at": 100},
        {"section_id": "sec1", "start_s": 3.0, "end_s": 7.0,
         "body": "second", "created_at": 200},
        {"section_id": "sec2", "start_s": 15.0, "end_s": 22.0,
         "body": "third", "created_at": 50},
    ]
    out = render_your_notes(rows)
    assert "### 0:03 – 0:07" in out
    assert "### 0:15 – 0:22" in out
    # Still ordered by section start_s asc
    assert out.index("### 0:03") < out.index("### 0:15")
```

Inspect `test_vault_writer.py` for any `render_your_notes` row shapes using `moment_id` / `timestamp_s` — update them to `section_id` / `start_s` / `end_s`.

- [ ] **Step 2: Run to verify failure**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_vault_writer_summary.py tests/backend/test_vault_writer.py -v`
Expected: FAIL.

- [ ] **Step 3: Update `server/analysis/vault_writer.py`**

Changes required (apply each):

1. Remove the `compute_distribution` import and `CATEGORY_EMOJI` import; drop the `_SUMMARY_SECTION_ORDER` `position_distribution` entry. New order:

```python
_SUMMARY_SECTION_ORDER: list[tuple[str, str]] = [
    ("summary", "## Summary"),
    ("scores", "## Scores"),
    ("key_moments", "## Key Moments"),
    ("top_improvements", "## Top Improvements"),
    ("strengths", "## Strengths Observed"),
]
```

2. Rewrite `render_your_notes` to group by `(start_s, end_s)` (section range) instead of `moment_id`. Replace body:

```python
def render_your_notes(rows: Iterable) -> str:
    """Render annotation rows grouped by section range under H3 headers.

    Input row shape: keys `section_id`, `start_s`, `end_s`, `body`, `created_at`.
    """
    rows_list: list = list(rows)
    if not rows_list:
        return ""
    rows_list.sort(key=lambda r: (_row_get(r, "start_s"), _row_get(r, "created_at")))
    sections: list[str] = []
    current_section_id: str | None = None
    current_bullets: list[str] = []
    current_header = ""

    def flush() -> None:
        if current_section_id is None:
            return
        sections.append(current_header + "\n" + "\n".join(current_bullets))

    for row in rows_list:
        sid = _row_get(row, "section_id")
        if sid != current_section_id:
            flush()
            current_bullets = []
            current_section_id = sid
            start = _format_mm_ss(_row_get(row, "start_s"))
            end = _format_mm_ss(_row_get(row, "end_s"))
            current_header = f"### {start} – {end}"
        ts = _format_created_stamp(_row_get(row, "created_at"))
        body = _row_get(row, "body")
        current_bullets.append(f"- _({ts})_ {body}")
    flush()
    return "\n\n".join(sections)
```

3. Replace `render_summary_sections` signature + body to take `sections` instead of `distribution`, `categories`, `moments`. Key moments resolve by `section_id`; distribution block deleted.

```python
def render_summary_sections(
    scores_payload: dict,
    sections: list[dict],
) -> dict[str, str]:
    """Render summary-owned section bodies. No Position Distribution post-M9b."""
    section_by_id = {s["id"]: s for s in sections}
    summary = scores_payload["summary"].strip()

    scores = scores_payload["scores"]
    score_rows = [
        "| Metric                 | Score |",
        "| ---------------------- | ----- |",
    ] + [
        f"| {label:<22} | {scores[metric]}/10  |"
        for metric, label in _SCORE_METRIC_LABELS
    ]
    scores_body = "\n".join(score_rows)

    km_lines: list[str] = []
    for km in scores_payload["key_moments"]:
        sec = section_by_id.get(km["section_id"])
        if sec is None:
            label = "?:??"
        else:
            label = f"{_format_mm_ss(sec['start_s'])} – {_format_mm_ss(sec['end_s'])}"
        km_lines.append(f"- **{label}** — {km['note']}")
    key_moments_body = "\n".join(km_lines)

    ti_lines = [f"{i + 1}. {item}" for i, item in enumerate(scores_payload["top_improvements"])]
    top_improvements_body = "\n".join(ti_lines)
    st_lines = [f"- {item}" for item in scores_payload["strengths"]]
    strengths_body = "\n".join(st_lines)

    return {
        "summary": summary,
        "scores": scores_body,
        "key_moments": key_moments_body,
        "top_improvements": top_improvements_body,
        "strengths": strengths_body,
    }
```

4. Rewrite `publish()` to use sections instead of moments+analyses:

Replace the finalised-block of `publish`. Delete:

```python
import json as _json
scores_payload = _json.loads(roll_row["scores_json"])
moment_rows = get_moments(conn, roll_id)
flat_analyses = [...]
distribution = compute_distribution(...)
summary_section_bodies = render_summary_sections(...)
```

With:

```python
import json as _json
scores_payload = _json.loads(roll_row["scores_json"])
section_rows = [dict(s) for s in get_sections_by_roll(conn, roll_id)]
summary_section_bodies = render_summary_sections(
    scores_payload=scores_payload,
    sections=section_rows,
)
summary_hashes = {k: _hash_section(v) for k, v in summary_section_bodies.items()}
```

And drop the `taxonomy` requirement: `publish()` no longer needs taxonomy for distribution. Change the signature default to `taxonomy: dict | None = None` kept for backward compat; don't raise if `taxonomy is None` anymore (delete the `if taxonomy is None: raise ValueError(...)` block).

5. Update the `db.py` imports at the top of `vault_writer.py` — remove `get_analyses`, `get_moments`, add `get_sections_by_roll`:

```python
from server.db import (
    get_annotations_by_roll,
    get_roll,
    get_sections_by_roll,
    get_vault_state,
    set_vault_state,
    set_vault_summary_hashes,
)
```

Drop the unused `from server.analysis.summarise import CATEGORY_EMOJI, compute_distribution` line.

- [ ] **Step 4: Run tests**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_vault_writer_summary.py tests/backend/test_vault_writer.py tests/backend/test_vault_writer_report.py -v`
Expected: all PASS. Fix any residual distribution assertions.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/analysis/vault_writer.py tools/bjj-app/tests/backend/test_vault_writer_summary.py tools/bjj-app/tests/backend/test_vault_writer.py
git commit -m "feat(bjj-app): M9b vault writer — key_moments by section, your_notes by range, drop position_distribution"
```

---

## Task 12: PDF export — key_moments by section, conditional distribution block

**Files:**
- Modify: `tools/bjj-app/server/export/pdf.py`
- Modify: `tools/bjj-app/server/export/templates/report.html.j2`
- Modify: `tools/bjj-app/server/api/export_pdf.py`
- Modify: `tools/bjj-app/tests/backend/test_export_pdf.py`
- Modify: `tools/bjj-app/tests/backend/test_api_export_pdf.py`

- [ ] **Step 1: Update the tests**

In `test_export_pdf.py`, update `build_report_context` fixtures: `scores.key_moments[*]` uses `section_id`, and pass a `sections` list (not `moments`). Distribution is empty. Add:

```python
def test_build_report_context_key_moments_resolve_by_section_id():
    from datetime import datetime, timezone
    from server.export.pdf import build_report_context
    roll = {
        "id": "abcdef0123", "title": "T", "date": "2026-04-22",
        "player_a_name": "A", "player_b_name": "B", "duration_s": 60.0,
    }
    scores = {
        "summary": "S",
        "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["a", "b", "c"],
        "strengths": ["x", "y"],
        "key_moments": [{"section_id": "sec1", "note": "n1"}],
    }
    sections = [{"id": "sec1", "start_s": 3.0, "end_s": 7.0}]
    ctx = build_report_context(
        roll=roll, scores=scores, sections=sections,
        generated_at=datetime.now(timezone.utc),
    )
    assert ctx["distribution_bar"] == []
    assert ctx["key_moments"][0]["timestamp_human"] == "00:03"


def test_render_report_pdf_omits_distribution_section_when_empty():
    """Empty distribution_bar must not produce an empty Position Flow block."""
    from datetime import datetime, timezone
    from server.export.pdf import build_report_context, render_report_pdf
    ctx = build_report_context(
        roll={
            "id": "x" * 16, "title": "T", "date": "2026-04-22",
            "player_a_name": "A", "player_b_name": "B", "duration_s": 60.0,
        },
        scores={
            "summary": "S",
            "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 7},
            "top_improvements": ["a", "b", "c"],
            "strengths": ["x", "y"],
            "key_moments": [],
        },
        sections=[],
        generated_at=datetime.now(timezone.utc),
    )
    pdf = render_report_pdf(ctx)
    assert pdf[:4] == b"%PDF"
```

Delete any other tests asserting `distribution_bar` has entries.

- [ ] **Step 2: Run to verify failure**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_export_pdf.py -v`
Expected: FAIL (signature mismatch).

- [ ] **Step 3: Rewrite `build_report_context` in `server/export/pdf.py`**

Replace the signature + body (keep all other helpers in the file untouched):

```python
def build_report_context(
    *,
    roll: dict,
    scores: dict | None,
    sections: list[dict],
    generated_at: datetime,
) -> dict:
    """Flatten DB state into the exact shape the Jinja template expects.

    M9b: no distribution data available; key_moments resolve by section_id.
    """
    if scores is None:
        raise ValueError("build_report_context requires a non-null `scores` payload")

    section_by_id = {s["id"]: s for s in sections}

    date_human = datetime.strptime(roll["date"], "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")

    score_rows: list[dict] = []
    for score_id, label in _SCORE_LABEL_BY_ID.items():
        value = int(scores["scores"].get(score_id, 0))
        score_rows.append({
            "id": score_id,
            "label": label,
            "value": value,
            "bar_pct": value * 10,
            "color_bucket": _bucket_for(value),
        })

    key_moments: list[dict] = []
    for km in scores.get("key_moments", []):
        sid = km.get("section_id")
        sec = section_by_id.get(sid)
        if sec is None:
            continue
        key_moments.append({
            "timestamp_human": format_mm_ss(sec["start_s"]),
            "category_label": f"{format_mm_ss(sec['start_s'])}–{format_mm_ss(sec['end_s'])}",
            "blurb": km.get("note", ""),
        })

    return {
        "title": roll["title"],
        "date_human": date_human,
        "player_a_name": roll["player_a_name"],
        "player_b_name": roll["player_b_name"],
        "duration_human": format_mm_ss(roll.get("duration_s") or 0),
        "moments_analysed_count": sum(1 for s in sections if s.get("narrative")),
        "summary_sentence": scores.get("summary", ""),
        "scores": score_rows,
        "distribution_bar": [],
        "improvements": list(scores.get("top_improvements", [])),
        "strengths": list(scores.get("strengths", [])),
        "key_moments": key_moments,
        "generated_at_human": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "roll_id_short": roll["id"][:8],
    }
```

- [ ] **Step 4: Guard the template block**

In `tools/bjj-app/server/export/templates/report.html.j2`, wrap lines 36–45 in a `{% if distribution_bar %}` / `{% endif %}` block:

```jinja
{% if distribution_bar %}
<section class="distribution">
  <h2>Position flow</h2>
  <div class="dist-bar">
    {% for seg in distribution_bar %}
    <div class="dist-seg {{ seg.color_class }}" style="width: {{ seg.width_pct }}%;">
      <span class="dist-label">{{ seg.label }} {{ seg.width_pct }}%</span>
    </div>
    {% endfor %}
  </div>
</section>
{% endif %}
```

- [ ] **Step 5: Update `server/api/export_pdf.py`**

Replace the `moment_rows` + `flat_analyses` + `compute_distribution` + `moments_with_cat` block with a sections lookup:

```python
conn = connect(settings.db_path)
try:
    roll_row = get_roll(conn, roll_id)
    if roll_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found."
        )
    if roll_row["scores_json"] is None or roll_row["finalised_at"] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Roll must be finalised before export.",
        )
    scores_payload = _json.loads(roll_row["scores_json"])
    section_rows = [dict(s) for s in get_sections_by_roll(conn, roll_id)]
finally:
    conn.close()

generated_at = datetime.now(timezone.utc)
context = build_report_context(
    roll=dict(roll_row),
    scores=scores_payload,
    sections=section_rows,
    generated_at=generated_at,
)
```

Update the imports at the top:

```python
from server.db import connect, get_roll, get_sections_by_roll
```

Drop `from server.analysis.summarise import compute_distribution`. Drop `taxonomy` handling entirely (no longer needed).

The `vault_publish` call: still pass `taxonomy=taxonomy` if the signature still accepts it (backward-compat), or drop it. Per Task 11 we made `taxonomy` optional and unused, so pass nothing:

```python
vault_publish(
    conn,
    roll_id=roll_id,
    vault_root=settings.vault_root,
    force=force,
)
```

- [ ] **Step 6: Update `test_api_export_pdf.py`**

Swap `insert_moments` / `insert_analyses` seeding for `insert_section` + `update_section_analysis`. Ensure `scores_json` fixtures use `section_id` in `key_moments`.

- [ ] **Step 7: Run tests**

Run: `cd tools/bjj-app && python -m pytest tests/backend/test_export_pdf.py tests/backend/test_api_export_pdf.py tests/backend/test_export_pdf_template.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/bjj-app/server/export/pdf.py tools/bjj-app/server/export/templates/report.html.j2 tools/bjj-app/server/api/export_pdf.py tools/bjj-app/tests/backend/test_export_pdf.py tools/bjj-app/tests/backend/test_api_export_pdf.py
git commit -m "feat(bjj-app): M9b PDF export — key_moments by section, conditional Position Flow block"
```

---

## Task 13: Frontend types + api.ts

**Files:**
- Modify: `tools/bjj-app/web/src/lib/types.ts`
- Modify: `tools/bjj-app/web/src/lib/api.ts`

- [ ] **Step 1: Update `types.ts`**

Replace the `Section` interface and the `AnalyseEvent` and `KeyMoment` types:

```ts
export interface Section {
  id: string;
  start_s: number;
  end_s: number;
  sample_interval_s: number;
  narrative: string | null;
  coach_tip: string | null;
  analysed_at: number | null;
  annotations: Annotation[];
}

// RollDetail.distribution is always null post-M9b but kept in the type for
// backward compatibility with older clients. Do not render it.

export type AnalyseEvent =
  | { stage: 'section_started'; section_id: string; start_s: number; end_s: number; idx: number; total: number }
  | { stage: 'section_queued'; section_id: string; retry_after_s: number }
  | { stage: 'section_done'; section_id: string; start_s: number; end_s: number; narrative: string; coach_tip: string }
  | { stage: 'section_error'; section_id: string; error: string }
  | { stage: 'done'; total: number };

export type KeyMoment = {
  section_id: string;
  note: string;
};
```

(Keep `Moment` type as-is so any lingering UI still type-checks, but its `analyses` / `annotations` arrays will always be empty post-M9b.)

- [ ] **Step 2: Update `api.ts`**

Change `SectionInput` — `sample_interval_s` optional:

```ts
export interface SectionInput {
  start_s: number;
  end_s: number;
  sample_interval_s?: number;
}
```

Change `addAnnotation`:

```ts
export function addAnnotation(
  rollId: string,
  sectionId: string,
  body: string,
): Promise<Annotation> {
  return request<Annotation>(
    `/api/rolls/${encodeURIComponent(rollId)}/sections/${encodeURIComponent(sectionId)}/annotations`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    },
  );
}
```

Add `deleteSection`:

```ts
export async function deleteSection(rollId: string, sectionId: string): Promise<void> {
  const r = await fetch(
    `/api/rolls/${encodeURIComponent(rollId)}/sections/${encodeURIComponent(sectionId)}`,
    { method: 'DELETE' },
  );
  if (!r.ok) {
    throw new ApiError(r.status, `${r.status} ${r.statusText}`);
  }
}
```

Remove `analyseMoment` entirely — the per-moment analyse endpoint is deprecated along with the UI. Leave the route in the backend (`server/api/moments.py`) alone; we're just not calling it from the app.

- [ ] **Step 3: Typecheck frontend**

Run: `cd tools/bjj-app/web && npm run check` (or whatever the typecheck script is — check `package.json`; likely `svelte-check --tsconfig ./tsconfig.json`).
Expected: errors in `review/[id]/+page.svelte`, `MomentDetail.svelte`, `section-picker.test.ts`, `review-analyse.test.ts`, `scores-panel.test.ts`. These are expected — fixed in Tasks 14–17.

- [ ] **Step 4: Commit**

```bash
git add tools/bjj-app/web/src/lib/types.ts tools/bjj-app/web/src/lib/api.ts
git commit -m "feat(bjj-app): M9b frontend types — Section fields, new AnalyseEvent, section-level addAnnotation + deleteSection"
```

---

## Task 14: Frontend — `SectionCard` component + tests

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/SectionCard.svelte`
- Create: `tools/bjj-app/web/tests/section-card.test.ts`

- [ ] **Step 1: Write failing tests**

Create `tools/bjj-app/web/tests/section-card.test.ts`:

```ts
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import SectionCard from '../src/lib/components/SectionCard.svelte';

const baseSection = {
  id: 'sec1',
  start_s: 3.0,
  end_s: 7.0,
  sample_interval_s: 1.0,
  narrative: 'Player A passes to side control.',
  coach_tip: 'Stay heavy.',
  analysed_at: 1713700000,
  annotations: [],
};

describe('SectionCard', () => {
  it('renders timestamp range, narrative and coach tip', () => {
    render(SectionCard, {
      section: baseSection,
      busy: false,
      onSeek: vi.fn(),
      onDelete: vi.fn(),
      onAddAnnotation: vi.fn(),
    });
    expect(screen.getByText(/0:03\s*–\s*0:07/)).toBeInTheDocument();
    expect(screen.getByText('Player A passes to side control.')).toBeInTheDocument();
    expect(screen.getByText('Stay heavy.')).toBeInTheDocument();
  });

  it('clicking Seek fires onSeek with start_s', async () => {
    const onSeek = vi.fn();
    render(SectionCard, {
      section: baseSection, busy: false,
      onSeek, onDelete: vi.fn(), onAddAnnotation: vi.fn(),
    });
    await userEvent.click(screen.getByRole('button', { name: /seek/i }));
    expect(onSeek).toHaveBeenCalledWith(3.0);
  });

  it('clicking Delete fires onDelete with section_id', async () => {
    const onDelete = vi.fn();
    render(SectionCard, {
      section: baseSection, busy: false,
      onSeek: vi.fn(), onDelete, onAddAnnotation: vi.fn(),
    });
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(onDelete).toHaveBeenCalledWith('sec1');
  });

  it('shows "Analysing…" when narrative is null and busy', () => {
    render(SectionCard, {
      section: { ...baseSection, narrative: null, coach_tip: null, analysed_at: null },
      busy: true,
      onSeek: vi.fn(), onDelete: vi.fn(), onAddAnnotation: vi.fn(),
    });
    expect(screen.getByText(/analysing/i)).toBeInTheDocument();
  });

  it('submits a new annotation via textarea + Add button', async () => {
    const onAddAnnotation = vi.fn();
    render(SectionCard, {
      section: baseSection, busy: false,
      onSeek: vi.fn(), onDelete: vi.fn(), onAddAnnotation,
    });
    const user = userEvent.setup();
    await user.type(screen.getByRole('textbox', { name: /add note/i }), 'new note');
    await user.click(screen.getByRole('button', { name: /^add$/i }));
    expect(onAddAnnotation).toHaveBeenCalledWith('sec1', 'new note');
  });

  it('renders existing annotations as bullets', () => {
    render(SectionCard, {
      section: {
        ...baseSection,
        annotations: [
          { id: 'a1', body: 'triangle was there', created_at: 1713700000 },
          { id: 'a2', body: 'too eager', created_at: 1713700100 },
        ],
      },
      busy: false,
      onSeek: vi.fn(), onDelete: vi.fn(), onAddAnnotation: vi.fn(),
    });
    expect(screen.getByText('triangle was there')).toBeInTheDocument();
    expect(screen.getByText('too eager')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the failing tests**

Run: `cd tools/bjj-app/web && npx vitest run tests/section-card.test.ts`
Expected: FAIL (component does not exist).

- [ ] **Step 3: Create the component**

Create `tools/bjj-app/web/src/lib/components/SectionCard.svelte`:

```svelte
<script lang="ts">
  import type { Section } from '$lib/types';

  let {
    section,
    busy,
    onSeek,
    onDelete,
    onAddAnnotation,
  }: {
    section: Section;
    busy: boolean;
    onSeek: (start_s: number) => void;
    onDelete: (section_id: string) => void;
    onAddAnnotation: (section_id: string, body: string) => void;
  } = $props();

  let draft = $state('');

  function formatMmSs(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function onAdd() {
    const body = draft.trim();
    if (!body) return;
    onAddAnnotation(section.id, body);
    draft = '';
  }
</script>

<section class="space-y-3 rounded-lg border border-white/10 bg-white/[0.02] p-4">
  <header class="flex items-center justify-between gap-2">
    <span class="font-mono tabular-nums text-white/85">
      {formatMmSs(section.start_s)} – {formatMmSs(section.end_s)}
    </span>
    <div class="flex gap-2">
      <button
        type="button"
        class="rounded border border-white/15 bg-white/[0.04] px-2 py-0.5 text-xs text-white/75 hover:bg-white/[0.08]"
        onclick={() => onSeek(section.start_s)}
      >
        Seek
      </button>
      <button
        type="button"
        class="rounded border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-xs text-rose-100 hover:bg-rose-500/25"
        onclick={() => onDelete(section.id)}
      >
        Delete
      </button>
    </div>
  </header>

  {#if section.narrative}
    <p class="text-sm leading-relaxed text-white/85">{section.narrative}</p>
    {#if section.coach_tip}
      <div class="rounded-md border border-blue-400/30 bg-blue-500/10 px-3 py-2 text-xs text-blue-100">
        <span class="font-semibold">Coach tip:</span> {section.coach_tip}
      </div>
    {/if}
  {:else if busy}
    <p class="text-xs text-white/55">Analysing…</p>
  {:else}
    <p class="text-xs text-white/55">Not analysed yet.</p>
  {/if}

  {#if section.annotations.length > 0}
    <ul class="list-disc space-y-1 pl-5 text-xs text-white/75">
      {#each section.annotations as ann (ann.id)}
        <li>{ann.body}</li>
      {/each}
    </ul>
  {/if}

  <div class="flex gap-2">
    <label class="sr-only" for="ann-{section.id}">Add note</label>
    <textarea
      id="ann-{section.id}"
      aria-label="Add note"
      class="flex-1 rounded-md border border-white/10 bg-black/30 px-2 py-1 text-xs text-white/85"
      rows="2"
      bind:value={draft}
    ></textarea>
    <button
      type="button"
      class="self-end rounded-md border border-emerald-400/40 bg-emerald-500/15 px-3 py-1 text-xs text-emerald-100 hover:bg-emerald-500/25"
      onclick={onAdd}
    >
      Add
    </button>
  </div>
</section>
```

- [ ] **Step 4: Run tests**

Run: `cd tools/bjj-app/web && npx vitest run tests/section-card.test.ts`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/web/src/lib/components/SectionCard.svelte tools/bjj-app/web/tests/section-card.test.ts
git commit -m "feat(bjj-app): M9b SectionCard component + tests"
```

---

## Task 15: Frontend — SectionPicker drop density dropdown; nav un-link /graph; ScoresPanel conditional distribution

**Files:**
- Modify: `tools/bjj-app/web/src/lib/components/SectionPicker.svelte`
- Modify: `tools/bjj-app/web/src/routes/+layout.svelte`
- Modify: `tools/bjj-app/web/src/lib/components/ScoresPanel.svelte`
- Modify: `tools/bjj-app/web/tests/section-picker.test.ts`
- Modify: `tools/bjj-app/web/tests/scores-panel.test.ts`

- [ ] **Step 1: Update SectionPicker tests**

Open `tools/bjj-app/web/tests/section-picker.test.ts`. Delete the test that asserts on the density `<select>` (look for `'1s'`, `'0.5s'`, or `/density/i`). Keep tests for Mark start / Mark end / Analyse.

- [ ] **Step 2: Strip density from `SectionPicker.svelte`**

Remove the `<label><select>...1s/0.5s/2s...</select></label>` block from the template. In the script, remove `onDensityChange`. Keep `sample_interval_s: 1.0` in the staged section object so the API payload still type-checks, but don't render a chooser.

The `onAnalyse` callback still receives `SectionInput[]` — ok, `sample_interval_s: 1.0` is harmless (backend ignores it).

- [ ] **Step 3: Remove /graph nav link from `+layout.svelte`**

Delete this block:

```html
<a
  class="px-3 py-1.5 rounded-md hover:bg-white/5 text-white/70 hover:text-white transition-colors"
  href="/graph"
>
  Graph
</a>
```

The `/graph` route file stays — only the nav link disappears.

- [ ] **Step 4: Update `ScoresPanel.svelte`**

In the script:
- Replace `moments: Moment[]` prop with `sections: Section[]` + `rollId: string`. Update `momentsById` → `sectionsById`.
- `formatMmSs` stays but `key_moments` loop looks up `km.section_id` → section → show range `start–end`.
- `ongoto(momentId)` signature stays semantically — rename to `ongoto(sectionId: string)` and pass the section_id through.

Template change:

```svelte
{#each scores.key_moments as km, i (i)}
  {@const section = sectionsById.get(km.section_id)}
  <li class="flex items-start justify-between gap-3">
    <div class="flex-1">
      <span class="font-mono tabular-nums text-white/60">
        {section ? `${formatMmSs(section.start_s)} – ${formatMmSs(section.end_s)}` : '?:??'}
      </span>
      <span class="ml-1 text-white/40">—</span>
      <span class="ml-1">{km.note}</span>
    </div>
    <button
      type="button"
      onclick={() => ongoto(km.section_id)}
      aria-label="Go to section"
      class="..."
    >
      Go to →
    </button>
  </li>
{/each}
```

- [ ] **Step 5: Update `scores-panel.test.ts`**

Swap `moments: [...]` fixture for `sections: [...]`. Update `key_moments` entries to use `section_id`. Drop any distribution-related assertions.

- [ ] **Step 6: Run frontend tests**

Run: `cd tools/bjj-app/web && npx vitest run tests/section-picker.test.ts tests/scores-panel.test.ts`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/bjj-app/web/src/lib/components/SectionPicker.svelte tools/bjj-app/web/src/routes/+layout.svelte tools/bjj-app/web/src/lib/components/ScoresPanel.svelte tools/bjj-app/web/tests/section-picker.test.ts tools/bjj-app/web/tests/scores-panel.test.ts
git commit -m "feat(bjj-app): M9b SectionPicker drops density; /graph nav hidden; ScoresPanel key_moments by section"
```

---

## Task 16: Frontend — review page rewrite (SectionCard list, new SSE, queued banner)

**Files:**
- Modify: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`
- Modify: `tools/bjj-app/web/tests/review-analyse.test.ts`
- Delete: `tools/bjj-app/web/src/lib/components/MomentDetail.svelte`
- Delete: `tools/bjj-app/web/tests/moment-detail.test.ts`

- [ ] **Step 1: Rewrite `review-analyse.test.ts`**

Replace SSE mock events with the new shape:

```ts
body: sseBody([
  { stage: 'section_started', section_id: 'sec-a', start_s: 3.0, end_s: 5.0, idx: 0, total: 1 },
  { stage: 'section_done',    section_id: 'sec-a', start_s: 3.0, end_s: 5.0,
    narrative: 'A passes to side control.', coach_tip: 'Stay heavy.' },
  { stage: 'done', total: 1 },
]),
```

Drop assertions looking for time chips (`/0:03/`, `/0:04/`) — replace with assertions on the narrative text or the section card.

Example: after clicking Analyse ranges, expect:

```ts
await waitFor(() => {
  expect(screen.getByText('A passes to side control.')).toBeInTheDocument();
  expect(screen.getByText('Stay heavy.')).toBeInTheDocument();
});
```

Drop the "renders existing moments as chips" test entirely — moments don't render. Replace with "renders existing sections as cards when the roll was already analysed":

```ts
it('renders existing sections as cards when the roll was already analysed', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        ...detailWithoutMoments(),
        sections: [
          {
            id: 's1', start_s: 3.0, end_s: 7.0, sample_interval_s: 1.0,
            narrative: 'Existing narrative.', coach_tip: 'Keep elbows tight.',
            analysed_at: 1713700000, annotations: [],
          },
        ],
      }),
    }),
  );
  render(Page);
  await waitFor(() => {
    expect(screen.getByText('Existing narrative.')).toBeInTheDocument();
  });
});
```

Add a test for the queued banner:

```ts
it('shows queued banner on section_queued and clears on next section_started', async () => {
  const fetchMock = vi.fn();
  fetchMock.mockResolvedValueOnce({
    ok: true, status: 200, json: async () => detailWithoutMoments(),
  });
  fetchMock.mockRejectedValueOnce(new Error('graph not needed'));
  fetchMock.mockResolvedValueOnce({
    ok: true, status: 200,
    body: sseBody([
      { stage: 'section_queued', section_id: 'sec-a', retry_after_s: 7 },
      { stage: 'section_started', section_id: 'sec-a', start_s: 3.0, end_s: 5.0, idx: 0, total: 1 },
      { stage: 'section_done', section_id: 'sec-a', start_s: 3.0, end_s: 5.0,
        narrative: 'A passes.', coach_tip: 'Tight.' },
      { stage: 'done', total: 1 },
    ]),
  });
  vi.stubGlobal('fetch', fetchMock);

  const user = userEvent.setup();
  render(Page);
  await waitFor(() => expect(screen.getByText('Review M9 test')).toBeInTheDocument());

  const video = document.querySelector('video') as HTMLVideoElement;
  Object.defineProperty(video, 'currentTime', { writable: true, value: 3 });
  await user.click(screen.getByRole('button', { name: /mark start/i }));
  Object.defineProperty(video, 'currentTime', { writable: true, value: 5 });
  await user.click(screen.getByRole('button', { name: /mark end/i }));
  await user.click(screen.getByRole('button', { name: /analyse ranges/i }));

  await waitFor(() => expect(screen.getByText('A passes.')).toBeInTheDocument());
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd tools/bjj-app/web && npx vitest run tests/review-analyse.test.ts`
Expected: FAIL.

- [ ] **Step 3: Rewrite `review/[id]/+page.svelte`**

Major changes — apply each:

1. **Imports:** remove `GraphCluster`, `MomentDetail`, `getGraph`, `getGraphPaths`; add `SectionCard`; add `addAnnotation`, `deleteSection`.
2. **State:** drop `selectedMomentId`, `graphTaxonomy`, `graphPaths`, `hasAnyAnalyses` (re-derive from `sections`); add `queuedBanner: { sectionId: string; retryAfterS: number } | null`.
3. **`hasAnyAnalyses` derivation:** `roll?.sections?.some((s) => s.narrative != null) ?? false`.
4. **`onMount`:** drop `getGraph` / `getGraphPaths` calls and related try/catch.
5. **`onAnalyseSections`:** keep the fetch + SSE reader, switch to the new `AnalyseEvent` union.
6. **`handleAnalyseEvent`:** rewrite to handle new shape — on `section_started`, append a placeholder section to `roll.sections` if missing (narrative/coach_tip/analysed_at all null); on `section_queued` set `queuedBanner`; on `section_done` update the section in place with narrative/coach_tip/analysed_at = now; on `section_error` update the section with an error flag (use a local `errorBySectionId` map); on `done` progress is cleared.
7. **Delete** the chips loop block (`{#each roll.moments as moment ...}`).
8. **Delete** the `{#if selectedMoment}` block and the mini-graph block below.
9. **Add** a sections loop rendering `<SectionCard>`:

```svelte
{#if roll.sections && roll.sections.length > 0}
  <div class="space-y-3">
    {#each roll.sections as section (section.id)}
      <SectionCard
        {section}
        busy={analysing && section.narrative === null}
        onSeek={(t) => seek(t)}
        onDelete={(id) => onSectionDelete(id)}
        onAddAnnotation={(id, body) => onSectionAnnotate(id, body)}
      />
    {/each}
  </div>
{:else if !analysing}
  <div class="rounded-lg border border-white/10 bg-white/[0.02] p-6 text-center">
    <p class="text-sm text-white/60">No sections yet.</p>
    <p class="mt-1 text-xs text-white/35">
      Pick sections above by playing the video and clicking <strong>Mark start</strong> / <strong>Mark end</strong>, then click <strong>Analyse ranges</strong>.
    </p>
  </div>
{/if}
```

10. **Add** callbacks:

```ts
async function onSectionDelete(sectionId: string) {
  if (!roll) return;
  await deleteSection(roll.id, sectionId);
  roll.sections = roll.sections.filter((s) => s.id !== sectionId);
}

async function onSectionAnnotate(sectionId: string, body: string) {
  if (!roll) return;
  const ann = await addAnnotation(roll.id, sectionId, body);
  roll.sections = roll.sections.map((s) =>
    s.id === sectionId ? { ...s, annotations: [...s.annotations, ann] } : s,
  );
}

function seek(t: number) {
  if (!videoEl) return;
  videoEl.currentTime = t;
  void videoEl.play();
}
```

11. **Queued banner** — right below the existing `progress` banner:

```svelte
{#if queuedBanner}
  <div class="rounded-md border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100" role="status">
    Queued — Claude cooldown, retrying in {queuedBanner.retryAfterS}s…
  </div>
{/if}
```

12. **`onKeyMomentGoTo`:** change argument from `momentId` to `sectionId`; resolve section via `roll.sections` → seek to `section.start_s`.

```ts
function onKeyMomentGoTo(sectionId: string) {
  const section = roll?.sections.find((s) => s.id === sectionId);
  if (section) seek(section.start_s);
}
```

13. **ScoresPanel** call sites: pass `sections={roll.sections}` instead of `moments={roll.moments}`.

- [ ] **Step 4: Delete `MomentDetail.svelte` and its test**

```bash
rm tools/bjj-app/web/src/lib/components/MomentDetail.svelte
rm -f tools/bjj-app/web/tests/moment-detail.test.ts
```

- [ ] **Step 5: Run frontend tests**

Run: `cd tools/bjj-app/web && npx vitest run && npm run check`
Expected: all PASS (and typecheck clean).

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/web/src/routes/review/[id]/+page.svelte tools/bjj-app/web/tests/review-analyse.test.ts tools/bjj-app/web/src/lib/components/MomentDetail.svelte tools/bjj-app/web/tests/moment-detail.test.ts
git commit -m "feat(bjj-app): M9b review page — SectionCard list, new SSE handler, queued banner; drop MomentDetail + mini-graph"
```

---

## Task 17: Export-pdf frontend test + home test sweep

**Files:**
- Modify: `tools/bjj-app/web/tests/export-pdf.test.ts`
- Modify: any other test that references `moment_id` in `key_moments` fixtures

- [ ] **Step 1: Grep for `moment_id` in web/tests/**

Run:
```bash
grep -rn "moment_id" tools/bjj-app/web/tests/ tools/bjj-app/web/src/
```

- [ ] **Step 2: Replace with `section_id`**

For each match in test fixtures or ScoresPanel-related code: rename `moment_id` → `section_id` in `key_moments` fixtures.

For `export-pdf.test.ts`: update `key_moments` fixture entries to `{ section_id: 's1', note: '...' }` + add a `sections: [...]` array to the roll fixture if the test is hitting a path that needs it.

- [ ] **Step 3: Run all frontend tests**

Run: `cd tools/bjj-app/web && npx vitest run && npm run check`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tools/bjj-app/web/tests/export-pdf.test.ts
git commit -m "test(bjj-app): M9b frontend fixtures — section_id in key_moments"
```

---

## Task 18: README + full test sweep

**Files:**
- Modify: `tools/bjj-app/README.md`

- [ ] **Step 1: Update README**

Append an M9b line under the milestone log in `tools/bjj-app/README.md`. Find the existing M9 entry and insert below it:

```markdown
- **M9b — Section sequence analysis (2026-04-22).** Pivoted from per-frame classification to one Claude call per section with a multi-image narrative prompt. Annotations are now section-scoped; graph page hidden; `key_moments` resolve by `section_id`. See `docs/superpowers/specs/2026-04-22-bjj-app-m9b-section-sequence-analysis-design.md`.
```

Also update the prior M9 entry to include `(shipped)` where appropriate.

- [ ] **Step 2: Run full backend + frontend test sweep**

```bash
cd tools/bjj-app && python -m pytest
cd tools/bjj-app/web && npx vitest run && npm run check
```
Expected: all PASS, no unexpected errors.

- [ ] **Step 3: Manual smoke (per spec section "Manual smoke")**

Start the dev backend + frontend:

```bash
# terminal 1 — backend
cd tools/bjj-app && uvicorn server.main:app --reload
# terminal 2 — frontend
cd tools/bjj-app/web && npm run dev
```

Then in a browser at http://localhost:5173:

1. Upload a short clip.
2. Mark start 0:03 → Mark end 0:07. Chip shows `0:03 – 0:07`. Mark start 0:15 → Mark end 0:22. Second chip.
3. Click **Analyse ranges**. Progress shows `section_started` → `section_done` per section.
4. Both section cards appear with narrative + coach tip.
5. Click "Seek" on card 1 → video jumps to 0:03 and plays.
6. Add an annotation to card 1 → appears as a bullet.
7. Mark a third section. Click Analyse ranges again. Cards 1/2 narratives preserved; card 3 appears.
8. Click Finalise. ScoresPanel renders with key moments pointing at section ranges.
9. Save to Vault. Generated `Roll Log/<date> - <title>.md` contains `## Summary`, `## Scores`, `## Key Moments`, `## Top Improvements`, `## Strengths Observed`, `## Your Notes` (section-grouped), no `## Position Distribution`.
10. Export PDF. One-page report renders; no Position Flow bar; key moments listed with ranges.
11. Navigate to `/graph` directly — page still works; nav link is gone.

Any smoke-test failure: open an issue / fix in a follow-up task.

- [ ] **Step 4: Commit**

```bash
git add tools/bjj-app/README.md
git commit -m "docs(bjj-app): mark M9b (shipped) in README"
```

---

## Notes on ordering and cross-task dependencies

- Tasks 1–4 are self-contained DB work; run first.
- Task 5 (prompt) has no dependencies on 1–4 and could run in parallel; keep linear for review simplicity.
- Task 6 (pipeline) depends on 1, 2, 5.
- Task 7 (analyse API) depends on 6.
- Task 8 (annotations + delete API) depends on 1–4.
- Task 9 (rolls API) depends on 1, 3.
- Task 10 (summarise) depends on 1, 3.
- Task 11 (vault writer) depends on 10.
- Task 12 (PDF) depends on 10, 11.
- Tasks 13–17 (frontend) depend on 9 + 10 + 12 (API shape finalised).
- Task 18 is the final sweep.

After each task's tests pass, run the backend suite once (`python -m pytest tools/bjj-app/tests/backend/`) to catch any cross-file regressions before the next commit.
