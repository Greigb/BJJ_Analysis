# BJJ App M4 — Annotations + Vault Write-back Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user type append-only annotations on any moment (persisted to SQLite immediately), then explicitly click "Save to Vault" to publish the roll and all annotations to a Roll Log markdown file with H3-per-moment threading. Hash-based conflict detection on the `## Your Notes` section only, so edits in other sections of the markdown survive a publish.

**Architecture:** SQLite is the working store for annotations; the vault is the published form. A single new module `server/analysis/vault_writer.py` owns every write into `Roll Log/*.md` — it computes the `## Your Notes` body, surgically splices it into an existing file (preserving everything outside that section), and atomic-writes via `.tmp` + `os.replace`. Two new endpoints (`PATCH /rolls/:id/moments/:moment_id/annotations`, `POST /rolls/:id/publish`) expose these paths. Three new columns on `rolls` (`vault_path`, `vault_your_notes_hash`, `vault_published_at`) track publish state. Frontend gains a notes-thread + textarea inside `MomentDetail.svelte`, a `PublishConflictDialog.svelte`, and a "Save to Vault" button in the review page footer.

**Tech Stack:** SQLite with idempotent `PRAGMA table_info` + conditional `ALTER TABLE` for the schema migration. `python-frontmatter` (already installed) for reading frontmatter. Raw string formatting for writes to preserve exact whitespace. Python `hashlib.sha256`, `os.replace` for atomic writes. FastAPI `APIRouter` per endpoint. Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`) for the frontend, matching M3 patterns.

**Scope (M4 only):**
- Backend: `server/analysis/vault_writer.py`, `server/api/annotations.py`, `server/api/publish.py`.
- Extensions to: `server/db.py`, `server/main.py`, `server/api/rolls.py`, `server/analysis/vault.py`.
- DB schema: three new columns on `rolls`; existing `annotations` table reused as-is.
- `GET /api/rolls` summaries gain `roll_id` (from frontmatter).
- `GET /api/rolls/:id` gains `vault_path`, `vault_published_at`; each moment gains `annotations: [...]`.
- Frontend: new `PublishConflictDialog.svelte` + extensions to `MomentDetail.svelte`, `+page.svelte` (home), `review/[id]/+page.svelte`.
- Tests: vault_writer, annotations DB, vault-state DB, annotations API, publish API, extended vault tests for `roll_id`, extended MomentDetail tests, new conflict-dialog tests, extended home tests.

**Explicitly out of scope (per spec):**
- Edit / delete annotations (append-only in M4).
- Analyses serialized to vault (M6 will add these alongside the summary step).
- Retrofit of legacy vault-only markdown (stays visible but non-clickable).
- Upload flow changes — `POST /rolls` still doesn't create a markdown file.
- Three-way merge on conflict (terse dialog + git is the answer).

---

## File Structure

```
tools/bjj-app/
├── server/
│   ├── analysis/
│   │   ├── vault_writer.py             # NEW: publish() + render_your_notes() + slugify_filename() + ConflictError
│   │   └── vault.py                    # MODIFY: RollSummary gains roll_id
│   ├── api/
│   │   ├── annotations.py              # NEW: PATCH /api/rolls/:id/moments/:moment_id/annotations
│   │   ├── publish.py                  # NEW: POST /api/rolls/:id/publish
│   │   └── rolls.py                    # MODIFY: MomentOut.annotations, RollDetailOut.vault_path + vault_published_at, RollSummaryOut.roll_id
│   ├── db.py                           # MODIFY: schema migration + insert_annotation + get_annotations_by_* + set/get_vault_state
│   └── main.py                         # MODIFY: include annotations + publish routers
├── tests/backend/
│   ├── test_db_schema_migration.py     # NEW
│   ├── test_db_annotations.py          # NEW
│   ├── test_db_vault_state.py          # NEW
│   ├── test_vault_writer.py            # NEW
│   ├── test_api_annotations.py         # NEW
│   ├── test_api_publish.py             # NEW
│   └── test_vault.py                   # MODIFY: roll_id from frontmatter
└── web/
    ├── src/
    │   ├── lib/
    │   │   ├── api.ts                  # MODIFY: addAnnotation, publishRoll
    │   │   ├── types.ts                # MODIFY: Annotation; Moment.annotations; RollDetail.vault_path + vault_published_at; RollSummary.roll_id
    │   │   └── components/
    │   │       ├── MomentDetail.svelte              # MODIFY: notes thread + textarea
    │   │       └── PublishConflictDialog.svelte     # NEW
    │   └── routes/
    │       ├── +page.svelte                         # MODIFY: conditional link on roll_id
    │       └── review/[id]/+page.svelte             # MODIFY: Save to Vault button + conflict dialog wiring
    └── tests/
        ├── moment-detail.test.ts       # MODIFY: notes thread + textarea
        ├── publish-conflict.test.ts    # NEW
        └── home.test.ts                # MODIFY: clickable vs non-clickable tiles
```

### Responsibilities

- **`vault_writer.py`** — **SOLE** module that writes to `Roll Log/*.md`. Three pure helpers (`render_your_notes`, `slugify_filename`, `_compute_hash`) + one orchestrating `publish` that ties them together with SQLite reads/writes. Raises `ConflictError` on hash mismatch when `force=False`. Never reads/writes anything outside `vault_root/Roll Log/`. Security invariant: every write target resolves under `vault_root/Roll Log/`.
- **`api/annotations.py`** — Thin HTTP shell. One endpoint. Validates roll + moment exist, inserts annotation row, returns 201.
- **`api/publish.py`** — Thin HTTP shell. One endpoint. Loads settings, calls `vault_writer.publish`, translates `ConflictError` → HTTP 409 and `PublishResult` → 200.
- **`db.py`** — Append five new helpers + a schema migration function. The migration runs as part of `init_db` (idempotent).
- **`vault.py`** — One field added to `RollSummary`: `roll_id: str | None` from frontmatter. No other logic changes.
- **`MomentDetail.svelte`** — Extended with a notes thread (renders `moment.annotations`) + textarea (Cmd-Enter or button submits to PATCH).
- **`PublishConflictDialog.svelte`** — New component. Renders modal with Overwrite/Cancel. Callbacks to parent page.
- **Review page** — Adds "Save to Vault" button in the footer; wires 409 → dialog → force re-publish.
- **Home page** — Conditional anchor vs muted tile based on `roll.roll_id` presence.

### Annotation wire shape

```typescript
type Annotation = {
  id: string;
  body: string;
  created_at: number;   // unix seconds
};

// Extended:
type Moment = {
  id: string;
  frame_idx: number;
  timestamp_s: number;
  pose_delta: number | null;
  analyses: Analysis[];
  annotations: Annotation[];    // NEW
};

type RollDetail = {
  // ... existing fields ...
  vault_path: string | null;         // NEW — relative path under vault root, e.g. "Roll Log/2026-04-21 - ...md"
  vault_published_at: number | null; // NEW — unix seconds of last successful publish
};

type RollSummary = {
  // ... existing fields ...
  roll_id: string | null;   // NEW — from frontmatter. Present on M4+ markdown, null on legacy.
};

type AnalyseMomentEvent = /* unchanged from M3 */;
```

### Publish SSE / conflict shapes

```typescript
// POST /api/rolls/:id/publish — body: {force?: boolean}

// 200 OK
{ vault_path: string; your_notes_hash: string; vault_published_at: number }

// 409 Conflict
{ detail: string; current_hash: string; stored_hash: string }
```

---

## Task 1: Extend `rolls` table with three vault columns

**Files:**
- Modify: `tools/bjj-app/server/db.py`
- Create: `tools/bjj-app/tests/backend/test_db_schema_migration.py`

Schema migration is idempotent and backwards-compatible: existing databases get new columns added as NULL on next `init_db`.

- [ ] **Step 1: Write the failing test**

Create `tools/bjj-app/tests/backend/test_db_schema_migration.py`:

```python
"""Tests for the M4 schema migration (vault columns on rolls table)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from server.db import connect, init_db


def _rolls_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("PRAGMA table_info(rolls)")
        return {row[1] for row in cur.fetchall()}


def test_init_db_fresh_includes_vault_columns(tmp_path: Path):
    db_path = tmp_path / "fresh.db"
    init_db(db_path)
    cols = _rolls_columns(db_path)
    assert "vault_path" in cols
    assert "vault_your_notes_hash" in cols
    assert "vault_published_at" in cols


def test_init_db_migrates_pre_m4_schema(tmp_path: Path):
    """A database created before M4 (no vault_* columns) gets them added."""
    db_path = tmp_path / "premigrate.db"
    with sqlite3.connect(db_path) as conn:
        # Minimal pre-M4 rolls table — just the columns that existed before M4.
        conn.executescript(
            """
            CREATE TABLE rolls (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                video_path TEXT NOT NULL,
                duration_s REAL,
                partner TEXT,
                result TEXT,
                scores_json TEXT,
                finalised_at INTEGER,
                created_at INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO rolls (id, title, date, video_path, created_at) "
            "VALUES ('r1', 't', '2026-01-01', 'v.mp4', 1)"
        )
        conn.commit()

    # Should not raise; should add the columns to the existing rolls table.
    init_db(db_path)

    cols = _rolls_columns(db_path)
    assert "vault_path" in cols
    assert "vault_your_notes_hash" in cols
    assert "vault_published_at" in cols

    # Existing row is untouched, new columns are NULL.
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, vault_path, vault_your_notes_hash, vault_published_at "
            "FROM rolls WHERE id = 'r1'"
        ).fetchone()
    finally:
        conn.close()
    assert row["id"] == "r1"
    assert row["vault_path"] is None
    assert row["vault_your_notes_hash"] is None
    assert row["vault_published_at"] is None


def test_init_db_is_idempotent(tmp_path: Path):
    """Running init_db twice must not raise (no duplicate ALTER)."""
    db_path = tmp_path / "idem.db"
    init_db(db_path)
    init_db(db_path)  # must not raise
    cols = _rolls_columns(db_path)
    assert "vault_path" in cols
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_db_schema_migration.py -v
```

Expected: first two tests fail (columns not present); third may pass trivially but becomes meaningful once migration runs.

- [ ] **Step 3: Implement the migration in `server/db.py`**

Add the new columns to `SCHEMA_SQL` (so fresh DBs get them from `CREATE TABLE IF NOT EXISTS`):

Find the `CREATE TABLE IF NOT EXISTS rolls (...)` block at the top of `SCHEMA_SQL` and replace it with:

```sql
CREATE TABLE IF NOT EXISTS rolls (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    date TEXT NOT NULL,
    video_path TEXT NOT NULL,
    duration_s REAL,
    partner TEXT,
    result TEXT,
    scores_json TEXT,
    finalised_at INTEGER,
    created_at INTEGER NOT NULL,
    vault_path TEXT,
    vault_your_notes_hash TEXT,
    vault_published_at INTEGER
);
```

Then replace the `init_db` function with:

```python
_ROLLS_M4_COLUMNS: tuple[tuple[str, str], ...] = (
    ("vault_path", "TEXT"),
    ("vault_your_notes_hash", "TEXT"),
    ("vault_published_at", "INTEGER"),
)


def _migrate_rolls_m4(conn: sqlite3.Connection) -> None:
    """Idempotently add M4 columns to an existing rolls table.

    Only needed for databases created before M4 — CREATE TABLE IF NOT EXISTS
    above handles fresh installs. SQLite has no ADD COLUMN IF NOT EXISTS,
    so we inspect PRAGMA table_info and ALTER only when missing.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(rolls)").fetchall()}
    for name, sql_type in _ROLLS_M4_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE rolls ADD COLUMN {name} {sql_type}")


def init_db(db_path: Path) -> None:
    """Create the schema if it doesn't already exist. Safe to call every startup."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_rolls_m4(conn)
        conn.commit()
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_db_schema_migration.py -v
```

Expected: 3 passed.

Also run the full backend suite to confirm no regressions:
```bash
pytest tests/backend -v
```

Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_schema_migration.py
git commit -m "feat(bjj-app): add M4 vault_* columns to rolls with idempotent migration"
```

---

## Task 2: DB helpers — `set_vault_state` / `get_vault_state`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_db_vault_state.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/tests/backend/test_db_vault_state.py`:

```python
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
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_db_vault_state.py -v
```

Expected: ImportError on `get_vault_state` / `set_vault_state`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_db_vault_state.py
git commit -m "test(bjj-app): add vault-state db helper tests (failing — no impl)"
```

---

## Task 3: Implement `set_vault_state` / `get_vault_state`

**Files:**
- Modify: `tools/bjj-app/server/db.py`

- [ ] **Step 1: Append helpers to `db.py`**

Append to the end of `tools/bjj-app/server/db.py`:

```python


def set_vault_state(
    conn,
    *,
    roll_id: str,
    vault_path: str,
    vault_your_notes_hash: str,
    vault_published_at: int,
) -> None:
    """Record the outcome of a successful publish on the roll row."""
    conn.execute(
        """
        UPDATE rolls
           SET vault_path = ?,
               vault_your_notes_hash = ?,
               vault_published_at = ?
         WHERE id = ?
        """,
        (vault_path, vault_your_notes_hash, vault_published_at, roll_id),
    )
    conn.commit()


def get_vault_state(conn, roll_id: str) -> dict | None:
    """Return the roll's vault_path/hash/published_at, or None if the roll doesn't exist."""
    cur = conn.execute(
        "SELECT vault_path, vault_your_notes_hash, vault_published_at FROM rolls WHERE id = ?",
        (roll_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "vault_path": row["vault_path"],
        "vault_your_notes_hash": row["vault_your_notes_hash"],
        "vault_published_at": row["vault_published_at"],
    }
```

- [ ] **Step 2: Run — must pass**

```bash
pytest tests/backend/test_db_vault_state.py -v
```

Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py
git commit -m "feat(bjj-app): add set_vault_state / get_vault_state helpers"
```

---

## Task 4: DB helpers — annotations

**Files:**
- Create: `tools/bjj-app/tests/backend/test_db_annotations.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/tests/backend/test_db_annotations.py`:

```python
"""Tests for insert_annotation / get_annotations_by_moment / get_annotations_by_roll."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from server.db import (
    connect,
    create_roll,
    get_annotations_by_moment,
    get_annotations_by_roll,
    init_db,
    insert_annotation,
    insert_moments,
)


@pytest.fixture
def db_with_moments(tmp_path: Path):
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
        moments=[
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 7, "timestamp_s": 7.0, "pose_delta": 0.8},
        ],
    )
    try:
        yield conn, [m["id"] for m in moments]
    finally:
        conn.close()


def test_insert_annotation_persists_row(db_with_moments):
    conn, moment_ids = db_with_moments
    row = insert_annotation(
        conn, moment_id=moment_ids[0], body="first note", created_at=1700000000
    )
    assert row["body"] == "first note"
    assert row["moment_id"] == moment_ids[0]
    assert row["created_at"] == 1700000000


def test_multiple_annotations_per_moment_are_allowed(db_with_moments):
    conn, moment_ids = db_with_moments
    insert_annotation(conn, moment_id=moment_ids[0], body="one", created_at=1)
    insert_annotation(conn, moment_id=moment_ids[0], body="two", created_at=2)
    rows = get_annotations_by_moment(conn, moment_ids[0])
    assert [r["body"] for r in rows] == ["one", "two"]


def test_get_annotations_by_moment_orders_by_created_at(db_with_moments):
    conn, moment_ids = db_with_moments
    insert_annotation(conn, moment_id=moment_ids[0], body="later", created_at=200)
    insert_annotation(conn, moment_id=moment_ids[0], body="earlier", created_at=100)
    rows = get_annotations_by_moment(conn, moment_ids[0])
    assert [r["body"] for r in rows] == ["earlier", "later"]


def test_get_annotations_by_moment_returns_empty_for_moment_with_none(db_with_moments):
    conn, moment_ids = db_with_moments
    assert get_annotations_by_moment(conn, moment_ids[0]) == []


def test_get_annotations_by_roll_joins_moment_timestamp(db_with_moments):
    conn, moment_ids = db_with_moments
    insert_annotation(conn, moment_id=moment_ids[1], body="on m2", created_at=50)
    insert_annotation(conn, moment_id=moment_ids[0], body="on m1", created_at=60)
    rows = get_annotations_by_roll(conn, "roll-1")
    # Ordered by timestamp_s asc, then created_at asc — so m1 (t=3) comes before m2 (t=7).
    assert [(r["timestamp_s"], r["body"]) for r in rows] == [
        (3.0, "on m1"),
        (7.0, "on m2"),
    ]


def test_get_annotations_by_roll_returns_empty_for_roll_with_none(db_with_moments):
    conn, _ = db_with_moments
    assert get_annotations_by_roll(conn, "roll-1") == []


def test_annotations_cascade_delete_on_moment_delete(db_with_moments):
    conn, moment_ids = db_with_moments
    insert_annotation(conn, moment_id=moment_ids[0], body="x", created_at=1)
    conn.execute("DELETE FROM moments WHERE id = ?", (moment_ids[0],))
    conn.commit()
    assert get_annotations_by_moment(conn, moment_ids[0]) == []
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_db_annotations.py -v
```

Expected: ImportError on the three helpers.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_db_annotations.py
git commit -m "test(bjj-app): add annotations db helper tests (failing — no impl)"
```

---

## Task 5: Implement annotations db helpers

**Files:**
- Modify: `tools/bjj-app/server/db.py`

- [ ] **Step 1: Append helpers to `db.py`**

Append to the end of `tools/bjj-app/server/db.py`:

```python


def insert_annotation(
    conn,
    *,
    moment_id: str,
    body: str,
    created_at: int,
) -> sqlite3.Row:
    """Append a new annotation to a moment. Returns the inserted row."""
    annotation_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO annotations (id, moment_id, body, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (annotation_id, moment_id, body, created_at, created_at),
    )
    conn.commit()
    cur = conn.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    return cur.fetchone()


def get_annotations_by_moment(conn, moment_id: str) -> list[sqlite3.Row]:
    """Return all annotations for a moment ordered by created_at ascending."""
    cur = conn.execute(
        "SELECT * FROM annotations WHERE moment_id = ? ORDER BY created_at",
        (moment_id,),
    )
    return list(cur.fetchall())


def get_annotations_by_roll(conn, roll_id: str) -> list[sqlite3.Row]:
    """Return all annotations for a roll, joined with moment timestamps.

    Ordered for vault rendering: by moment timestamp_s ascending, then by
    created_at ascending within each moment.
    Each row carries: id, moment_id, body, created_at, updated_at, timestamp_s, frame_idx.
    """
    cur = conn.execute(
        """
        SELECT a.id, a.moment_id, a.body, a.created_at, a.updated_at,
               m.timestamp_s, m.frame_idx
          FROM annotations a
          JOIN moments m ON m.id = a.moment_id
         WHERE m.roll_id = ?
         ORDER BY m.timestamp_s ASC, a.created_at ASC
        """,
        (roll_id,),
    )
    return list(cur.fetchall())
```

- [ ] **Step 2: Run — must pass**

```bash
pytest tests/backend/test_db_annotations.py -v
```

Expected: 7 passed.

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py
git commit -m "feat(bjj-app): add annotations db helpers (insert + by-moment + by-roll)"
```

---

## Task 6: Pure helper — `render_your_notes`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_vault_writer.py` (first of several vault_writer tests; additions happen in later tasks)

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/tests/backend/test_vault_writer.py` with this initial content:

```python
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
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_vault_writer.py -v
```

Expected: ImportError on `server.analysis.vault_writer`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_vault_writer.py
git commit -m "test(bjj-app): add render_your_notes tests (failing — no impl)"
```

---

## Task 7: Implement `render_your_notes`

**Files:**
- Create: `tools/bjj-app/server/analysis/vault_writer.py`

- [ ] **Step 1: Write the initial `vault_writer.py`**

Create `tools/bjj-app/server/analysis/vault_writer.py`:

```python
"""SOLE module that writes to Roll Log/*.md.

All vault markdown writes go through `publish`. Pure helpers (`render_your_notes`,
`slugify_filename`) are extracted for easy unit testing.

Security invariant: every write target must resolve under `vault_root/Roll Log/`.
Enforced inside `publish` by Path.resolve().relative_to().
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


def render_your_notes(rows: Iterable) -> str:
    """Render annotation rows as the body of the `## Your Notes` section.

    Input row shape (dict or sqlite3.Row): keys `moment_id`, `timestamp_s`,
    `body`, `created_at`. Ordering is performed here — caller need not sort.
    Returns a string without a trailing newline; the caller adds surrounding
    section framing.
    """
    rows_list: list = list(rows)
    if not rows_list:
        return ""

    # Sort by (timestamp_s, created_at) for moment-groups then bullet order.
    rows_list.sort(key=lambda r: (_row_get(r, "timestamp_s"), _row_get(r, "created_at")))

    # Group consecutive rows with the same moment_id into their H3 section.
    sections: list[str] = []
    current_moment_id: str | None = None
    current_bullets: list[str] = []
    current_header: str = ""

    def flush() -> None:
        if current_moment_id is None:
            return
        sections.append(current_header + "\n" + "\n".join(current_bullets))

    for row in rows_list:
        moment_id = _row_get(row, "moment_id")
        if moment_id != current_moment_id:
            flush()
            current_bullets = []
            current_moment_id = moment_id
            current_header = f"### {_format_mm_ss(_row_get(row, 'timestamp_s'))}"
        ts = _format_created_stamp(_row_get(row, "created_at"))
        body = _row_get(row, "body")
        current_bullets.append(f"- _({ts})_ {body}")
    flush()

    return "\n\n".join(sections)


def _row_get(row, key: str):
    if isinstance(row, dict):
        return row[key]
    return row[key]  # sqlite3.Row supports [key] too


def _format_mm_ss(seconds: float) -> str:
    total = int(round(seconds))
    m = total // 60
    s = total % 60
    return f"{m}:{s:02d}"


def _format_created_stamp(unix_seconds: int) -> str:
    # UTC — deterministic across machines. Obsidian renders this verbatim.
    dt = datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")
```

- [ ] **Step 2: Run — must pass**

```bash
pytest tests/backend/test_vault_writer.py -v
```

Expected: 6 passed (the render_your_notes tests).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/vault_writer.py
git commit -m "feat(bjj-app): add render_your_notes (H3-per-moment vault body)"
```

---

## Task 8: Pure helper — `slugify_filename`

**Files:**
- Modify: `tools/bjj-app/tests/backend/test_vault_writer.py` (append tests)

- [ ] **Step 1: Append tests**

Append to `tools/bjj-app/tests/backend/test_vault_writer.py`:

```python


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
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_vault_writer.py -v
```

Expected: 5 new tests fail (ImportError on `slugify_filename`).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_vault_writer.py
git commit -m "test(bjj-app): add slugify_filename tests (failing — no impl)"
```

---

## Task 9: Implement `slugify_filename`

**Files:**
- Modify: `tools/bjj-app/server/analysis/vault_writer.py`

- [ ] **Step 1: Append to `vault_writer.py`**

Append to `tools/bjj-app/server/analysis/vault_writer.py`:

```python


_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def slugify_filename(title: str, date: str, vault_root: Path) -> Path:
    """Return a collision-safe path under `<vault_root>/Roll Log/`.

    Filename template: `YYYY-MM-DD - <sanitised title>.md`.
    Sanitisation: collapses runs of whitespace, strips filesystem-unsafe
    characters (/\\:*?"<>|), drops leading dots so ".." or "./" can't escape.

    On collision, appends ` (2)`, ` (3)` etc. until unique.
    """
    roll_log = vault_root / "Roll Log"
    roll_log.mkdir(parents=True, exist_ok=True)

    clean_title = _UNSAFE_CHARS.sub("", title).strip()
    clean_title = re.sub(r"\s+", " ", clean_title)
    # Prevent leading dot (hidden file, or ".." remnants).
    clean_title = clean_title.lstrip(". ")
    if not clean_title:
        clean_title = "Roll"

    base = f"{date} - {clean_title}"
    candidate = roll_log / f"{base}.md"
    if not candidate.exists():
        return candidate

    n = 2
    while True:
        candidate = roll_log / f"{base} ({n}).md"
        if not candidate.exists():
            return candidate
        n += 1
```

Add `import re` to the top of `vault_writer.py` if not already present. (The current file doesn't import it — so add it.)

The import block at the top of `vault_writer.py` should end up looking like:

```python
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
```

- [ ] **Step 2: Run — must pass**

```bash
pytest tests/backend/test_vault_writer.py -v
```

Expected: 11 passed (6 render + 5 slugify).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/vault_writer.py
git commit -m "feat(bjj-app): add slugify_filename (collision-safe Roll Log path)"
```

---

## Task 10: Write failing tests for `publish`

**Files:**
- Modify: `tools/bjj-app/tests/backend/test_vault_writer.py` (append publish tests)

- [ ] **Step 1: Append tests**

Append to `tools/bjj-app/tests/backend/test_vault_writer.py`:

```python


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
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_vault_writer.py -v
```

Expected: 8 new tests fail (ImportError on `publish` / `ConflictError`).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_vault_writer.py
git commit -m "test(bjj-app): add publish() tests (failing — no impl)"
```

---

## Task 11: Implement `publish` + `ConflictError` + `PublishResult`

**Files:**
- Modify: `tools/bjj-app/server/analysis/vault_writer.py`

- [ ] **Step 1: Append to `vault_writer.py`**

Append to the end of `tools/bjj-app/server/analysis/vault_writer.py`:

```python


# ---------- publish orchestration ----------


import hashlib
import os
import re as _re  # re is already imported at top, alias to avoid shadowing any later additions
import time

from server.db import get_annotations_by_roll, get_roll, get_vault_state, set_vault_state


@dataclass(frozen=True)
class PublishResult:
    vault_path: str            # relative to vault_root, e.g. "Roll Log/2026-04-21 - T.md"
    your_notes_hash: str       # sha256 of the new Your Notes body
    vault_published_at: int    # unix seconds when this publish completed


class ConflictError(Exception):
    """Raised by publish() when `## Your Notes` hash in the file disagrees with stored hash."""

    def __init__(self, *, current_hash: str, stored_hash: str) -> None:
        super().__init__(
            f"Your Notes section hash mismatch: current={current_hash[:8]} "
            f"stored={stored_hash[:8]}"
        )
        self.current_hash = current_hash
        self.stored_hash = stored_hash


_YOUR_NOTES_HEADING = "## Your Notes"
_SECTION_BOUNDARY = _re.compile(r"^## ", _re.MULTILINE)


def publish(
    conn,
    *,
    roll_id: str,
    vault_root: Path,
    force: bool = False,
) -> PublishResult:
    """Publish a roll's annotations to its vault markdown file.

    First publish: creates a new file under Roll Log/ with frontmatter + title +
    Your Notes. Re-publish: surgically replaces the Your Notes section only,
    preserving everything else. Hash-based conflict detection fires on external
    edits to Your Notes (raises ConflictError unless force=True).
    """
    roll_row = get_roll(conn, roll_id)
    if roll_row is None:
        raise LookupError(f"Roll not found: {roll_id}")

    # Render the new Your Notes body from current annotations.
    annotations = get_annotations_by_roll(conn, roll_id)
    new_body = render_your_notes(annotations)
    new_hash = _hash_section(new_body)

    vault_state = get_vault_state(conn, roll_id) or {
        "vault_path": None, "vault_your_notes_hash": None, "vault_published_at": None,
    }

    # Decide target path: existing stored path if any, else slugify new one.
    if vault_state["vault_path"]:
        target = vault_root / vault_state["vault_path"]
    else:
        target = slugify_filename(
            title=roll_row["title"],
            date=roll_row["date"],
            vault_root=vault_root,
        )

    # Security invariant: target must resolve under Roll Log/.
    _assert_under_roll_log(target, vault_root)

    if target.exists():
        current_text = target.read_text(encoding="utf-8")
        current_section = _extract_your_notes_section(current_text)
        current_hash = _hash_section(current_section)
        stored_hash = vault_state["vault_your_notes_hash"]
        if stored_hash is not None and current_hash != stored_hash and not force:
            raise ConflictError(current_hash=current_hash, stored_hash=stored_hash)
        new_text = _splice_your_notes(current_text, new_body)
    else:
        # Either first publish OR user deleted the file — build from scratch.
        new_text = _build_skeleton(
            title=roll_row["title"],
            date=roll_row["date"],
            partner=roll_row["partner"],
            duration_s=roll_row["duration_s"],
            roll_id=roll_id,
            your_notes_body=new_body,
        )

    _atomic_write(target, new_text)

    now = int(time.time())
    relative_path = str(target.relative_to(vault_root))
    set_vault_state(
        conn,
        roll_id=roll_id,
        vault_path=relative_path,
        vault_your_notes_hash=new_hash,
        vault_published_at=now,
    )
    return PublishResult(
        vault_path=relative_path,
        your_notes_hash=new_hash,
        vault_published_at=now,
    )


def _assert_under_roll_log(target: Path, vault_root: Path) -> None:
    roll_log = (vault_root / "Roll Log").resolve()
    resolved = target.resolve()
    if not resolved.is_relative_to(roll_log):
        raise ValueError(f"target {target} escapes Roll Log directory {roll_log}")


def _build_skeleton(
    *,
    title: str,
    date: str,
    partner: str | None,
    duration_s: float | None,
    roll_id: str,
    your_notes_body: str,
) -> str:
    duration = _format_duration(duration_s)
    partner_line = f"partner: {partner}" if partner else "partner:"
    duration_line = f'duration: "{duration}"' if duration else "duration:"

    frontmatter = "\n".join([
        "---",
        f"date: {date}",
        partner_line,
        duration_line,
        "tags: [roll]",
        f"roll_id: {roll_id}",
        "---",
    ])

    body = your_notes_body if your_notes_body else ""
    return (
        f"{frontmatter}\n\n"
        f"# {title}\n\n"
        f"{_YOUR_NOTES_HEADING}\n\n"
        f"{body}\n"
    )


def _format_duration(duration_s: float | None) -> str:
    if duration_s is None:
        return ""
    total = int(round(duration_s))
    m = total // 60
    s = total % 60
    return f"{m}:{s:02d}"


def _extract_your_notes_section(text: str) -> str:
    """Return the body of `## Your Notes` section, or '' if absent.

    The body spans from the first blank line after the heading to the next
    `## ` heading (exclusive) or EOF. Leading/trailing whitespace is stripped
    so whitespace-only differences don't trigger false conflicts.
    """
    heading_idx = text.find(_YOUR_NOTES_HEADING)
    if heading_idx == -1:
        return ""
    # Start after the heading line.
    body_start = text.find("\n", heading_idx)
    if body_start == -1:
        return ""
    body_start += 1

    # Find next `^## ` heading (anywhere in the remaining text).
    rest = text[body_start:]
    m = _SECTION_BOUNDARY.search(rest)
    end = body_start + m.start() if m else len(text)

    return text[body_start:end].strip()


def _splice_your_notes(current_text: str, new_body: str) -> str:
    """Replace the Your Notes section body inside an existing file.

    If the section heading is absent, append a new section at the end.
    """
    heading_idx = current_text.find(_YOUR_NOTES_HEADING)
    if heading_idx == -1:
        # Append a new section.
        separator = "" if current_text.endswith("\n\n") else ("\n" if current_text.endswith("\n") else "\n\n")
        return f"{current_text}{separator}{_YOUR_NOTES_HEADING}\n\n{new_body}\n"

    # Find body span [body_start, end).
    body_start = current_text.find("\n", heading_idx)
    if body_start == -1:
        body_start = len(current_text)
    else:
        body_start += 1
    rest = current_text[body_start:]
    m = _SECTION_BOUNDARY.search(rest)
    end = body_start + m.start() if m else len(current_text)

    # Standardise the body block: the heading line stays; then one blank line;
    # then the new body; then a blank line before the next `## ` (if any).
    before = current_text[: heading_idx + len(_YOUR_NOTES_HEADING)]
    after = current_text[end:]

    # Ensure `after` starts with a newline before `## ` so rendering stays clean.
    if after and not after.startswith("\n"):
        after = "\n" + after
    # If there's no following section, make sure the file ends with a trailing newline.
    if not after:
        after = "\n"

    return f"{before}\n\n{new_body}\n{after}"


def _hash_section(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
```

- [ ] **Step 2: Run — must pass**

```bash
pytest tests/backend/test_vault_writer.py -v
```

Expected: 19 passed (6 render + 5 slugify + 8 publish).

Full suite:
```bash
pytest tests/backend -v
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/vault_writer.py
git commit -m "feat(bjj-app): add vault_writer.publish (atomic splice with hash-based conflict detection)"
```

---

## Task 12: Extend `vault.py` `list_rolls` with `roll_id`

**Files:**
- Modify: `tools/bjj-app/server/analysis/vault.py`
- Modify: `tools/bjj-app/tests/backend/test_vault.py`

- [ ] **Step 1: Extend existing test**

Open `tools/bjj-app/tests/backend/test_vault.py`. Append these tests to the end of the file:

```python


def test_list_rolls_exposes_roll_id_from_frontmatter(tmp_path: Path):
    roll_log = tmp_path / "Roll Log"
    roll_log.mkdir()
    (roll_log / "2026-04-21 - with-id.md").write_text(
        "---\n"
        "date: 2026-04-21\n"
        "roll_id: abc123def\n"
        "tags: [roll]\n"
        "---\n"
        "# With ID\n"
    )
    (roll_log / "2026-04-20 - without-id.md").write_text(
        "---\n"
        "date: 2026-04-20\n"
        "tags: [roll]\n"
        "---\n"
        "# No ID\n"
    )

    rolls = list_rolls(tmp_path)
    by_id = {r.id: r for r in rolls}
    assert by_id["2026-04-21 - with-id"].roll_id == "abc123def"
    assert by_id["2026-04-20 - without-id"].roll_id is None
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_vault.py -v
```

Expected: 3 existing pass, 1 new fails with `AttributeError: 'RollSummary' object has no attribute 'roll_id'`.

- [ ] **Step 3: Add `roll_id` field to `RollSummary` and populate it**

In `tools/bjj-app/server/analysis/vault.py`, modify the `RollSummary` dataclass to add a `roll_id` field. Replace:

```python
@dataclass(frozen=True)
class RollSummary:
    """One row in the home page's roll list.

    `id` is the markdown filename stem — a stable, vault-relative identifier
    safe to send over HTTP and use in URLs. `path` is the full filesystem
    Path for internal use by later-milestone code that reads/writes the file.
    """

    id: str
    path: Path
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None
```

with:

```python
@dataclass(frozen=True)
class RollSummary:
    """One row in the home page's roll list.

    `id` is the markdown filename stem — a stable, vault-relative identifier
    safe to send over HTTP and use in URLs. `path` is the full filesystem
    Path for internal use by later-milestone code that reads/writes the file.
    `roll_id` is the SQLite uuid from frontmatter (present on files the app
    has published, absent on legacy markdown).
    """

    id: str
    path: Path
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None
    roll_id: str | None
```

Then in the `list_rolls` function body, update the `RollSummary(...)` construction to populate `roll_id` from frontmatter. Replace:

```python
        summaries.append(
            RollSummary(
                id=md_path.stem,
                path=md_path,
                title=title,
                date=str(post.metadata.get("date", "")),
                partner=_str_or_none(post.metadata.get("partner")),
                duration=_str_or_none(post.metadata.get("duration")),
                result=_str_or_none(post.metadata.get("result")),
            )
        )
```

with:

```python
        summaries.append(
            RollSummary(
                id=md_path.stem,
                path=md_path,
                title=title,
                date=str(post.metadata.get("date", "")),
                partner=_str_or_none(post.metadata.get("partner")),
                duration=_str_or_none(post.metadata.get("duration")),
                result=_str_or_none(post.metadata.get("result")),
                roll_id=_str_or_none(post.metadata.get("roll_id")),
            )
        )
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_vault.py -v
```

Expected: 4 passed.

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/vault.py tools/bjj-app/tests/backend/test_vault.py
git commit -m "feat(bjj-app): expose roll_id from frontmatter in RollSummary"
```

---

## Task 13: Extend `api/rolls.py` — MomentOut.annotations, RollDetailOut vault fields, RollSummaryOut.roll_id

**Files:**
- Modify: `tools/bjj-app/server/api/rolls.py`

This task adds the shape changes without new endpoints. Existing tests that don't reference the new fields continue to pass because Pydantic defaults apply.

- [ ] **Step 1: Update `api/rolls.py`**

Open `tools/bjj-app/server/api/rolls.py`.

Change the imports line:
```python
from server.db import connect, create_roll, get_analyses, get_moments, get_roll
```
to:
```python
from server.db import (
    connect,
    create_roll,
    get_analyses,
    get_annotations_by_moment,
    get_moments,
    get_roll,
)
```

Replace the `RollSummaryOut` class with:
```python
class RollSummaryOut(BaseModel):
    """Compact shape for the home page roll list."""

    id: str
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None
    roll_id: str | None = None

    @classmethod
    def from_vault(cls, r: RollSummary) -> "RollSummaryOut":
        return cls(
            id=r.id,
            title=r.title,
            date=r.date,
            partner=r.partner,
            duration=r.duration,
            result=r.result,
            roll_id=r.roll_id,
        )
```

Replace the `AnalysisOut`, `MomentOut`, and `RollDetailOut` classes with:
```python
class AnalysisOut(BaseModel):
    id: str
    player: str
    position_id: str
    confidence: float | None
    description: str | None
    coach_tip: str | None


class AnnotationOut(BaseModel):
    id: str
    body: str
    created_at: int


class MomentOut(BaseModel):
    id: str
    frame_idx: int
    timestamp_s: float
    pose_delta: float | None
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
    moments: list[MomentOut] = []
```

Replace the `get_roll_detail` function with:
```python
@router.get("/rolls/{roll_id}", response_model=RollDetailOut)
def get_roll_detail(
    roll_id: str,
    settings: Settings = Depends(load_settings),
) -> RollDetailOut:
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        moment_rows = get_moments(conn, roll_id)
        analyses_by_moment: dict[str, list] = {
            m["id"]: get_analyses(conn, m["id"]) for m in moment_rows
        }
        annotations_by_moment: dict[str, list] = {
            m["id"]: get_annotations_by_moment(conn, m["id"]) for m in moment_rows
        }
    finally:
        conn.close()

    moments_out = [
        MomentOut(
            id=m["id"],
            frame_idx=m["frame_idx"],
            timestamp_s=m["timestamp_s"],
            pose_delta=m["pose_delta"],
            analyses=[
                AnalysisOut(
                    id=a["id"],
                    player=a["player"],
                    position_id=a["position_id"],
                    confidence=a["confidence"],
                    description=a["description"],
                    coach_tip=a["coach_tip"],
                )
                for a in analyses_by_moment[m["id"]]
            ],
            annotations=[
                AnnotationOut(id=an["id"], body=an["body"], created_at=an["created_at"])
                for an in annotations_by_moment[m["id"]]
            ],
        )
        for m in moment_rows
    ]

    return RollDetailOut(
        id=row["id"],
        title=row["title"],
        date=row["date"],
        partner=row["partner"],
        duration_s=row["duration_s"],
        result=row["result"],
        video_url=f"/{row['video_path']}",
        vault_path=row["vault_path"],
        vault_published_at=row["vault_published_at"],
        moments=moments_out,
    )
```

Also update the `upload_roll` function's return `RollDetailOut(...)` to include the new fields. Find the final `return RollDetailOut(...)` in `upload_roll` and change it to:

```python
    return RollDetailOut(
        id=roll_id,
        title=title,
        date=date,
        partner=partner,
        duration_s=duration_s,
        result="unknown",
        video_url=f"/assets/{roll_id}/source.mp4",
        vault_path=None,
        vault_published_at=None,
        moments=[],
    )
```

- [ ] **Step 2: Run the full suite — no regressions**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend -v
```

Expected: all existing tests still pass. New fields default; no existing test touches them.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/rolls.py
git commit -m "feat(bjj-app): extend MomentOut/RollDetailOut/RollSummaryOut with M4 fields"
```

---

## Task 14: Write failing tests for annotations API

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_annotations.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_api_annotations.py`:

```python
"""Tests for PATCH /api/rolls/:id/moments/:moment_id/annotations."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


async def _upload_and_detect_moment(client: AsyncClient, short_video_path: Path) -> tuple[str, str]:
    """Upload + pose pre-pass. Returns (roll_id, first_moment_id)."""
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Annotations fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]

    pre = await client.post(f"/api/rolls/{roll_id}/analyse")
    assert pre.status_code == 200

    detail = await client.get(f"/api/rolls/{roll_id}")
    moments = detail.json()["moments"]
    assert moments
    return roll_id, moments[0]["id"]


@pytest.mark.asyncio
async def test_patch_annotation_inserts_and_returns_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moment_id = await _upload_and_detect_moment(client, short_video_path)
        response = await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "a first note"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "a first note"
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_patch_annotation_appends_multiple(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moment_id = await _upload_and_detect_moment(client, short_video_path)
        await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "one"},
        )
        await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "two"},
        )

        detail = await client.get(f"/api/rolls/{roll_id}")

    moment = next(
        m for m in detail.json()["moments"] if m["id"] == moment_id
    )
    bodies = [a["body"] for a in moment["annotations"]]
    assert bodies == ["one", "two"]


@pytest.mark.asyncio
async def test_patch_annotation_returns_404_for_unknown_roll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/api/rolls/no-such-roll/moments/no-such-moment/annotations",
            json={"body": "x"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_annotation_returns_404_for_unknown_moment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_detect_moment(client, short_video_path)
        response = await client.patch(
            f"/api/rolls/{roll_id}/moments/no-such-moment/annotations",
            json={"body": "x"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_annotation_rejects_empty_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moment_id = await _upload_and_detect_moment(client, short_video_path)
        response = await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "   "},
        )

    assert response.status_code == 400
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_annotations.py -v
```

Expected: all 5 fail with 404 (router doesn't exist) or ImportError.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_annotations.py
git commit -m "test(bjj-app): add annotations API tests (failing — no impl)"
```

---

## Task 15: Implement annotations API

**Files:**
- Create: `tools/bjj-app/server/api/annotations.py`
- Modify: `tools/bjj-app/server/main.py`

- [ ] **Step 1: Create `server/api/annotations.py`**

Create `tools/bjj-app/server/api/annotations.py`:

```python
"""PATCH /api/rolls/:id/moments/:moment_id/annotations — append-only annotations."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from server.config import Settings, load_settings
from server.db import connect, get_moments, get_roll, insert_annotation

router = APIRouter(prefix="/api", tags=["annotations"])


class _AnnotationIn(BaseModel):
    body: str


class _AnnotationOut(BaseModel):
    id: str
    body: str
    created_at: int


@router.patch(
    "/rolls/{roll_id}/moments/{moment_id}/annotations",
    response_model=_AnnotationOut,
    status_code=status.HTTP_201_CREATED,
)
def add_annotation(
    roll_id: str,
    moment_id: str,
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
        moments = get_moments(conn, roll_id)
        if not any(m["id"] == moment_id for m in moments):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Moment not found"
            )
        row = insert_annotation(
            conn, moment_id=moment_id, body=body, created_at=int(time.time())
        )
    finally:
        conn.close()

    return _AnnotationOut(id=row["id"], body=row["body"], created_at=row["created_at"])
```

- [ ] **Step 2: Register the router in `main.py`**

Open `tools/bjj-app/server/main.py`. Change:

```python
from server.api import analyse as analyse_api
from server.api import moments as moments_api
from server.api import rolls as rolls_api
```

to:

```python
from server.api import analyse as analyse_api
from server.api import annotations as annotations_api
from server.api import moments as moments_api
from server.api import rolls as rolls_api
```

Then change:

```python
    app.include_router(rolls_api.router)
    app.include_router(analyse_api.router)
    app.include_router(moments_api.router)
```

to:

```python
    app.include_router(rolls_api.router)
    app.include_router(analyse_api.router)
    app.include_router(moments_api.router)
    app.include_router(annotations_api.router)
```

- [ ] **Step 3: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_api_annotations.py -v
```

Expected: 5 passed.

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/annotations.py tools/bjj-app/server/main.py
git commit -m "feat(bjj-app): add PATCH /api/rolls/:id/moments/:moment_id/annotations"
```

---

## Task 16: Write failing tests for publish API

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_publish.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_api_publish.py`:

```python
"""Tests for POST /api/rolls/:id/publish."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


async def _upload_annotate(client: AsyncClient, short_video_path: Path) -> tuple[str, str]:
    """Upload + pose pre-pass + add one annotation. Returns (roll_id, moment_id)."""
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Publish fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]

    pre = await client.post(f"/api/rolls/{roll_id}/analyse")
    assert pre.status_code == 200

    detail = await client.get(f"/api/rolls/{roll_id}")
    moment_id = detail.json()["moments"][0]["id"]

    ann = await client.patch(
        f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
        json={"body": "my note"},
    )
    assert ann.status_code == 201
    return roll_id, moment_id


@pytest.mark.asyncio
async def test_publish_first_time_creates_file_and_returns_200(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_annotate(client, short_video_path)
        response = await client.post(
            f"/api/rolls/{roll_id}/publish", json={}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["vault_path"].startswith("Roll Log/")
    assert body["your_notes_hash"]
    assert body["vault_published_at"] > 0

    vault_file = tmp_project_root / body["vault_path"]
    assert vault_file.exists()
    content = vault_file.read_text()
    assert "my note" in content
    assert "## Your Notes" in content
    assert f"roll_id: {roll_id}" in content


@pytest.mark.asyncio
async def test_publish_returns_409_on_external_your_notes_edit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moment_id = await _upload_annotate(client, short_video_path)
        first = await client.post(f"/api/rolls/{roll_id}/publish", json={})
        assert first.status_code == 200
        vault_path = tmp_project_root / first.json()["vault_path"]

        # Simulate external edit to Your Notes.
        original = vault_path.read_text()
        tampered = original.replace("my note", "my note — edited in Obsidian")
        vault_path.write_text(tampered)

        # Add another annotation + re-publish without force → 409.
        await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "second note"},
        )
        second = await client.post(f"/api/rolls/{roll_id}/publish", json={})

    assert second.status_code == 409
    body = second.json()
    assert body["current_hash"] != body["stored_hash"]


@pytest.mark.asyncio
async def test_publish_force_true_overrides_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moment_id = await _upload_annotate(client, short_video_path)
        first = await client.post(f"/api/rolls/{roll_id}/publish", json={})
        vault_path = tmp_project_root / first.json()["vault_path"]

        tampered = vault_path.read_text().replace("my note", "externally edited")
        vault_path.write_text(tampered)

        await client.patch(
            f"/api/rolls/{roll_id}/moments/{moment_id}/annotations",
            json={"body": "force note"},
        )

        forced = await client.post(
            f"/api/rolls/{roll_id}/publish", json={"force": True}
        )

    assert forced.status_code == 200
    content = vault_path.read_text()
    assert "externally edited" not in content
    assert "force note" in content


@pytest.mark.asyncio
async def test_publish_returns_404_for_unknown_roll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/rolls/no-such-roll/publish", json={})

    assert response.status_code == 404
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_publish.py -v
```

Expected: 4 tests fail with 404/405 (endpoint missing).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_publish.py
git commit -m "test(bjj-app): add publish API tests (failing — no impl)"
```

---

## Task 17: Implement publish API

**Files:**
- Create: `tools/bjj-app/server/api/publish.py`
- Modify: `tools/bjj-app/server/main.py`

- [ ] **Step 1: Create `server/api/publish.py`**

Create `tools/bjj-app/server/api/publish.py`:

```python
"""POST /api/rolls/:id/publish — publish annotations to the vault markdown."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.analysis.vault_writer import ConflictError, publish as vault_publish
from server.config import Settings, load_settings
from server.db import connect

router = APIRouter(prefix="/api", tags=["publish"])


class _PublishIn(BaseModel):
    force: bool = False


class _PublishOut(BaseModel):
    vault_path: str
    your_notes_hash: str
    vault_published_at: int


@router.post(
    "/rolls/{roll_id}/publish",
    response_model=_PublishOut,
)
def publish_roll(
    roll_id: str,
    payload: _PublishIn,
    settings: Settings = Depends(load_settings),
):
    conn = connect(settings.db_path)
    try:
        try:
            result = vault_publish(
                conn,
                roll_id=roll_id,
                vault_root=settings.vault_root,
                force=payload.force,
            )
        except LookupError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        except ConflictError as exc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "Your Notes was edited in Obsidian since last publish",
                    "current_hash": exc.current_hash,
                    "stored_hash": exc.stored_hash,
                },
            )
    finally:
        conn.close()

    return _PublishOut(
        vault_path=result.vault_path,
        your_notes_hash=result.your_notes_hash,
        vault_published_at=result.vault_published_at,
    )
```

- [ ] **Step 2: Register the router in `main.py`**

Open `tools/bjj-app/server/main.py`. Change:

```python
from server.api import analyse as analyse_api
from server.api import annotations as annotations_api
from server.api import moments as moments_api
from server.api import rolls as rolls_api
```

to:

```python
from server.api import analyse as analyse_api
from server.api import annotations as annotations_api
from server.api import moments as moments_api
from server.api import publish as publish_api
from server.api import rolls as rolls_api
```

Then change:

```python
    app.include_router(rolls_api.router)
    app.include_router(analyse_api.router)
    app.include_router(moments_api.router)
    app.include_router(annotations_api.router)
```

to:

```python
    app.include_router(rolls_api.router)
    app.include_router(analyse_api.router)
    app.include_router(moments_api.router)
    app.include_router(annotations_api.router)
    app.include_router(publish_api.router)
```

- [ ] **Step 3: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_api_publish.py -v
```

Expected: 4 passed.

Full suite sanity — this is the backend completion gate:
```bash
pytest tests/backend -v
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/publish.py tools/bjj-app/server/main.py
git commit -m "feat(bjj-app): add POST /api/rolls/:id/publish (with 409 conflict surfacing)"
```

---

## Task 18: Frontend types + api.ts

**Files:**
- Modify: `tools/bjj-app/web/src/lib/types.ts`
- Modify: `tools/bjj-app/web/src/lib/api.ts`

- [ ] **Step 1: Update `types.ts`**

Replace the entire contents of `tools/bjj-app/web/src/lib/types.ts` with:

```typescript
export type RollSummary = {
  id: string;
  title: string;
  date: string;
  partner: string | null;
  duration: string | null;
  result: string | null;
  roll_id: string | null;
};

export type Analysis = {
  id: string;
  player: 'greig' | 'anthony';
  position_id: string;
  confidence: number | null;
  description: string | null;
  coach_tip: string | null;
};

export type Annotation = {
  id: string;
  body: string;
  created_at: number;
};

export type Moment = {
  id: string;
  frame_idx: number;
  timestamp_s: number;
  pose_delta: number | null;
  analyses: Analysis[];
  annotations: Annotation[];
};

export type RollDetail = {
  id: string;
  title: string;
  date: string;
  partner: string | null;
  duration_s: number | null;
  result: string;
  video_url: string;
  vault_path: string | null;
  vault_published_at: number | null;
  moments: Moment[];
};

export type CreateRollInput = {
  title: string;
  date: string;
  partner?: string;
  video: File;
};

export type AnalyseEvent =
  | { stage: 'frames'; pct: number; total?: number }
  | { stage: 'pose'; pct: number; total?: number }
  | {
      stage: 'done';
      total?: number;
      moments: Array<{ frame_idx: number; timestamp_s: number; pose_delta: number | null }>;
    };

export type AnalyseMomentEvent =
  | { stage: 'cache'; hit: boolean }
  | { stage: 'streaming'; text: string }
  | {
      stage: 'done';
      cached: boolean;
      analysis: {
        timestamp: number;
        greig: { position: string; confidence: number };
        anthony: { position: string; confidence: number };
        description: string;
        coach_tip: string;
      };
    }
  | {
      stage: 'error';
      kind: string;
      detail?: string;
      retry_after_s?: number;
    };

export type PublishSuccess = {
  vault_path: string;
  your_notes_hash: string;
  vault_published_at: number;
};

export type PublishConflict = {
  detail: string;
  current_hash: string;
  stored_hash: string;
};
```

- [ ] **Step 2: Update `api.ts`**

Open `tools/bjj-app/web/src/lib/api.ts`. Change the import line at the top:

```typescript
import type {
  AnalyseEvent,
  AnalyseMomentEvent,
  CreateRollInput,
  RollDetail,
  RollSummary
} from './types';
```

to:

```typescript
import type {
  AnalyseEvent,
  AnalyseMomentEvent,
  Annotation,
  CreateRollInput,
  PublishConflict,
  PublishSuccess,
  RollDetail,
  RollSummary
} from './types';
```

Append at the end of the file:

```typescript

export function addAnnotation(
  rollId: string,
  momentId: string,
  body: string
): Promise<Annotation> {
  return request<Annotation>(
    `/api/rolls/${encodeURIComponent(rollId)}/moments/${encodeURIComponent(momentId)}/annotations`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body })
    }
  );
}

/**
 * Publish a roll to the vault. Returns PublishSuccess on 200.
 * On 409, throws a ConflictError carrying the current/stored hashes.
 */
export class PublishConflictError extends Error {
  constructor(public readonly payload: PublishConflict) {
    super(payload.detail);
  }
}

export async function publishRoll(
  rollId: string,
  options: { force?: boolean } = {}
): Promise<PublishSuccess> {
  const response = await fetch(`/api/rolls/${encodeURIComponent(rollId)}/publish`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ force: options.force ?? false })
  });
  if (response.status === 409) {
    const payload = (await response.json()) as PublishConflict;
    throw new PublishConflictError(payload);
  }
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as PublishSuccess;
}
```

- [ ] **Step 3: Run existing frontend tests — no regressions**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 12 passed (existing M3 tests). The new `Annotation`, `PublishSuccess`, `PublishConflict` types are type-only additions and don't affect runtime behaviour.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/types.ts tools/bjj-app/web/src/lib/api.ts
git commit -m "feat(bjj-app): add Annotation types + addAnnotation/publishRoll client"
```

---

## Task 19: Extend `MomentDetail.svelte` with notes thread + textarea (tests)

**Files:**
- Modify: `tools/bjj-app/web/tests/moment-detail.test.ts`

Append new tests for the notes thread + textarea behaviour. Keep existing tests unchanged — they still assert analyses rendering and are orthogonal.

- [ ] **Step 1: Append tests**

Open `tools/bjj-app/web/tests/moment-detail.test.ts` and update `momentWithoutAnalyses()` and `momentWithAnalyses()` to include an `annotations: []` field. Find:

```typescript
function momentWithoutAnalyses() {
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: []
  };
}

function momentWithAnalyses() {
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: [
```

Add `annotations: []` to each (respecting the current structure):

```typescript
function momentWithoutAnalyses() {
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: [],
    annotations: []
  };
}

function momentWithAnalyses() {
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: [
```
(Leave the rest of `momentWithAnalyses` intact, but also append `annotations: []` inside the returned object — immediately before the closing `};`.)

The returned object of `momentWithAnalyses` should then look like:

```typescript
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: [ /* existing items */ ],
    annotations: []
  };
```

Then append an entirely new test file block inside the existing `describe('MomentDetail', ...)` block. Add these tests before the closing `});` of the describe block:

```typescript

  it('renders an empty notes thread with a textarea + Add button', () => {
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });
    expect(screen.getByPlaceholderText(/type a new note/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add note/i })).toBeInTheDocument();
  });

  it('renders prior annotations in the thread in chronological order', () => {
    const moment = {
      ...momentWithoutAnalyses(),
      annotations: [
        { id: 'a1', body: 'earlier thought', created_at: 100 },
        { id: 'a2', body: 'later thought', created_at: 200 }
      ]
    };
    render(MomentDetail, { rollId: 'r1', moment });
    const earlier = screen.getByText('earlier thought');
    const later = screen.getByText('later thought');
    expect(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('submitting a new note via Add button calls PATCH and appends to the thread', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({ id: 'a-new', body: 'fresh note', created_at: 999 })
      })
    );

    const user = userEvent.setup();
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });

    await user.type(screen.getByPlaceholderText(/type a new note/i), 'fresh note');
    await user.click(screen.getByRole('button', { name: /add note/i }));

    await waitFor(() => {
      expect(screen.getByText('fresh note')).toBeInTheDocument();
    });
    // Textarea clears after submit.
    expect((screen.getByPlaceholderText(/type a new note/i) as HTMLTextAreaElement).value).toBe(
      ''
    );
  });

  it('does not submit when the textarea is empty or whitespace', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });

    await user.click(screen.getByRole('button', { name: /add note/i }));
    expect(fetchMock).not.toHaveBeenCalled();

    await user.type(screen.getByPlaceholderText(/type a new note/i), '   ');
    await user.click(screen.getByRole('button', { name: /add note/i }));
    expect(fetchMock).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: the 4 new tests fail (no textarea, no thread rendering). Existing 12 pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/moment-detail.test.ts
git commit -m "test(bjj-app): add MomentDetail notes-thread tests (failing — no impl)"
```

---

## Task 20: Extend `MomentDetail.svelte` with notes thread + textarea (implementation)

**Files:**
- Modify: `tools/bjj-app/web/src/lib/components/MomentDetail.svelte`

- [ ] **Step 1: Replace the component**

Replace the entire contents of `tools/bjj-app/web/src/lib/components/MomentDetail.svelte` with:

```svelte
<script lang="ts">
  import { addAnnotation, analyseMoment, ApiError } from '$lib/api';
  import type { Analysis, AnalyseMomentEvent, Annotation, Moment } from '$lib/types';

  let {
    rollId,
    moment,
    onanalysed,
    onannotated
  }: {
    rollId: string;
    moment: Moment;
    onanalysed?: (m: Moment) => void;
    onannotated?: (m: Moment) => void;
  } = $props();

  let analysing = $state(false);
  let partial = $state('');
  let analyseError = $state<string | null>(null);
  let localAnalyses = $state<Analysis[]>(moment.analyses);
  let localAnnotations = $state<Annotation[]>(moment.annotations);
  let noteDraft = $state('');
  let adding = $state(false);
  let annotateError = $state<string | null>(null);

  $effect(() => {
    localAnalyses = moment.analyses;
    localAnnotations = moment.annotations;
    partial = '';
    analyseError = null;
    noteDraft = '';
    annotateError = null;
  });

  const greig = $derived(localAnalyses.find((a) => a.player === 'greig'));
  const anthony = $derived(localAnalyses.find((a) => a.player === 'anthony'));

  function formatMomentTime(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function formatCreatedAt(unix_s: number): string {
    const d = new Date(unix_s * 1000);
    const mm = d.toLocaleString(undefined, { month: 'short' });
    const dd = d.getDate();
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${mm} ${dd} ${hh}:${mi}`;
  }

  async function onAnalyseClick() {
    if (analysing) return;
    analysing = true;
    partial = '';
    analyseError = null;
    try {
      for await (const event of analyseMoment(rollId, moment.frame_idx)) {
        handleAnalyseEvent(event);
      }
    } catch (err) {
      analyseError = err instanceof ApiError ? err.message : String(err);
    } finally {
      analysing = false;
    }
  }

  function handleAnalyseEvent(event: AnalyseMomentEvent) {
    if (event.stage === 'streaming') {
      partial = event.text;
    } else if (event.stage === 'done') {
      const a = event.analysis;
      const fabricated: Analysis[] = [
        {
          id: `pending-${moment.id}-greig`,
          player: 'greig',
          position_id: a.greig.position,
          confidence: a.greig.confidence,
          description: a.description,
          coach_tip: a.coach_tip
        },
        {
          id: `pending-${moment.id}-anthony`,
          player: 'anthony',
          position_id: a.anthony.position,
          confidence: a.anthony.confidence,
          description: null,
          coach_tip: null
        }
      ];
      localAnalyses = fabricated;
      partial = '';
      onanalysed?.({ ...moment, analyses: fabricated, annotations: localAnnotations });
    } else if (event.stage === 'error') {
      if (event.kind === 'rate_limited' && event.retry_after_s) {
        analyseError = `Claude cooldown — ${event.retry_after_s}s until next call`;
      } else {
        analyseError = event.detail ?? `Analyse failed (${event.kind})`;
      }
    }
  }

  async function onAddNote() {
    const body = noteDraft.trim();
    if (!body || adding) return;
    adding = true;
    annotateError = null;
    try {
      const newRow = await addAnnotation(rollId, moment.id, body);
      localAnnotations = [...localAnnotations, newRow];
      noteDraft = '';
      onannotated?.({ ...moment, analyses: localAnalyses, annotations: localAnnotations });
    } catch (err) {
      annotateError = err instanceof ApiError ? err.message : String(err);
    } finally {
      adding = false;
    }
  }

  function onNoteKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      onAddNote();
    }
  }
</script>

<section class="space-y-3 rounded-lg border border-white/10 bg-white/[0.02] p-4">
  <header class="flex items-baseline gap-3">
    <span class="text-lg font-mono tabular-nums text-white/90">
      {formatMomentTime(moment.timestamp_s)}
    </span>
    <span class="text-[10px] uppercase tracking-wider text-white/40">Selected moment</span>
  </header>

  {#if analyseError}
    <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      {analyseError}
    </div>
  {/if}

  {#if localAnalyses.length > 0}
    <div class="grid gap-2 sm:grid-cols-2">
      {#if greig}
        <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
          <div class="text-[10px] uppercase tracking-wider text-white/40">Greig</div>
          <div class="mt-0.5 font-mono text-xs text-white/85">{greig.position_id}</div>
          {#if greig.confidence != null}
            <div class="text-[11px] text-white/40">
              confidence {(greig.confidence * 100).toFixed(0)}%
            </div>
          {/if}
        </div>
      {/if}
      {#if anthony}
        <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
          <div class="text-[10px] uppercase tracking-wider text-white/40">Anthony</div>
          <div class="mt-0.5 font-mono text-xs text-white/85">{anthony.position_id}</div>
          {#if anthony.confidence != null}
            <div class="text-[11px] text-white/40">
              confidence {(anthony.confidence * 100).toFixed(0)}%
            </div>
          {/if}
        </div>
      {/if}
    </div>

    {#if greig?.description}
      <p class="text-sm leading-relaxed text-white/80">{greig.description}</p>
    {/if}
    {#if greig?.coach_tip}
      <div class="border-l-2 border-amber-400/60 pl-3 text-sm text-amber-100/90">
        {greig.coach_tip}
      </div>
    {/if}
  {:else if analysing}
    <div class="space-y-2">
      <div class="text-xs text-white/55">Streaming from Claude Opus 4.7…</div>
      {#if partial}
        <pre
          class="whitespace-pre-wrap rounded-md bg-black/30 p-2 font-mono text-[11px] text-white/70"
        >{partial}</pre>
      {/if}
    </div>
  {:else}
    <button
      type="button"
      onclick={onAnalyseClick}
      class="rounded-md border border-blue-400/40 bg-blue-500/20 px-3 py-1.5 text-xs font-medium text-blue-100 hover:bg-blue-500/30 transition-colors"
    >
      Analyse this moment with Claude Opus 4.7
    </button>
  {/if}

  <!-- --- Your notes for this moment --- -->
  <div class="space-y-2 border-t border-white/8 pt-3">
    <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
      Your notes for this moment
    </div>

    {#if localAnnotations.length > 0}
      <ul class="space-y-1">
        {#each localAnnotations as a (a.id)}
          <li class="text-sm text-white/80">
            <span class="text-[10px] text-white/40">({formatCreatedAt(a.created_at)})</span>
            <span class="ml-1">{a.body}</span>
          </li>
        {/each}
      </ul>
    {/if}

    {#if annotateError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {annotateError}
      </div>
    {/if}

    <textarea
      bind:value={noteDraft}
      onkeydown={onNoteKeydown}
      placeholder="Type a new note…  (Cmd-Enter to submit)"
      class="w-full min-h-[60px] rounded-md border border-white/10 bg-white/[0.02] p-2 text-sm text-white/85 placeholder:text-white/30 focus:border-white/30 outline-none"
    ></textarea>

    <div class="flex items-center justify-end">
      <button
        type="button"
        onclick={onAddNote}
        disabled={adding || !noteDraft.trim()}
        class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-white/85 hover:bg-white/[0.08] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {adding ? 'Adding…' : 'Add note'}
      </button>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 16 passed (12 existing + 4 new).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/components/MomentDetail.svelte
git commit -m "feat(bjj-app): add notes thread + textarea to MomentDetail"
```

---

## Task 21: Write failing tests for `PublishConflictDialog.svelte`

**Files:**
- Create: `tools/bjj-app/web/tests/publish-conflict.test.ts`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/web/tests/publish-conflict.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import PublishConflictDialog from '../src/lib/components/PublishConflictDialog.svelte';

describe('PublishConflictDialog', () => {
  it('renders the conflict message and both buttons when open', () => {
    render(PublishConflictDialog, { open: true, onOverwrite: vi.fn(), onCancel: vi.fn() });
    expect(screen.getByText(/edited in Obsidian/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /overwrite/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('renders nothing when closed', () => {
    render(PublishConflictDialog, { open: false, onOverwrite: vi.fn(), onCancel: vi.fn() });
    expect(screen.queryByText(/edited in Obsidian/i)).toBeNull();
  });

  it('calls onOverwrite when Overwrite is clicked', async () => {
    const onOverwrite = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(PublishConflictDialog, { open: true, onOverwrite, onCancel });
    await user.click(screen.getByRole('button', { name: /overwrite/i }));
    expect(onOverwrite).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('calls onCancel when Cancel is clicked', async () => {
    const onOverwrite = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(PublishConflictDialog, { open: true, onOverwrite, onCancel });
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onOverwrite).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: the 4 new tests fail (component does not exist).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/publish-conflict.test.ts
git commit -m "test(bjj-app): add PublishConflictDialog tests (failing — no impl)"
```

---

## Task 22: Implement `PublishConflictDialog.svelte`

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/PublishConflictDialog.svelte`

- [ ] **Step 1: Write the component**

Create `tools/bjj-app/web/src/lib/components/PublishConflictDialog.svelte`:

```svelte
<script lang="ts">
  let {
    open,
    onOverwrite,
    onCancel
  }: {
    open: boolean;
    onOverwrite: () => void;
    onCancel: () => void;
  } = $props();
</script>

{#if open}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
  >
    <div class="max-w-md rounded-lg border border-white/12 bg-black/80 p-5 shadow-lg">
      <h2 class="text-sm font-semibold text-white/95">Vault conflict</h2>
      <p class="mt-2 text-sm text-white/70">
        Your Notes was edited in Obsidian since you last published. If you overwrite, the external
        edit will be lost (check git if you need to recover).
      </p>
      <div class="mt-4 flex items-center justify-end gap-2">
        <button
          type="button"
          onclick={onCancel}
          class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-white/75 hover:bg-white/[0.08] transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onclick={onOverwrite}
          class="rounded-md border border-rose-500/40 bg-rose-500/20 px-3 py-1.5 text-xs font-medium text-rose-100 hover:bg-rose-500/30 transition-colors"
        >
          Overwrite
        </button>
      </div>
    </div>
  </div>
{/if}
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 20 passed (16 existing + 4 new).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/components/PublishConflictDialog.svelte
git commit -m "feat(bjj-app): add PublishConflictDialog component"
```

---

## Task 23: Home page — conditional link based on `roll_id` (tests + impl)

**Files:**
- Modify: `tools/bjj-app/web/tests/home.test.ts`
- Modify: `tools/bjj-app/web/src/routes/+page.svelte`

- [ ] **Step 1: Extend home.test.ts**

Open `tools/bjj-app/web/tests/home.test.ts`. Append these tests before the closing `});` of the final describe block:

```typescript

  it('renders a clickable anchor for rolls with a roll_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => [
          {
            id: '2026-04-21 - sample',
            title: 'Sample roll',
            date: '2026-04-21',
            partner: 'Anthony',
            duration: '3:45',
            result: 'unknown',
            roll_id: 'abc123'
          }
        ]
      })
    );

    const { default: Page } = await import('../src/routes/+page.svelte');
    render(Page);

    await waitFor(() => {
      const link = screen.getByRole('link', { name: /sample roll/i });
      expect(link).toHaveAttribute('href', '/review/abc123');
    });
  });

  it('renders a non-link tile for rolls without a roll_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => [
          {
            id: '2026-04-14 - legacy',
            title: 'Legacy roll',
            date: '2026-04-14',
            partner: null,
            duration: null,
            result: null,
            roll_id: null
          }
        ]
      })
    );

    const { default: Page } = await import('../src/routes/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText(/legacy roll/i)).toBeInTheDocument();
      // No link with that text exists.
      expect(screen.queryByRole('link', { name: /legacy roll/i })).toBeNull();
      // An ".md only" badge is rendered.
      expect(screen.getByText(/md only/i)).toBeInTheDocument();
    });
  });
```

If the existing home test file doesn't already have these imports/globals at the top, ensure `waitFor` is imported from `@testing-library/svelte` and `vi` from `vitest` — the existing file imports them already, so just verify.

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: the 2 new tests fail.

- [ ] **Step 3: Update the home page**

Open `tools/bjj-app/web/src/routes/+page.svelte`.

Find the `{#each rolls as roll (roll.id)}` block inside the list rendering. Replace the `<li>` block content (currently an `<a href=...>` wrapping the tile) with a conditional that renders either an anchor or a muted div based on `roll.roll_id`:

Replace:

```svelte
      {#each rolls as roll (roll.id)}
        <li>
          <a
            href={`/review/${encodeURIComponent(roll.id)}`}
            class="block rounded-lg border border-white/8 bg-white/[0.02] hover:bg-white/[0.05] p-4 transition-colors"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <h2 class="text-base font-medium leading-tight truncate">{roll.title}</h2>
                <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/55">
                  <span>{roll.date}</span>
                  {#if roll.partner}<span>{roll.partner}</span>{/if}
                  {#if roll.duration}<span>{roll.duration}</span>{/if}
                </div>
              </div>
              <span
                class={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${resultBadgeClass(roll.result)}`}
              >
                {resultLabel(roll.result)}
              </span>
            </div>
          </a>
        </li>
      {/each}
```

with:

```svelte
      {#each rolls as roll (roll.id)}
        <li>
          {#if roll.roll_id}
            <a
              href={`/review/${encodeURIComponent(roll.roll_id)}`}
              class="block rounded-lg border border-white/8 bg-white/[0.02] hover:bg-white/[0.05] p-4 transition-colors"
            >
              <div class="flex items-start justify-between gap-4">
                <div class="min-w-0 flex-1">
                  <h2 class="text-base font-medium leading-tight truncate">{roll.title}</h2>
                  <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/55">
                    <span>{roll.date}</span>
                    {#if roll.partner}<span>{roll.partner}</span>{/if}
                    {#if roll.duration}<span>{roll.duration}</span>{/if}
                  </div>
                </div>
                <span
                  class={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${resultBadgeClass(roll.result)}`}
                >
                  {resultLabel(roll.result)}
                </span>
              </div>
            </a>
          {:else}
            <div
              class="block rounded-lg border border-white/8 bg-white/[0.02] p-4 opacity-70 cursor-default"
            >
              <div class="flex items-start justify-between gap-4">
                <div class="min-w-0 flex-1">
                  <h2 class="text-base font-medium leading-tight truncate">{roll.title}</h2>
                  <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/55">
                    <span>{roll.date}</span>
                    {#if roll.partner}<span>{roll.partner}</span>{/if}
                    {#if roll.duration}<span>{roll.duration}</span>{/if}
                  </div>
                </div>
                <span
                  class="shrink-0 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-white/50"
                >
                  md only
                </span>
              </div>
            </div>
          {/if}
        </li>
      {/each}
```

- [ ] **Step 4: Run — must pass**

```bash
npm test
```

Expected: 22 passed (20 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/+page.svelte tools/bjj-app/web/tests/home.test.ts
git commit -m "feat(bjj-app): home page routes via roll_id, mutes legacy rolls"
```

---

## Task 24: Review page — wire Save to Vault button + conflict dialog (tests + impl)

**Files:**
- Modify: `tools/bjj-app/web/tests/review-analyse.test.ts`
- Modify: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`

- [ ] **Step 1: Update test fixtures + add tests**

Open `tools/bjj-app/web/tests/review-analyse.test.ts`. Find `detailWithoutMoments` and `detailWithMoments` helpers. Update them to include the new `vault_path: null, vault_published_at: null` fields on the roll, and `annotations: []` on each moment.

Replace:

```typescript
function detailWithoutMoments() {
  return {
    id: 'abc123',
    title: 'Review analyse test',
    date: '2026-04-20',
    partner: null,
    duration_s: 10.0,
    result: 'unknown',
    video_url: '/assets/abc123/source.mp4',
    moments: []
  };
}
```

with:

```typescript
function detailWithoutMoments() {
  return {
    id: 'abc123',
    title: 'Review analyse test',
    date: '2026-04-20',
    partner: null,
    duration_s: 10.0,
    result: 'unknown',
    video_url: '/assets/abc123/source.mp4',
    vault_path: null,
    vault_published_at: null,
    moments: []
  };
}
```

Replace `detailWithMoments` similarly — it should keep its extension of `detailWithoutMoments` via spread, but update its moment fixtures to include `annotations: []`. The final shape:

```typescript
function detailWithMoments() {
  return {
    ...detailWithoutMoments(),
    moments: [
      { id: 'm1', frame_idx: 2, timestamp_s: 2.0, pose_delta: 0.5, analyses: [], annotations: [] },
      { id: 'm2', frame_idx: 5, timestamp_s: 5.0, pose_delta: 1.2, analyses: [], annotations: [] }
    ]
  };
}
```

Then append these new tests before the closing `});` of the describe block:

```typescript

  it('clicking Save to Vault calls POST /publish and toasts on success', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => detailWithMoments()
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        vault_path: 'Roll Log/2026-04-20 - Review analyse test.md',
        your_notes_hash: 'newhash',
        vault_published_at: 1700000000
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    const { default: Page } = await import('../src/routes/review/[id]/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save to vault/i }));

    await waitFor(() => {
      expect(screen.getByText(/published to/i)).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const publishCall = fetchMock.mock.calls[1];
    expect(publishCall[0]).toContain('/publish');
  });

  it('shows the conflict dialog on 409 and re-sends with force on Overwrite', async () => {
    const fetchMock = vi.fn();
    // 1. GET detail
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => detailWithMoments()
    });
    // 2. first POST /publish → 409
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({
        detail: 'Your Notes was edited in Obsidian since last publish',
        current_hash: 'cur',
        stored_hash: 'stored'
      })
    });
    // 3. second POST /publish with force → 200
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        vault_path: 'Roll Log/x.md',
        your_notes_hash: 'newhash',
        vault_published_at: 1700000999
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    const { default: Page } = await import('../src/routes/review/[id]/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save to vault/i }));
    // Dialog appears
    await waitFor(() => {
      expect(screen.getByText(/edited in obsidian/i)).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /overwrite/i }));
    // Success toast after force retry
    await waitFor(() => {
      expect(screen.getByText(/published to/i)).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const forceCall = fetchMock.mock.calls[2];
    const forceBody = JSON.parse(forceCall[1].body);
    expect(forceBody.force).toBe(true);
  });
```

- [ ] **Step 2: Run — must fail (new tests)**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 2 new review-analyse tests fail (no Save to Vault button).

- [ ] **Step 3: Update the review page**

Open `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`. Replace its entire contents with:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import {
    analyseRoll,
    ApiError,
    getRoll,
    publishRoll,
    PublishConflictError
  } from '$lib/api';
  import MomentDetail from '$lib/components/MomentDetail.svelte';
  import PublishConflictDialog from '$lib/components/PublishConflictDialog.svelte';
  import type { AnalyseEvent, Moment, RollDetail } from '$lib/types';

  let roll = $state<RollDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let analysing = $state(false);
  let progress = $state<{ stage: string; pct: number } | null>(null);
  let selectedMomentId = $state<string | null>(null);
  let publishing = $state(false);
  let publishError = $state<string | null>(null);
  let publishToast = $state<string | null>(null);
  let conflictOpen = $state(false);

  let videoEl: HTMLVideoElement | undefined = $state();

  const selectedMoment = $derived(
    roll?.moments.find((m) => m.id === selectedMomentId) ?? null
  );

  onMount(async () => {
    const id = $page.params.id;
    try {
      roll = await getRoll(id);
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      loading = false;
    }
  });

  async function onAnalyseClick() {
    if (!roll || analysing) return;
    analysing = true;
    progress = { stage: 'frames', pct: 0 };
    try {
      for await (const event of analyseRoll(roll.id)) {
        handleAnalyseEvent(event);
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      analysing = false;
      progress = null;
    }
  }

  function handleAnalyseEvent(event: AnalyseEvent) {
    if (event.stage === 'done') {
      if (!roll) return;
      roll.moments = event.moments.map((m) => ({
        id: `pending-${m.frame_idx}`,
        frame_idx: m.frame_idx,
        timestamp_s: m.timestamp_s,
        pose_delta: m.pose_delta,
        analyses: [],
        annotations: []
      })) as Moment[];
      progress = { stage: 'done', pct: 100 };
    } else {
      progress = { stage: event.stage, pct: event.pct };
    }
  }

  function formatDuration(seconds: number | null | undefined): string {
    if (!seconds) return '—';
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function formatMomentTime(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function progressLabel(p: { stage: string; pct: number } | null): string {
    if (!p) return '';
    if (p.stage === 'frames') return `Extracting frames… ${p.pct}%`;
    if (p.stage === 'pose') return `Detecting poses… ${p.pct}%`;
    if (p.stage === 'done') return 'Analysis complete';
    return `${p.stage}… ${p.pct}%`;
  }

  function onChipClick(moment: Moment) {
    selectedMomentId = moment.id;
    if (videoEl) {
      videoEl.currentTime = moment.timestamp_s;
      videoEl.play().catch(() => {
        /* autoplay may be blocked; that's fine */
      });
    }
  }

  function onMomentAnalysed(updated: Moment) {
    if (!roll) return;
    roll.moments = roll.moments.map((m) => (m.id === updated.id ? updated : m));
  }

  function onMomentAnnotated(updated: Moment) {
    if (!roll) return;
    roll.moments = roll.moments.map((m) => (m.id === updated.id ? updated : m));
  }

  function chipStateClass(m: Moment, isSelected: boolean): string {
    const base = 'rounded-md px-2.5 py-1 text-xs font-mono tabular-nums transition-colors';
    if (m.analyses.length > 0) {
      return `${base} border bg-emerald-500/15 border-emerald-400/40 text-emerald-100 hover:bg-emerald-500/25${
        isSelected ? ' ring-1 ring-emerald-300' : ''
      }`;
    }
    return `${base} border border-dashed bg-white/[0.02] border-white/20 text-white/75 hover:bg-white/[0.05] hover:border-white/40${
      isSelected ? ' ring-1 ring-white/40' : ''
    }`;
  }

  async function onSaveToVault(options: { force?: boolean } = {}) {
    if (!roll || publishing) return;
    publishing = true;
    publishError = null;
    publishToast = null;
    try {
      const result = await publishRoll(roll.id, options);
      publishToast = `Published to ${result.vault_path}`;
      roll.vault_path = result.vault_path;
      roll.vault_published_at = result.vault_published_at;
    } catch (err) {
      if (err instanceof PublishConflictError) {
        conflictOpen = true;
      } else {
        publishError = err instanceof ApiError ? err.message : String(err);
      }
    } finally {
      publishing = false;
    }
  }

  async function onOverwrite() {
    conflictOpen = false;
    await onSaveToVault({ force: true });
  }

  function onCancelConflict() {
    conflictOpen = false;
  }
</script>

{#if loading}
  <p class="text-white/50 text-sm">Loading roll…</p>
{:else if error || !roll}
  <div class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
    <strong>Couldn't load roll:</strong>
    {error ?? 'Unknown error'}
  </div>
{:else}
  <section class="space-y-5">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold tracking-tight">{roll.title}</h1>
        <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-white/55">
          <span>{roll.date}</span>
          {#if roll.partner}<span>{roll.partner}</span>{/if}
          <span>{formatDuration(roll.duration_s)}</span>
        </div>
      </div>
      <div class="flex gap-2">
        <button
          type="button"
          onclick={onAnalyseClick}
          disabled={analysing}
          class="rounded-md px-3 py-1.5 text-xs font-medium bg-blue-500/20 border border-blue-400/40 text-blue-100 hover:bg-blue-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {analysing ? 'Analysing…' : 'Analyse'}
        </button>
      </div>
    </header>

    <div class="rounded-lg overflow-hidden border border-white/8 bg-black">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video
        bind:this={videoEl}
        controls
        preload="metadata"
        class="w-full aspect-video bg-black"
      >
        <source src={roll.video_url} type="video/mp4" />
        Your browser can't play this video file.
      </video>
    </div>

    {#if progress}
      <div
        class="rounded-md border border-white/10 bg-white/[0.02] px-4 py-2 text-xs text-white/65"
        role="status"
      >
        {progressLabel(progress)}
      </div>
    {/if}

    {#if roll.moments.length > 0}
      <div class="space-y-2">
        <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
          Moments ({roll.moments.length})
        </div>
        <div class="flex flex-wrap gap-1.5">
          {#each roll.moments as moment (moment.id)}
            <button
              type="button"
              onclick={() => onChipClick(moment)}
              class={chipStateClass(moment, moment.id === selectedMomentId)}
            >
              {formatMomentTime(moment.timestamp_s)}
            </button>
          {/each}
        </div>
      </div>

      {#if selectedMoment}
        <MomentDetail
          rollId={roll.id}
          moment={selectedMoment}
          onanalysed={onMomentAnalysed}
          onannotated={onMomentAnnotated}
        />
      {:else}
        <p class="text-[11px] text-white/35">
          Click a chip to see the moment and analyse it with Claude.
        </p>
      {/if}
    {:else if !analysing}
      <div class="rounded-lg border border-white/10 bg-white/[0.02] p-6 text-center">
        <p class="text-sm text-white/60">No moments yet.</p>
        <p class="mt-1 text-xs text-white/35">
          Click <strong>Analyse</strong> to run the pose pre-pass and flag interesting moments.
        </p>
      </div>
    {/if}

    <footer class="flex items-center justify-between gap-3 border-t border-white/8 pt-4">
      <div class="text-[11px] text-white/40">
        {#if roll.vault_path}
          Last published to <span class="font-mono">{roll.vault_path}</span>
        {:else}
          Not yet published to vault.
        {/if}
      </div>
      <button
        type="button"
        onclick={() => onSaveToVault()}
        disabled={publishing}
        class="rounded-md border border-amber-400/40 bg-amber-500/15 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {publishing ? 'Publishing…' : 'Save to Vault'}
      </button>
    </footer>

    {#if publishToast}
      <div class="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
        {publishToast}
      </div>
    {/if}
    {#if publishError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {publishError}
      </div>
    {/if}

    <PublishConflictDialog
      open={conflictOpen}
      onOverwrite={onOverwrite}
      onCancel={onCancelConflict}
    />
  </section>
{/if}
```

- [ ] **Step 4: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 24 passed (22 existing + 2 new review-analyse Save-to-Vault tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/review/[id]/+page.svelte tools/bjj-app/web/tests/review-analyse.test.ts
git commit -m "feat(bjj-app): wire Save to Vault button + conflict dialog in review page"
```

---

## Task 25: End-to-end browser smoke test

**Files:** none — manual verification.

- [ ] **Step 1: Start dev mode**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && ./scripts/dev.sh
```

- [ ] **Step 2: Upload + pose pre-pass + analyse a moment with Claude** (M3 path, confirms nothing regressed)

Upload a short video at `http://127.0.0.1:5173/new`. Click **Analyse** on the review page → chips appear. Click a chip → click "Analyse this moment with Claude Opus 4.7" → streaming → cards + coach tip appear, chip turns emerald.

- [ ] **Step 3: Add multiple annotations to a single moment**

On the same selected moment, type a note into the textarea: "frames too wide". Click **Add note**. The note appears in the thread. Type a second: "also hip escape needed earlier". Click **Add note** (or Cmd-Enter). Both notes appear in chronological order above the textarea.

- [ ] **Step 4: Add annotations to a different moment**

Click a different chip, add a note. Click back to the first chip — the first moment's notes are still there. Click forward — the second moment's notes are distinct.

- [ ] **Step 5: First "Save to Vault"**

Click the **Save to Vault** button in the footer. Expected: button briefly shows "Publishing…", then a green toast appears: "Published to Roll Log/YYYY-MM-DD - <title>.md". The footer text updates to "Last published to Roll Log/...".

Open the file in Obsidian (or just `cat` it): verify the frontmatter has `roll_id: <uuid>`, the title is `# <title>`, and `## Your Notes` contains H3 per moment with your bullets.

- [ ] **Step 6: Verify home page clickability**

Navigate back to `http://127.0.0.1:5173/`. Expected: the just-published roll now appears in the list as a clickable tile. Click it → `/review/<uuid>` loads with all your moments and annotations.

- [ ] **Step 7: Hash-based conflict detection**

In Obsidian, open the roll's markdown and add a line inside `## Your Notes`:
```
> manually edited in Obsidian
```
Save. Back in the web app, add one more annotation to a moment. Click **Save to Vault**. Expected: a modal appears — "Vault conflict — Your Notes was edited in Obsidian…".

Click **Overwrite**. Expected: toast "Published to …". Re-open the file in Obsidian — your manual line is gone, the latest annotations are present.

- [ ] **Step 8: Edits to other sections preserved**

In Obsidian, scroll to the end of the file and append a new section:
```
## Overall Notes

This was a tough roll; need to work on framing.
```
Save. Back in the app, add another annotation + **Save to Vault**. Expected: no conflict dialog; toast fires normally. Re-open in Obsidian — your `## Overall Notes` section is intact, and the new annotation is in `## Your Notes`.

- [ ] **Step 9: Verify database state**

In a separate terminal:
```bash
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT id, vault_path, vault_published_at IS NOT NULL AS published FROM rolls ORDER BY created_at DESC LIMIT 3;"
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT moment_id, body FROM annotations ORDER BY created_at DESC LIMIT 5;"
```
Expected: the most recent roll has a non-null `vault_path`; `annotations` table has rows.

- [ ] **Step 10: Cleanup (optional)**

```bash
# Find the test roll
ROLL_ID=$(sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT id FROM rolls ORDER BY created_at DESC LIMIT 1;")
VAULT_PATH=$(sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT vault_path FROM rolls WHERE id='$ROLL_ID';")
rm -f "/Users/greigbradley/Desktop/BJJ_Analysis/$VAULT_PATH"
rm -rf "/Users/greigbradley/Desktop/BJJ_Analysis/assets/$ROLL_ID"
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "DELETE FROM rolls WHERE id='$ROLL_ID';"
```

- [ ] **Step 11: Stop dev server** (Ctrl-C).

---

## Task 26: Update README with M4 status

**Files:**
- Modify: `tools/bjj-app/README.md`

- [ ] **Step 1: Replace the Milestones section**

Find the `## Milestones` section in `tools/bjj-app/README.md` and replace it (plus everything below it) with:

```markdown
## Milestones

- **M1 (shipped):** Scaffolding. Home page lists vault's `Roll Log/` via `GET /api/rolls`.
- **M2a (shipped):** Video upload (`POST /api/rolls`), review page skeleton, `/assets/` static mount.
- **M2b (shipped):** MediaPipe pose pre-pass, `POST /api/rolls/:id/analyse` SSE endpoint, timeline chips seek the video on click.
- **M3 (shipped):** Claude CLI adapter (sole `claude -p` caller), `POST /api/rolls/:id/moments/:frame_idx/analyse` streaming, SQLite cache, sliding-window rate limiter. Security audit at `docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`.
- **M4 (this milestone):** Append-only annotations per moment, explicit "Save to Vault" publish to `Roll Log/*.md`, hash-based conflict detection on `## Your Notes` only, home page routes via `roll_id` frontmatter. Design at `docs/superpowers/specs/2026-04-21-bjj-app-m4-annotations-vault-writeback-design.md`.
- **M5 (next):** Graph page + mini graph. Cytoscape.js clustered layout with both players' paths overlaid.
- **M6–M8:** Summary step + PDF export, PWA + mobile polish, cleanup.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/README.md
git commit -m "docs(bjj-app): document M4 (annotations + vault write-back)"
```

---

## Completion criteria for M4

1. `pytest tests/backend -v` → all green, including the new M4 tests (~30 new tests added across six files).
2. `npm test` (in `web/`) → 24 passed (12 from M3 + 12 new M4: 4 moment-detail + 4 publish-conflict + 2 home + 2 review-analyse).
3. Dev-mode smoke test (Task 25) passes all 11 steps.
4. No M1/M2a/M2b/M3 tests regress.
5. The vault writer is the only module that writes to `Roll Log/*.md` (a grep of `server/` for `write_text` / `write_bytes` / `os.replace` under `Roll Log` finds only `vault_writer.py`).

---

## Out of scope (explicitly deferred to later milestones)

| Deliverable | Why deferred |
|---|---|
| Edit / delete annotations | Append-only MVP. Can add `PUT /annotations/:id` / `DELETE /annotations/:id` in a future milestone. |
| Analyses serialised to vault | M6 will extend vault_writer to render scores + key moments + summary + coach tips alongside `## Your Notes`. |
| Retrofit of legacy vault-only markdown | Pre-M2a `Roll Log/*.md` files stay visible but non-clickable. Retrofit can come later with its own migration path. |
| Three-way merge on conflict | Terse dialog + git recovery is the V1 answer. A visual diff viewer can be added if the conflict path gets used often. |
| Concurrent publish serialization | Not needed for a single-user app. Would matter if the app ever served multiple clients. |
| Upload-time vault creation | `POST /rolls` still doesn't write markdown — publish is explicit. |
