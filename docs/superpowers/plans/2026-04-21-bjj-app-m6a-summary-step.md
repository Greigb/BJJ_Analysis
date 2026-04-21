# BJJ App M6a — Summary Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a "Finalise" button on `/review/[id]` that runs one Claude call across all analysed moments + annotations, persists scores + summary + improvements + strengths + 3 key-moment pointers to SQLite, and extends "Save to Vault" so the markdown file gains six new summary sections (Summary / Scores / Position Distribution / Key Moments / Top Improvements / Strengths Observed) alongside `## Your Notes`.

**Architecture:** Three small pure helpers in a new `server/analysis/summarise.py` (prompt builder, response parser, distribution calculator). A thin new endpoint `api/summarise.py` orchestrates them. The existing M3 Claude adapter (`claude_cli.py`) gets a `run_claude(prompt)` entry point extracted for reuse; `analyse_frame` keeps its behaviour but calls the new seam internally. `vault_writer.py` grows one function (`render_summary_sections`) and its `publish` generalises from "splice Your Notes" to "splice every app-owned section" with a per-section hash map stored in a new `rolls.vault_summary_hashes` column. Frontend adds a `ScoresPanel.svelte` component above `MomentDetail` and a Finalise button in the review-page footer.

**Tech Stack:** No new dependencies. Python stdlib + `python-frontmatter` (already installed). Svelte 5 runes frontend. Reuses M3's `SlidingWindowLimiter`, M4's `_atomic_write` / `_extract_your_notes_section` pattern (generalised), M5's `load_taxonomy`.

**Scope (M6a only):**
- Backend: `server/analysis/summarise.py` (new), `server/analysis/claude_cli.py` (refactor), `server/analysis/vault_writer.py` (extend), `server/api/summarise.py` (new), `server/api/publish.py` (extend), `server/api/rolls.py` (extend `RollDetailOut`), `server/db.py` (migration + helper), `server/main.py` (register router).
- Frontend: `web/src/lib/types.ts` (new types), `web/src/lib/api.ts` (`summariseRoll`), `web/src/lib/components/ScoresPanel.svelte` (new), `web/src/routes/review/[id]/+page.svelte` (wire Finalise button + mount panel).
- Tests: 5 new backend files, 2 existing backend files extended, 1 new frontend file, 1 existing frontend file extended.
- Docs: README milestones update; M3 security audit one-line addendum.

**Explicitly out of scope (per spec):**
- WeasyPrint + `POST /api/rolls/:id/export/pdf` (M6b).
- Re-finalise confirmation dialog.
- Per-moment "pin as key moment" affordance.
- Versioned score history.
- Auto-finalise after N analyses.

---

## File Structure

```
tools/bjj-app/
├── server/
│   ├── analysis/
│   │   ├── summarise.py                 # NEW: build_summary_prompt + parse_summary_response + compute_distribution + CATEGORY_EMOJI
│   │   ├── claude_cli.py                # MODIFY: extract run_claude(prompt, *, settings, limiter, stream_callback) from analyse_frame
│   │   └── vault_writer.py              # MODIFY: render_summary_sections + generalised per-section splice + per-section hash map
│   ├── api/
│   │   ├── summarise.py                 # NEW: POST /api/rolls/:id/summarise
│   │   ├── publish.py                   # MODIFY: load taxonomy from app.state and pass to vault_writer.publish
│   │   └── rolls.py                     # MODIFY: RollDetailOut gains finalised_at + scores + distribution; get_roll_detail populates them
│   ├── db.py                            # MODIFY: schema migration for vault_summary_hashes + set_summary_state helper
│   └── main.py                          # MODIFY: register summarise_api.router
├── tests/backend/
│   ├── test_summarise.py                # NEW: pure helper tests
│   ├── test_api_summarise.py            # NEW: endpoint happy path + 400/404/429/502
│   ├── test_vault_writer_summary.py     # NEW: render + per-section splice + per-section conflict
│   ├── test_db_summary_state.py         # NEW: set_summary_state helper
│   ├── test_api_publish.py              # MODIFY: assert summary sections on finalised rolls
│   ├── test_db_schema_migration.py      # MODIFY: add vault_summary_hashes column test
│   └── test_claude_cli.py               # MODIFY: add run_claude tests; existing analyse_frame tests continue to pass
└── web/
    ├── src/
    │   ├── lib/
    │   │   ├── api.ts                   # MODIFY: add summariseRoll()
    │   │   ├── types.ts                 # MODIFY: add Scores, KeyMoment, SummaryPayload, Distribution; extend RollDetail
    │   │   └── components/
    │   │       └── ScoresPanel.svelte   # NEW
    │   └── routes/
    │       └── review/[id]/+page.svelte # MODIFY: mount ScoresPanel + Finalise button
    └── tests/
        ├── scores-panel.test.ts         # NEW
        └── review-analyse.test.ts       # MODIFY: Finalise-button tests + scores-panel visibility
```

### Responsibilities

- **`summarise.py`** — Pure functions, no IO, no subprocess. Three exports:
  - `build_summary_prompt(roll_row, moment_rows, analyses_by_moment, annotations_by_moment) -> str`.
  - `parse_summary_response(raw, valid_moment_ids) -> dict` — raises `SummaryResponseError` on any schema/validity failure.
  - `compute_distribution(analyses, categories) -> dict` — computes `timeline`, `counts`, `percentages`.
  - Module-level constant `CATEGORY_EMOJI` (dict). Module-level exception `SummaryResponseError`.
- **`claude_cli.run_claude`** — Takes a prompt string, returns raw assistant text. Owns: rate-limit acquisition, subprocess spawn, stream-json parsing, one retry on non-zero exit. Does NOT own: prompt construction, cache, response schema. Shared by `analyse_frame` and `api/summarise.py`.
- **`vault_writer.render_summary_sections`** — Pure function. Takes the parsed `scores_json` payload + `distribution` + `categories` taxonomy list → returns `dict[section_id, body_markdown]` for the six summary sections. Deterministic.
- **`vault_writer.publish`** — Generalised. Renders Your Notes body AND (if finalised) each summary section. Splice logic walks a list of section descriptors and checks each section's hash before overwriting.
- **`api/summarise.py`** — Thin HTTP shell. Load inputs, build prompt, run Claude, parse, persist, return payload + distribution.
- **`ScoresPanel.svelte`** — Presentational component. Props: `scores: SummaryPayload`, `distribution: Distribution`, `finalised_at: number`, `moments: Moment[]` (for looking up key-moment timestamps), `ongoto: (momentId: string) => void`.

### Wire types (frontend)

```typescript
export type Scores = {
  guard_retention: number;
  positional_awareness: number;
  transition_quality: number;
};

export type KeyMoment = {
  moment_id: string;
  note: string;
};

export type SummaryPayload = {
  summary: string;
  scores: Scores;
  top_improvements: string[];
  strengths: string[];
  key_moments: KeyMoment[];
};

export type Distribution = {
  timeline: string[];      // list of category_ids in chronological order
  counts: Record<string, number>;
  percentages: Record<string, number>;
};
```

`RollDetail` gains three optional fields:
```typescript
  finalised_at: number | null;
  scores: SummaryPayload | null;
  distribution: Distribution | null;
```

---

## Task 1: Schema migration — `vault_summary_hashes` column

**Files:**
- Modify: `tools/bjj-app/server/db.py`
- Modify: `tools/bjj-app/tests/backend/test_db_schema_migration.py`

- [ ] **Step 1: Write the failing test**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_db_schema_migration.py` and append:

```python


def test_init_db_fresh_includes_vault_summary_hashes_column(tmp_path: Path):
    db_path = tmp_path / "fresh.db"
    init_db(db_path)
    cols = _rolls_columns(db_path)
    assert "vault_summary_hashes" in cols


def test_init_db_migrates_vault_summary_hashes_on_existing_db(tmp_path: Path):
    """A pre-M6a DB (with all prior M1–M5 columns but no vault_summary_hashes)
    gets the new column added on next init_db."""
    db_path = tmp_path / "premigrate.db"
    # Simulate a pre-M6a rolls table: all M1-M5 columns, no vault_summary_hashes.
    with sqlite3.connect(db_path) as conn:
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
                created_at INTEGER NOT NULL,
                vault_path TEXT,
                vault_your_notes_hash TEXT,
                vault_published_at INTEGER,
                player_a_name TEXT,
                player_b_name TEXT
            );
            """
        )
        conn.commit()
    init_db(db_path)
    cols = _rolls_columns(db_path)
    assert "vault_summary_hashes" in cols
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_db_schema_migration.py -v
```

Expected: 2 new tests fail (column not present).

- [ ] **Step 3: Add the column to schema + migration**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/db.py`.

Find the `_ROLLS_M4_COLUMNS` tuple and extend with the new column:

```python
_ROLLS_M4_COLUMNS: tuple[tuple[str, str], ...] = (
    ("vault_path", "TEXT"),
    ("vault_your_notes_hash", "TEXT"),
    ("vault_published_at", "INTEGER"),
    ("player_a_name", "TEXT"),
    ("player_b_name", "TEXT"),
    ("vault_summary_hashes", "TEXT"),
)
```

(The M4 migration helper is already idempotent — just extending the tuple adds the column on any DB that doesn't yet have it.)

Also update `SCHEMA_SQL`'s `rolls` `CREATE TABLE IF NOT EXISTS` block — append the column at the end of the columns list so fresh installs get it too:

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
    vault_published_at INTEGER,
    player_a_name TEXT,
    player_b_name TEXT,
    vault_summary_hashes TEXT
);
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_db_schema_migration.py -v
```

Expected: all passing (the new 2 + prior tests).

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_schema_migration.py
git commit -m "feat(bjj-app): add vault_summary_hashes column migration for M6a"
```

---

## Task 2: DB helper — `set_summary_state`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_db_summary_state.py`
- Modify: `tools/bjj-app/server/db.py`

- [ ] **Step 1: Write the failing test**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_db_summary_state.py`:

```python
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
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_db_summary_state.py -v
```

Expected: ImportError on `set_summary_state` / `set_vault_summary_hashes`.

- [ ] **Step 3: Implement the helpers**

Append to the end of `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/db.py`:

```python


def set_summary_state(
    conn,
    *,
    roll_id: str,
    scores_payload: dict,
    finalised_at: int,
) -> None:
    """Write the parsed summary payload + finalised_at to the rolls row."""
    conn.execute(
        "UPDATE rolls SET scores_json = ?, finalised_at = ? WHERE id = ?",
        (json.dumps(scores_payload), finalised_at, roll_id),
    )
    conn.commit()


def set_vault_summary_hashes(
    conn,
    *,
    roll_id: str,
    hashes: dict | None,
) -> None:
    """Record per-section hash dict for the summary-owned vault sections.

    Pass None to clear (e.g. for a roll that's been un-finalised — currently no
    code path does this, but the helper accepts it for completeness).
    """
    value = json.dumps(hashes) if hashes is not None else None
    conn.execute(
        "UPDATE rolls SET vault_summary_hashes = ? WHERE id = ?",
        (value, roll_id),
    )
    conn.commit()
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_db_summary_state.py -v
```

Expected: 4 passed.

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py tools/bjj-app/tests/backend/test_db_summary_state.py
git commit -m "feat(bjj-app): add set_summary_state + set_vault_summary_hashes db helpers"
```

---

## Task 3: Pure helper — `compute_distribution`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_summarise.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_summarise.py`:

```python
"""Tests for summarise.py — pure helpers (build_summary_prompt, parse_summary_response, compute_distribution)."""
from __future__ import annotations

import json

import pytest

from server.analysis.summarise import (
    CATEGORY_EMOJI,
    SummaryResponseError,
    build_summary_prompt,
    compute_distribution,
    parse_summary_response,
)


# ---------- compute_distribution ----------


_FIXTURE_CATEGORIES = [
    {"id": "standing", "label": "Standing"},
    {"id": "guard_bottom", "label": "Guard (Bottom)"},
    {"id": "guard_top", "label": "Guard (Top)"},
    {"id": "scramble", "label": "Scramble"},
]

# Map position_id -> category for the fixture.
_FIXTURE_POSITION_TO_CATEGORY = {
    "standing_neutral": "standing",
    "closed_guard_bottom": "guard_bottom",
    "closed_guard_top": "guard_top",
    "scramble_entry": "scramble",
}


def _analyses(*position_ids_in_order: str) -> list[dict]:
    """Build a flat analyses fixture: one row per (moment, player='a') in order."""
    rows: list[dict] = []
    for i, pid in enumerate(position_ids_in_order):
        rows.append({
            "position_id": pid,
            "player": "a",
            "timestamp_s": float(i),
            "category": _FIXTURE_POSITION_TO_CATEGORY.get(pid, "scramble"),
        })
    return rows


def test_compute_distribution_returns_timeline_in_chronological_order():
    analyses = _analyses("standing_neutral", "closed_guard_bottom", "scramble_entry")
    dist = compute_distribution(analyses, _FIXTURE_CATEGORIES)
    assert dist["timeline"] == ["standing", "guard_bottom", "scramble"]


def test_compute_distribution_counts_per_category():
    analyses = _analyses(
        "standing_neutral",
        "closed_guard_bottom",
        "closed_guard_bottom",
        "closed_guard_bottom",
        "scramble_entry",
    )
    dist = compute_distribution(analyses, _FIXTURE_CATEGORIES)
    assert dist["counts"] == {"standing": 1, "guard_bottom": 3, "scramble": 1}


def test_compute_distribution_percentages_sum_to_100():
    analyses = _analyses(
        "standing_neutral", "closed_guard_bottom", "scramble_entry",
    )
    dist = compute_distribution(analyses, _FIXTURE_CATEGORIES)
    total = sum(dist["percentages"].values())
    assert 99 <= total <= 100  # integer rounding may yield 99


def test_compute_distribution_handles_empty_analyses():
    dist = compute_distribution([], _FIXTURE_CATEGORIES)
    assert dist == {"timeline": [], "counts": {}, "percentages": {}}


def test_compute_distribution_only_counts_player_a():
    # Player b analyses should be excluded from the distribution.
    analyses = [
        {"position_id": "standing_neutral", "player": "a", "timestamp_s": 0.0,
         "category": "standing"},
        {"position_id": "closed_guard_top", "player": "b", "timestamp_s": 0.0,
         "category": "guard_top"},
        {"position_id": "closed_guard_bottom", "player": "a", "timestamp_s": 1.0,
         "category": "guard_bottom"},
    ]
    dist = compute_distribution(analyses, _FIXTURE_CATEGORIES)
    assert dist["counts"] == {"standing": 1, "guard_bottom": 1}
    assert dist["timeline"] == ["standing", "guard_bottom"]


def test_category_emoji_covers_canonical_categories():
    expected = {
        "standing", "guard_bottom", "guard_top", "dominant_top",
        "inferior_bottom", "leg_entanglement", "scramble",
    }
    assert expected.issubset(set(CATEGORY_EMOJI.keys()))
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_summarise.py -v
```

Expected: ImportError on `server.analysis.summarise`.

- [ ] **Step 3: Implement `compute_distribution` + `CATEGORY_EMOJI`**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/analysis/summarise.py`:

```python
"""Pure helpers for the summary step — no IO, no subprocess.

- build_summary_prompt: assembles the Claude coach-summary prompt.
- parse_summary_response: validates Claude's JSON output.
- compute_distribution: counts positions + builds the timeline bar data.
"""
from __future__ import annotations

import json


class SummaryResponseError(Exception):
    """Raised when Claude's summary output fails schema or reference validation."""


CATEGORY_EMOJI: dict[str, str] = {
    "standing":          "⬜",
    "guard_bottom":      "🟦",
    "guard_top":         "🟨",
    "dominant_top":      "🟩",
    "inferior_bottom":   "🟥",
    "leg_entanglement":  "🟫",
    "scramble":          "🟪",
}


def compute_distribution(
    analyses: list[dict],
    categories: list[dict],
) -> dict:
    """Compute timeline + category counts + percentages from analyses.

    Only considers rows where `player == "a"` (the person being coached).
    `analyses` must be a flat list ordered chronologically with an already-joined
    `category` field per row. `categories` is the taxonomy's category list (unused
    for the computation itself, but accepted so callers can keep the data flow
    consistent with future extensions).
    """
    player_a_only = [a for a in analyses if a.get("player") == "a"]
    if not player_a_only:
        return {"timeline": [], "counts": {}, "percentages": {}}

    timeline: list[str] = [a["category"] for a in player_a_only]

    counts: dict[str, int] = {}
    for cat in timeline:
        counts[cat] = counts.get(cat, 0) + 1

    total = sum(counts.values())
    percentages: dict[str, int] = {
        cat: round((n / total) * 100) for cat, n in counts.items()
    }

    return {"timeline": timeline, "counts": counts, "percentages": percentages}
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_summarise.py -v
```

Expected: 6 passed (compute_distribution 5 + CATEGORY_EMOJI 1).

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/summarise.py tools/bjj-app/tests/backend/test_summarise.py
git commit -m "feat(bjj-app): add compute_distribution + CATEGORY_EMOJI in summarise.py"
```

---

## Task 4: Pure helper — `build_summary_prompt`

**Files:**
- Modify: `tools/bjj-app/tests/backend/test_summarise.py`
- Modify: `tools/bjj-app/server/analysis/summarise.py`

- [ ] **Step 1: Append failing tests**

Append to `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_summarise.py`:

```python


# ---------- build_summary_prompt ----------


def _roll(**overrides) -> dict:
    base = {
        "id": "roll-1",
        "title": "Sample",
        "date": "2026-04-21",
        "duration_s": 225.0,
        "player_a_name": "Alice",
        "player_b_name": "Bob",
    }
    base.update(overrides)
    return base


def _moment(mid: str, frame_idx: int, timestamp_s: float) -> dict:
    return {"id": mid, "frame_idx": frame_idx, "timestamp_s": timestamp_s}


def test_build_summary_prompt_includes_player_names():
    roll = _roll()
    prompt = build_summary_prompt(
        roll_row=roll,
        moment_rows=[],
        analyses_by_moment={},
        annotations_by_moment={},
    )
    assert "Alice" in prompt
    assert "Bob" in prompt
    # Doesn't leak hardcoded Greig/Anthony
    assert "Greig" not in prompt
    assert "Anthony" not in prompt


def test_build_summary_prompt_lists_analysed_moments_chronologically():
    moments = [_moment("m1", 3, 3.0), _moment("m2", 12, 12.0)]
    analyses = {
        "m1": [
            {"player": "a", "position_id": "closed_guard_bottom", "confidence": 0.8,
             "description": "Greig in guard", "coach_tip": "Break posture"},
            {"player": "b", "position_id": "closed_guard_top", "confidence": 0.75,
             "description": None, "coach_tip": None},
        ],
        "m2": [
            {"player": "a", "position_id": "half_guard_bottom", "confidence": 0.7,
             "description": "Slipped to half", "coach_tip": "Underhook"},
            {"player": "b", "position_id": "half_guard_top", "confidence": 0.68,
             "description": None, "coach_tip": None},
        ],
    }
    prompt = build_summary_prompt(
        roll_row=_roll(),
        moment_rows=moments,
        analyses_by_moment=analyses,
        annotations_by_moment={},
    )
    m1_idx = prompt.find("moment_id=m1")
    m2_idx = prompt.find("moment_id=m2")
    assert m1_idx != -1 and m2_idx != -1
    assert m1_idx < m2_idx  # chronological
    assert "closed_guard_bottom" in prompt
    assert "Break posture" in prompt
    assert "Underhook" in prompt


def test_build_summary_prompt_omits_annotations_block_when_no_annotations():
    moments = [_moment("m1", 3, 3.0)]
    analyses = {
        "m1": [
            {"player": "a", "position_id": "standing_neutral", "confidence": 0.9,
             "description": "Standing", "coach_tip": "Engage"},
            {"player": "b", "position_id": "standing_neutral", "confidence": 0.88,
             "description": None, "coach_tip": None},
        ],
    }
    prompt = build_summary_prompt(
        roll_row=_roll(),
        moment_rows=moments,
        analyses_by_moment=analyses,
        annotations_by_moment={"m1": []},
    )
    assert "User's own notes" not in prompt


def test_build_summary_prompt_includes_annotations_when_present():
    moments = [_moment("m1", 3, 3.0)]
    analyses = {
        "m1": [
            {"player": "a", "position_id": "standing_neutral", "confidence": 0.9,
             "description": "Standing", "coach_tip": "Engage"},
            {"player": "b", "position_id": "standing_neutral", "confidence": 0.88,
             "description": None, "coach_tip": None},
        ],
    }
    annotations = {
        "m1": [
            {"id": "a1", "body": "I was too passive here", "created_at": 1},
            {"id": "a2", "body": "could have shot a single", "created_at": 2},
        ],
    }
    prompt = build_summary_prompt(
        roll_row=_roll(),
        moment_rows=moments,
        analyses_by_moment=analyses,
        annotations_by_moment=annotations,
    )
    assert "User's own notes" in prompt
    assert "too passive" in prompt
    assert "shot a single" in prompt


def test_build_summary_prompt_includes_output_json_schema_keys():
    prompt = build_summary_prompt(
        roll_row=_roll(),
        moment_rows=[],
        analyses_by_moment={},
        annotations_by_moment={},
    )
    for key in (
        "summary", "scores", "guard_retention", "positional_awareness",
        "transition_quality", "top_improvements", "strengths", "key_moments",
        "moment_id",
    ):
        assert key in prompt
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_summarise.py -v
```

Expected: 5 new tests fail (ImportError on `build_summary_prompt`).

- [ ] **Step 3: Implement `build_summary_prompt`**

Append to `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/analysis/summarise.py`:

```python


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
    '    {"moment_id": "<from the list above>", "note": "<brief pointer sentence>"},\n'
    '    {"moment_id": "<...>", "note": "<...>"},\n'
    '    {"moment_id": "<...>", "note": "<...>"}\n'
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
    moment_rows: list[dict],
    analyses_by_moment: dict[str, list[dict]],
    annotations_by_moment: dict[str, list[dict]],
) -> str:
    """Construct the summary prompt for Claude.

    `roll_row` must have: player_a_name, player_b_name, duration_s, date.
    `moment_rows` sorted by timestamp_s ascending (caller's responsibility).
    `analyses_by_moment[moment_id]` lists analyses rows with keys
        player, position_id, confidence, description, coach_tip.
    `annotations_by_moment[moment_id]` lists annotation rows with keys
        id, body, created_at. Missing or empty lists are fine.
    """
    a_name = roll_row["player_a_name"]
    b_name = roll_row["player_b_name"]
    duration_s = roll_row.get("duration_s") or 0.0
    date = roll_row.get("date", "")

    preamble = (
        f"You are a BJJ coach reviewing a roll. Analyse the sequence below and produce "
        f"a concise coaching report. The practitioner is {a_name} (the person being coached); "
        f"{b_name} is their partner."
    )
    meta = (
        f"Roll metadata:\n"
        f"- Duration: {_format_mm_ss(duration_s)}\n"
        f"- Date: {date}\n"
        f"- Total moments analysed: {sum(1 for m in moment_rows if analyses_by_moment.get(m['id']))}"
    )

    moment_lines: list[str] = []
    for m in moment_rows:
        rows = analyses_by_moment.get(m["id"], [])
        if not rows:
            continue
        a_row = next((r for r in rows if r["player"] == "a"), None)
        b_row = next((r for r in rows if r["player"] == "b"), None)
        if a_row is None or b_row is None:
            continue
        mm_ss = _format_mm_ss(m["timestamp_s"])
        a_conf = int(round((a_row.get("confidence") or 0.0) * 100))
        description = (a_row.get("description") or "").strip()
        coach_tip = (a_row.get("coach_tip") or "").strip()
        moment_lines.append(
            f"- {mm_ss} moment_id={m['id']} — "
            f"{a_name}: {a_row['position_id']} ({a_conf}%); "
            f"{b_name}: {b_row['position_id']}."
            + (f"\n  {description}" if description else "")
            + (f"\n  Coach tip: {coach_tip}" if coach_tip else "")
        )

    moments_block = "Per-moment analyses (chronological):\n" + "\n".join(moment_lines) if moment_lines else \
        "Per-moment analyses (chronological):\n(no moments analysed)"

    annotation_lines: list[str] = []
    for m in moment_rows:
        for ann in annotations_by_moment.get(m["id"], []):
            mm_ss = _format_mm_ss(m["timestamp_s"])
            body = ann["body"].replace("\n", " ").strip()
            annotation_lines.append(f"- {mm_ss} moment_id={m['id']}: \"{body}\"")

    if annotation_lines:
        annotations_block = "User's own notes on specific moments:\n" + "\n".join(annotation_lines)
    else:
        annotations_block = ""

    parts = [preamble, meta, moments_block]
    if annotations_block:
        parts.append(annotations_block)
    parts.append(_OUTPUT_SCHEMA_HINT)

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_summarise.py -v
```

Expected: 11 passed (6 from Task 3 + 5 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/summarise.py tools/bjj-app/tests/backend/test_summarise.py
git commit -m "feat(bjj-app): add build_summary_prompt (parametric by player names + annotations)"
```

---

## Task 5: Pure helper — `parse_summary_response`

**Files:**
- Modify: `tools/bjj-app/tests/backend/test_summarise.py`
- Modify: `tools/bjj-app/server/analysis/summarise.py`

- [ ] **Step 1: Append failing tests**

Append to `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_summarise.py`:

```python


# ---------- parse_summary_response ----------


def _valid_payload() -> dict:
    return {
        "summary": "A good roll.",
        "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["a", "b", "c"],
        "strengths": ["x", "y"],
        "key_moments": [
            {"moment_id": "m1", "note": "first"},
            {"moment_id": "m2", "note": "second"},
            {"moment_id": "m3", "note": "third"},
        ],
    }


_VALID_IDS = {"m1", "m2", "m3", "m4"}


def test_parse_summary_response_accepts_valid_payload():
    raw = json.dumps(_valid_payload())
    out = parse_summary_response(raw, _VALID_IDS)
    assert out["summary"] == "A good roll."
    assert out["scores"]["guard_retention"] == 8


def test_parse_summary_response_rejects_non_json():
    with pytest.raises(SummaryResponseError):
        parse_summary_response("not json", _VALID_IDS)


def test_parse_summary_response_rejects_missing_top_level_keys():
    payload = _valid_payload()
    del payload["scores"]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_clamps_out_of_range_scores():
    payload = _valid_payload()
    payload["scores"] = {"guard_retention": 42, "positional_awareness": -3, "transition_quality": 7}
    out = parse_summary_response(json.dumps(payload), _VALID_IDS)
    assert out["scores"]["guard_retention"] == 10
    assert out["scores"]["positional_awareness"] == 0
    assert out["scores"]["transition_quality"] == 7


def test_parse_summary_response_rejects_key_moments_length_not_3():
    payload = _valid_payload()
    payload["key_moments"] = payload["key_moments"][:2]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_rejects_hallucinated_moment_id():
    payload = _valid_payload()
    payload["key_moments"][0]["moment_id"] = "not-a-real-id"
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_rejects_duplicate_moment_ids():
    payload = _valid_payload()
    payload["key_moments"][1]["moment_id"] = payload["key_moments"][0]["moment_id"]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_rejects_top_improvements_length_not_3():
    payload = _valid_payload()
    payload["top_improvements"] = ["a", "b"]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_requires_strengths_non_empty():
    payload = _valid_payload()
    payload["strengths"] = []
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_summarise.py -v
```

Expected: 9 new tests fail.

- [ ] **Step 3: Implement `parse_summary_response`**

Append to `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/analysis/summarise.py`:

```python


_REQUIRED_SCORES = ("guard_retention", "positional_awareness", "transition_quality")


def _clamp_score(value) -> int:
    """Coerce score to int in [0, 10]; raise if not a number."""
    if not isinstance(value, (int, float)):
        raise SummaryResponseError(f"score is not a number: {value!r}")
    return max(0, min(10, int(round(value))))


def parse_summary_response(raw: str, valid_moment_ids: set[str]) -> dict:
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

    # summary
    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise SummaryResponseError("summary must be a non-empty string")

    # scores
    scores = data["scores"]
    if not isinstance(scores, dict):
        raise SummaryResponseError("scores must be an object")
    for metric in _REQUIRED_SCORES:
        if metric not in scores:
            raise SummaryResponseError(f"missing score metric: {metric}")
    data["scores"] = {m: _clamp_score(scores[m]) for m in _REQUIRED_SCORES}

    # top_improvements — exactly 3 non-empty strings
    ti = data["top_improvements"]
    if not isinstance(ti, list) or len(ti) != 3:
        raise SummaryResponseError("top_improvements must be a list of exactly 3 items")
    for item in ti:
        if not isinstance(item, str) or not item.strip():
            raise SummaryResponseError("each top_improvements item must be a non-empty string")

    # strengths — 1..N non-empty strings, require at least one
    st = data["strengths"]
    if not isinstance(st, list) or len(st) == 0:
        raise SummaryResponseError("strengths must be a non-empty list")
    for item in st:
        if not isinstance(item, str) or not item.strip():
            raise SummaryResponseError("each strengths item must be a non-empty string")

    # key_moments — exactly 3 items, unique moment_ids, all in valid set
    km = data["key_moments"]
    if not isinstance(km, list) or len(km) != 3:
        raise SummaryResponseError("key_moments must be a list of exactly 3 items")
    seen: set[str] = set()
    for entry in km:
        if not isinstance(entry, dict):
            raise SummaryResponseError("each key_moments entry must be an object")
        mid = entry.get("moment_id")
        note = entry.get("note")
        if not isinstance(mid, str) or not mid:
            raise SummaryResponseError("key_moments[*].moment_id must be a non-empty string")
        if mid in seen:
            raise SummaryResponseError(f"duplicate key_moments moment_id: {mid}")
        if mid not in valid_moment_ids:
            raise SummaryResponseError(f"key_moments references unknown moment_id: {mid}")
        if not isinstance(note, str) or not note.strip():
            raise SummaryResponseError("key_moments[*].note must be a non-empty string")
        seen.add(mid)

    return data
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_summarise.py -v
```

Expected: 20 passed (11 prior + 9 new).

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/summarise.py tools/bjj-app/tests/backend/test_summarise.py
git commit -m "feat(bjj-app): add parse_summary_response with validation + score clamping"
```

---

## Task 6: Refactor — extract `run_claude` from `claude_cli.py`

**Files:**
- Modify: `tools/bjj-app/server/analysis/claude_cli.py`

No new tests — the existing `analyse_frame` tests gate this refactor; if they all pass the extraction preserved behaviour.

- [ ] **Step 1: Refactor `analyse_frame` to call new `run_claude`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/analysis/claude_cli.py`.

Find the `_run_once` function definition. It's currently called from the retry loop inside `analyse_frame`. We're creating a new `run_claude` that owns the rate-limit, the retry loop, and the subprocess call; `analyse_frame` will call it instead of calling `_run_once` directly.

Add a new `run_claude` function between the existing `RateLimitedError`/`ClaudeProcessError` exception classes and `analyse_frame`. Place it just above `analyse_frame`:

```python
async def run_claude(
    prompt: str,
    *,
    settings: Settings,
    limiter: SlidingWindowLimiter,
    stream_callback: StreamCallback | None = None,
) -> str:
    """Spawn claude -p with the given prompt, return raw assistant text.

    Owns: rate-limit acquisition, subprocess spawn, stream-json stdout parsing,
    one retry on non-zero exit with 2s backoff.
    Does NOT own: prompt construction, caching, response schema validation.
    Callers layer those on top.

    Raises:
      RateLimitedError  — limiter rejected the call; caller surfaces 429.
      ClaudeProcessError — subprocess failed after retry.
    """
    wait = limiter.try_acquire()
    if wait is not None:
        raise RateLimitedError(retry_after_s=wait)

    assistant_text: str | None = None
    last_exit: int | None = None
    cb: StreamCallback = stream_callback if stream_callback is not None else _noop_stream_callback
    for attempt in range(2):
        assistant_text, last_exit = await _run_once(
            settings=settings, prompt=prompt, stream_callback=cb
        )
        if last_exit == 0 and assistant_text is not None:
            break
        if attempt == 0:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)

    if last_exit != 0:
        raise ClaudeProcessError(f"claude exited {last_exit}")

    assert assistant_text is not None
    return assistant_text


async def _noop_stream_callback(evt: dict) -> None:
    """Default stream callback — discards stream events."""
    return None
```

Now update `analyse_frame` to delegate to `run_claude`. Find the section in `analyse_frame` that looks like:

```python
    # --- Rate limit (check BEFORE spawning, count toward the window) ---
    wait = limiter.try_acquire()
    if wait is not None:
        raise RateLimitedError(retry_after_s=wait)

    # --- Spawn with one retry on non-zero exit ---
    assistant_text: str | None = None
    last_exit: int | None = None
    for attempt in range(2):
        assistant_text, last_exit = await _run_once(
            settings=settings, prompt=prompt, stream_callback=stream_callback
        )
        if last_exit == 0 and assistant_text is not None:
            break
        if attempt == 0:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)

    if last_exit != 0:
        raise ClaudeProcessError(f"claude exited {last_exit}")

    assert assistant_text is not None
```

Replace it with:

```python
    # --- Rate limit + spawn + retry — delegated to run_claude ---
    assistant_text = await run_claude(
        prompt,
        settings=settings,
        limiter=limiter,
        stream_callback=stream_callback,
    )
```

- [ ] **Step 2: Run all Claude CLI tests — must still pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_claude_cli.py -v
```

Expected: all existing analyse_frame tests pass unchanged.

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/claude_cli.py
git commit -m "refactor(bjj-app): extract run_claude from analyse_frame for summary reuse"
```

---

## Task 7: Vault writer — `render_summary_sections`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_vault_writer_summary.py`
- Modify: `tools/bjj-app/server/analysis/vault_writer.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_vault_writer_summary.py`:

```python
"""Tests for vault_writer's summary-section rendering + per-section splice."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.analysis.vault_writer import render_summary_sections


_FIXTURE_CATEGORIES = [
    {"id": "standing", "label": "Standing"},
    {"id": "guard_bottom", "label": "Guard (Bottom)"},
    {"id": "scramble", "label": "Scramble"},
]

_FIXTURE_SCORES = {
    "summary": "A strong roll with good guard retention.",
    "scores": {
        "guard_retention": 8,
        "positional_awareness": 6,
        "transition_quality": 7,
    },
    "top_improvements": [
        "Keep elbows tight when posture is broken.",
        "Frame earlier when the pass shot fires.",
        "Don't overcommit to hip-bump sweeps.",
    ],
    "strengths": ["Patient grips", "Strong closed guard"],
    "key_moments": [
        {"moment_id": "m1", "note": "Perfect triangle entry timing."},
        {"moment_id": "m2", "note": "Got swept here — posture broke first."},
        {"moment_id": "m3", "note": "Clean half-guard recovery."},
    ],
}

_FIXTURE_DISTRIBUTION = {
    "timeline": ["standing", "guard_bottom", "guard_bottom", "scramble"],
    "counts": {"standing": 1, "guard_bottom": 2, "scramble": 1},
    "percentages": {"standing": 25, "guard_bottom": 50, "scramble": 25},
}

_FIXTURE_MOMENTS = [
    {"id": "m1", "timestamp_s": 3.0},
    {"id": "m2", "timestamp_s": 45.0},
    {"id": "m3", "timestamp_s": 125.0},
]


def test_render_summary_sections_returns_all_six_keys():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES,
        moments=_FIXTURE_MOMENTS,
    )
    assert set(sections.keys()) == {
        "summary",
        "scores",
        "position_distribution",
        "key_moments",
        "top_improvements",
        "strengths",
    }


def test_render_summary_sections_summary_is_the_prose_sentence():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES,
        moments=_FIXTURE_MOMENTS,
    )
    assert sections["summary"].strip() == "A strong roll with good guard retention."


def test_render_summary_sections_scores_renders_as_table():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES,
        moments=_FIXTURE_MOMENTS,
    )
    body = sections["scores"]
    assert "| Metric" in body
    assert "| Guard Retention" in body
    assert "8/10" in body
    assert "6/10" in body
    assert "7/10" in body


def test_render_summary_sections_position_distribution_includes_counts_and_bar():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES,
        moments=_FIXTURE_MOMENTS,
    )
    body = sections["position_distribution"]
    assert "| Category" in body
    assert "Guard (Bottom)" in body
    assert "50%" in body
    assert "### Position Timeline Bar" in body
    # At least one emoji for each category appears in the bar
    assert "⬜" in body  # standing
    assert "🟦" in body  # guard_bottom
    assert "🟪" in body  # scramble
    assert "Legend:" in body


def test_render_summary_sections_key_moments_cite_timestamps():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES,
        moments=_FIXTURE_MOMENTS,
    )
    body = sections["key_moments"]
    assert "- **0:03**" in body
    assert "Perfect triangle entry timing." in body
    assert "- **0:45**" in body
    assert "posture broke first" in body
    assert "- **2:05**" in body


def test_render_summary_sections_top_improvements_is_numbered():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES,
        moments=_FIXTURE_MOMENTS,
    )
    body = sections["top_improvements"]
    assert "1. Keep elbows tight" in body
    assert "2. Frame earlier" in body
    assert "3. Don't overcommit" in body


def test_render_summary_sections_strengths_is_bulleted():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES,
        moments=_FIXTURE_MOMENTS,
    )
    body = sections["strengths"]
    assert "- Patient grips" in body
    assert "- Strong closed guard" in body
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_vault_writer_summary.py -v
```

Expected: 7 tests fail (ImportError on `render_summary_sections`).

- [ ] **Step 3: Implement `render_summary_sections`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/analysis/vault_writer.py`.

Add the import at the top (near other imports):
```python
from server.analysis.summarise import CATEGORY_EMOJI
```

Append the new function at the bottom of `vault_writer.py`:

```python


# ---------- M6a: summary section rendering ----------


_SCORE_METRIC_LABELS: list[tuple[str, str]] = [
    ("guard_retention", "Guard Retention"),
    ("positional_awareness", "Positional Awareness"),
    ("transition_quality", "Transition Quality"),
]


def render_summary_sections(
    scores_payload: dict,
    distribution: dict,
    categories: list[dict],
    moments: list[dict],
) -> dict[str, str]:
    """Render the six summary-owned section bodies.

    Returns `{section_id: body_markdown}` where section_id is one of:
      summary, scores, position_distribution, key_moments, top_improvements, strengths.
    Body strings do NOT include the `## <heading>` line — the caller emits that
    and the splicer walks by heading.

    `moments` is the full moment list for the roll (needed to resolve
    key_moments[*].moment_id → timestamp_s for display).
    """
    moments_by_id = {m["id"]: m for m in moments}
    category_label_by_id = {c["id"]: c["label"] for c in categories}

    # --- Summary ---
    summary = scores_payload["summary"].strip()

    # --- Scores ---
    scores = scores_payload["scores"]
    score_rows = [
        "| Metric                 | Score |",
        "|------------------------|-------|",
    ] + [
        f"| {label:<22} | {scores[metric]}/10  |"
        for metric, label in _SCORE_METRIC_LABELS
    ]
    scores_body = "\n".join(score_rows)

    # --- Position Distribution ---
    dist_rows = ["| Category        | Count | %   |", "|-----------------|-------|-----|"]
    for cat_id in sorted(distribution["counts"].keys()):
        label = category_label_by_id.get(cat_id, cat_id)
        count = distribution["counts"][cat_id]
        pct = distribution["percentages"][cat_id]
        dist_rows.append(f"| {label:<15} | {count:<5} | {pct}% |")
    timeline_bar = "".join(
        CATEGORY_EMOJI.get(cat, "⬛") for cat in distribution["timeline"]
    )
    legend = "Legend: " + " ".join(
        f"{CATEGORY_EMOJI[cat]}{cat}" for cat in CATEGORY_EMOJI.keys()
    )
    position_distribution_body = (
        "\n".join(dist_rows)
        + "\n\n### Position Timeline Bar\n\n"
        + (timeline_bar if timeline_bar else "(no analyses)")
        + "\n\n"
        + legend
    )

    # --- Key Moments ---
    km_lines: list[str] = []
    for km in scores_payload["key_moments"]:
        m = moments_by_id.get(km["moment_id"])
        mm_ss = _format_mm_ss(m["timestamp_s"]) if m is not None else "?:??"
        km_lines.append(f"- **{mm_ss}** — {km['note']}")
    key_moments_body = "\n".join(km_lines)

    # --- Top Improvements ---
    ti_lines = [f"{i + 1}. {item}" for i, item in enumerate(scores_payload["top_improvements"])]
    top_improvements_body = "\n".join(ti_lines)

    # --- Strengths ---
    st_lines = [f"- {item}" for item in scores_payload["strengths"]]
    strengths_body = "\n".join(st_lines)

    return {
        "summary": summary,
        "scores": scores_body,
        "position_distribution": position_distribution_body,
        "key_moments": key_moments_body,
        "top_improvements": top_improvements_body,
        "strengths": strengths_body,
    }
```

Reuse the existing `_format_mm_ss` helper in `vault_writer.py` (already present from M4 `render_your_notes`).

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_vault_writer_summary.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/vault_writer.py tools/bjj-app/tests/backend/test_vault_writer_summary.py
git commit -m "feat(bjj-app): add render_summary_sections for M6a vault emission"
```

---

## Task 8: Extend `vault_writer.publish` for per-section splice + hashing

**Files:**
- Modify: `tools/bjj-app/server/analysis/vault_writer.py`
- Modify: `tools/bjj-app/tests/backend/test_vault_writer_summary.py`

This task generalises the existing `_splice_your_notes` / single-hash flow to walk a list of section descriptors. After this task, `publish` emits Your Notes AND (if finalised) all six summary sections, with per-section hash checks.

- [ ] **Step 1: Append failing tests for the extended publish**

Append to `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_vault_writer_summary.py`:

```python


# ---------- publish() extended with summary sections ----------


import json  # noqa: E402
import time  # noqa: E402

from server.analysis.vault_writer import ConflictError, publish  # noqa: E402
from server.db import (  # noqa: E402
    connect,
    create_roll,
    init_db,
    insert_annotation,
    insert_moments,
    set_summary_state,
)


@pytest.fixture
def db_finalised_roll(tmp_path: Path):
    """A roll with: 3 moments, annotations, and set_summary_state already called."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn, id="r-1", title="Sample Roll", date="2026-04-21",
        video_path="assets/r-1/source.mp4", duration_s=225.0, partner="Anthony",
        result="unknown", created_at=1700000000,
    )
    moments = insert_moments(
        conn, roll_id="r-1",
        moments=[
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 45, "timestamp_s": 45.0, "pose_delta": 0.9},
            {"frame_idx": 125, "timestamp_s": 125.0, "pose_delta": 1.0},
        ],
    )
    insert_annotation(conn, moment_id=moments[0]["id"], body="first note", created_at=1700000100)

    scores_payload = {
        "summary": "A strong roll with good guard retention.",
        "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["imp one", "imp two", "imp three"],
        "strengths": ["st one", "st two"],
        "key_moments": [
            {"moment_id": moments[0]["id"], "note": "Perfect entry"},
            {"moment_id": moments[1]["id"], "note": "Where the sweep reversed"},
            {"moment_id": moments[2]["id"], "note": "Clean recovery"},
        ],
    }
    set_summary_state(
        conn, roll_id="r-1", scores_payload=scores_payload, finalised_at=1700000500,
    )
    # Provide a taxonomy to the publish() call path.
    taxonomy = {
        "categories": [
            {"id": "standing", "label": "Standing"},
            {"id": "guard_bottom", "label": "Guard (Bottom)"},
            {"id": "scramble", "label": "Scramble"},
        ],
        "positions": [],
        "transitions": [],
    }
    try:
        yield conn, tmp_path, taxonomy
    finally:
        conn.close()


def test_publish_finalised_roll_emits_all_summary_sections(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    result = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    text = (vault_root / result.vault_path).read_text()
    # All six summary section headings
    assert "## Summary" in text
    assert "## Scores" in text
    assert "## Position Distribution" in text
    assert "## Key Moments" in text
    assert "## Top Improvements" in text
    assert "## Strengths Observed" in text
    # And Your Notes still present
    assert "## Your Notes" in text
    # Section ordering: all summary sections before Your Notes.
    your_notes_idx = text.index("## Your Notes")
    for section in (
        "## Summary",
        "## Scores",
        "## Position Distribution",
        "## Key Moments",
        "## Top Improvements",
        "## Strengths Observed",
    ):
        assert text.index(section) < your_notes_idx


def test_publish_unfinalised_roll_has_your_notes_only(db_finalised_roll):
    """Regression: a non-finalised roll should only emit Your Notes (M4 behaviour)."""
    conn, vault_root, taxonomy = db_finalised_roll
    # Un-finalise by clearing scores_json and finalised_at.
    conn.execute("UPDATE rolls SET scores_json = NULL, finalised_at = NULL WHERE id = 'r-1'")
    conn.commit()

    result = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    text = (vault_root / result.vault_path).read_text()
    assert "## Your Notes" in text
    assert "## Summary" not in text
    assert "## Scores" not in text


def test_publish_second_time_splices_owned_sections_preserves_user_sections(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    full = vault_root / first.vault_path

    # User appends a completely unrelated section in Obsidian.
    existing = full.read_text()
    existing += "\n## Extra thoughts\n\nSomething personal.\n"
    full.write_text(existing)

    # Re-publish (no changes to SQLite yet) — should keep user section intact.
    publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy, force=True)
    text_after = full.read_text()
    assert "## Extra thoughts" in text_after
    assert "Something personal." in text_after


def test_publish_raises_conflict_when_summary_section_edited_externally(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    full = vault_root / first.vault_path

    # User hand-edits the Summary section in Obsidian.
    text = full.read_text()
    text = text.replace(
        "A strong roll with good guard retention.",
        "EDITED IN OBSIDIAN — a strong roll.",
    )
    full.write_text(text)

    with pytest.raises(ConflictError):
        publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)


def test_publish_force_overrides_summary_section_conflict(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    full = vault_root / first.vault_path

    text = full.read_text()
    text = text.replace("A strong roll", "EDITED IN OBSIDIAN — a strong roll")
    full.write_text(text)

    # With force=True, no raise.
    result = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy, force=True)
    text_after = (vault_root / result.vault_path).read_text()
    assert "EDITED IN OBSIDIAN" not in text_after
    assert "A strong roll with good guard retention." in text_after


def test_publish_conflict_does_not_fire_on_unrelated_section_edit(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    full = vault_root / first.vault_path

    # User edits an UNRELATED section (## Extra thoughts) — not owned by the app.
    text = full.read_text()
    text += "\n## Extra thoughts\n\nUser added this, not owned.\n"
    full.write_text(text)

    # No conflict — the summary-owned sections are still unchanged.
    publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_vault_writer_summary.py -v
```

Expected: 6 new tests fail with errors about `publish` not accepting `taxonomy` kwarg, or summary sections missing from output.

- [ ] **Step 3: Extend `vault_writer.publish`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/analysis/vault_writer.py`.

Extend the existing imports near the top to include `set_vault_summary_hashes`:

```python
from server.db import (
    get_annotations_by_roll,
    get_roll,
    get_vault_state,
    set_vault_state,
    set_vault_summary_hashes,
)
```

Also import `get_analyses` and `get_moments` (needed to compute distribution):

```python
from server.db import (
    get_analyses,
    get_annotations_by_roll,
    get_moments,
    get_roll,
    get_vault_state,
    set_vault_state,
    set_vault_summary_hashes,
)
```

Add the `compute_distribution` import:
```python
from server.analysis.summarise import CATEGORY_EMOJI, compute_distribution
```

(CATEGORY_EMOJI may already be imported from Task 7; verify you don't double-import.)

Add section-descriptor constant + helpers near the top (after the existing `_YOUR_NOTES_HEADING` constant):

```python
# Ordered list of summary-owned sections — determines vault markdown order.
_SUMMARY_SECTION_ORDER: list[tuple[str, str]] = [
    ("summary", "## Summary"),
    ("scores", "## Scores"),
    ("position_distribution", "## Position Distribution"),
    ("key_moments", "## Key Moments"),
    ("top_improvements", "## Top Improvements"),
    ("strengths", "## Strengths Observed"),
]


def _heading_regex(heading: str) -> _re.Pattern:
    """Build a line-anchored regex for a given '## Section Name' heading."""
    escaped = _re.escape(heading)
    return _re.compile(rf"^{escaped}\s*$", _re.MULTILINE)


def _extract_section_by_heading(text: str, heading: str) -> str:
    """Return the body (stripped) of the section with the given heading.

    Empty string if heading not found. Section body spans from the line
    after the heading to the next `^## ` heading (exclusive) or EOF.
    """
    m = _heading_regex(heading).search(text)
    if m is None:
        return ""
    body_start = text.find("\n", m.end())
    if body_start == -1:
        return ""
    body_start += 1
    rest = text[body_start:]
    next_m = _SECTION_BOUNDARY.search(rest)
    end = body_start + next_m.start() if next_m else len(text)
    return text[body_start:end].strip()


def _splice_section_by_heading(current_text: str, heading: str, new_body: str) -> str:
    """Replace the body of a section with matching heading; if heading absent,
    append the section at the end."""
    m = _heading_regex(heading).search(current_text)
    if m is None:
        separator = "" if current_text.endswith("\n\n") else (
            "\n" if current_text.endswith("\n") else "\n\n"
        )
        return f"{current_text}{separator}{heading}\n\n{new_body}\n"

    body_start = current_text.find("\n", m.end())
    if body_start == -1:
        body_start = len(current_text)
    else:
        body_start += 1
    rest = current_text[body_start:]
    next_m = _SECTION_BOUNDARY.search(rest)
    end = body_start + next_m.start() if next_m else len(current_text)
    before = current_text[: m.end()]
    after = current_text[end:]
    if after and not after.startswith("\n"):
        after = "\n" + after
    if not after:
        after = "\n"
    return f"{before}\n\n{new_body}\n{after}"
```

Replace the existing `publish` function with a generalised version that handles all owned sections. Find the entire `def publish(...)` function and replace with:

```python
def publish(
    conn,
    *,
    roll_id: str,
    vault_root: Path,
    force: bool = False,
    taxonomy: dict | None = None,
) -> PublishResult:
    """Publish a roll's annotations + (if finalised) summary sections to the vault markdown.

    - First publish: creates a new file under Roll Log/ with frontmatter + title +
      all owned sections in order, then Your Notes.
    - Re-publish: surgically replaces each owned section body, preserving everything
      outside those sections. Per-section hash check fires `ConflictError` on any
      externally-edited owned section unless `force=True`.
    - Unfinalised rolls (no scores_json) emit only Your Notes, matching M4 behaviour.

    `taxonomy` is required when the roll is finalised (needed for distribution labels).
    Passing `None` is acceptable only for unfinalised rolls.
    """
    roll_row = get_roll(conn, roll_id)
    if roll_row is None:
        raise LookupError(f"Roll not found: {roll_id}")

    # ---------- Render the authoritative section bodies ----------
    annotations = get_annotations_by_roll(conn, roll_id)
    your_notes_body = render_your_notes(annotations)
    your_notes_hash = _hash_section(your_notes_body)

    is_finalised = roll_row["scores_json"] is not None and roll_row["finalised_at"] is not None
    summary_section_bodies: dict[str, str] = {}
    summary_hashes: dict[str, str] = {}

    if is_finalised:
        if taxonomy is None:
            raise ValueError("publish() requires `taxonomy` for finalised rolls")
        import json as _json
        scores_payload = _json.loads(roll_row["scores_json"])
        # Build analyses list with category joined — needed by compute_distribution.
        moment_rows = get_moments(conn, roll_id)
        flat_analyses: list[dict] = []
        position_to_category = {p["id"]: p["category"] for p in taxonomy.get("positions", [])}
        for m in moment_rows:
            for a in get_analyses(conn, m["id"]):
                flat_analyses.append({
                    "position_id": a["position_id"],
                    "player": a["player"],
                    "timestamp_s": m["timestamp_s"],
                    "category": position_to_category.get(a["position_id"], "scramble"),
                })
        distribution = compute_distribution(flat_analyses, taxonomy.get("categories", []))
        summary_section_bodies = render_summary_sections(
            scores_payload=scores_payload,
            distribution=distribution,
            categories=taxonomy.get("categories", []),
            moments=[{"id": m["id"], "timestamp_s": m["timestamp_s"]} for m in moment_rows],
        )
        summary_hashes = {k: _hash_section(v) for k, v in summary_section_bodies.items()}

    # ---------- Determine target path ----------
    vault_state = get_vault_state(conn, roll_id) or {
        "vault_path": None, "vault_your_notes_hash": None, "vault_published_at": None,
    }
    if vault_state["vault_path"]:
        target = vault_root / vault_state["vault_path"]
    else:
        target = slugify_filename(
            title=roll_row["title"],
            date=roll_row["date"],
            vault_root=vault_root,
        )
    _assert_under_roll_log(target, vault_root)

    stored_summary_hashes: dict[str, str] = {}
    if roll_row["vault_summary_hashes"]:
        import json as _json
        stored_summary_hashes = _json.loads(roll_row["vault_summary_hashes"]) or {}

    # ---------- Decide: fresh skeleton vs splice ----------
    if target.exists():
        current_text = target.read_text(encoding="utf-8")

        # Your Notes conflict check
        current_your_notes = _extract_your_notes_section(current_text)
        current_your_notes_hash = _hash_section(current_your_notes)
        if (
            vault_state["vault_your_notes_hash"] is not None
            and current_your_notes_hash != vault_state["vault_your_notes_hash"]
            and not force
        ):
            raise ConflictError(
                current_hash=current_your_notes_hash,
                stored_hash=vault_state["vault_your_notes_hash"],
            )

        # Per-summary-section conflict check (only if we've previously stored hashes).
        if is_finalised and stored_summary_hashes:
            for section_id, heading in _SUMMARY_SECTION_ORDER:
                current_body = _extract_section_by_heading(current_text, heading)
                current_hash = _hash_section(current_body)
                stored_hash = stored_summary_hashes.get(section_id)
                if (
                    stored_hash is not None
                    and current_hash != stored_hash
                    and not force
                ):
                    raise ConflictError(current_hash=current_hash, stored_hash=stored_hash)

        # Splice all owned sections.
        new_text = current_text
        if is_finalised:
            for section_id, heading in _SUMMARY_SECTION_ORDER:
                new_text = _splice_section_by_heading(
                    new_text, heading, summary_section_bodies[section_id]
                )
        new_text = _splice_your_notes(new_text, your_notes_body)
    else:
        # Fresh skeleton.
        new_text = _build_skeleton(
            title=roll_row["title"],
            date=roll_row["date"],
            partner=roll_row["partner"],
            duration_s=roll_row["duration_s"],
            roll_id=roll_id,
            your_notes_body=your_notes_body,
            summary_sections=summary_section_bodies if is_finalised else None,
        )

    _atomic_write(target, new_text)

    now = int(time.time())
    relative_path = str(target.relative_to(vault_root))
    set_vault_state(
        conn,
        roll_id=roll_id,
        vault_path=relative_path,
        vault_your_notes_hash=your_notes_hash,
        vault_published_at=now,
    )
    set_vault_summary_hashes(
        conn,
        roll_id=roll_id,
        hashes=summary_hashes if is_finalised else None,
    )
    return PublishResult(
        vault_path=relative_path,
        your_notes_hash=your_notes_hash,
        vault_published_at=now,
    )
```

Also update `_build_skeleton` to accept summary sections:

```python
def _build_skeleton(
    *,
    title: str,
    date: str,
    partner: str | None,
    duration_s: float | None,
    roll_id: str,
    your_notes_body: str,
    summary_sections: dict[str, str] | None = None,
) -> str:
    duration = _format_duration(duration_s)
    partner_line = f"partner: {_yaml_quote(partner)}" if partner else "partner:"
    duration_line = f"duration: {_yaml_quote(duration)}" if duration else "duration:"

    frontmatter = "\n".join([
        "---",
        f"date: {_yaml_quote(date)}",
        partner_line,
        duration_line,
        "tags: [roll]",
        f"roll_id: {_yaml_quote(roll_id)}",
        "---",
    ])

    parts = [f"{frontmatter}\n\n# {title}"]
    if summary_sections:
        for section_id, heading in _SUMMARY_SECTION_ORDER:
            parts.append(f"{heading}\n\n{summary_sections[section_id]}")
    parts.append(f"{_YOUR_NOTES_HEADING}\n\n{your_notes_body}")
    return "\n\n".join(parts) + "\n"
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_vault_writer_summary.py -v
```

Expected: 13 passed (7 render + 6 publish).

Also run existing vault_writer tests to ensure no regressions:
```bash
pytest tests/backend/test_vault_writer.py -v
```

Expected: all M4 tests still pass. The generalised splice must not break the M4 behaviour.

Full suite sanity:
```bash
pytest tests/backend -v
```

Note: `test_vault_writer.py` has existing tests that call `publish(conn, roll_id=..., vault_root=..., force=...)` without a `taxonomy` arg. Those rolls are NOT finalised so the new `taxonomy=None` default works fine. Verify no regressions.

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/vault_writer.py tools/bjj-app/tests/backend/test_vault_writer_summary.py
git commit -m "feat(bjj-app): extend vault_writer.publish with per-section splice + hashing for M6a"
```

---

## Task 9: Extend `api/publish.py` to pass taxonomy

**Files:**
- Modify: `tools/bjj-app/server/api/publish.py`
- Modify: `tools/bjj-app/tests/backend/test_api_publish.py`

- [ ] **Step 1: Update `api/publish.py` to load + pass taxonomy**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/api/publish.py`.

Find the `publish_roll` function. It currently calls `vault_publish(conn, roll_id=..., vault_root=..., force=...)`. Update to pass `taxonomy` from `request.app.state.taxonomy`:

```python
@router.post(
    "/rolls/{roll_id}/publish",
    response_model=_PublishOut,
)
def publish_roll(
    roll_id: str,
    payload: _PublishIn,
    request: Request,
    settings: Settings = Depends(load_settings),
):
    taxonomy = getattr(request.app.state, "taxonomy", None)
    conn = connect(settings.db_path)
    try:
        try:
            result = vault_publish(
                conn,
                roll_id=roll_id,
                vault_root=settings.vault_root,
                force=payload.force,
                taxonomy=taxonomy,
            )
        except LookupError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        except ConflictError as exc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "Your Notes or a summary section was edited in Obsidian since last publish",
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

Also import `Request` from FastAPI if not already imported:
```python
from fastapi import APIRouter, Depends, HTTPException, Request, status
```

- [ ] **Step 2: Add a regression test to `test_api_publish.py`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_api_publish.py` and append a new test that exercises publish on a finalised roll:

```python


@pytest.mark.asyncio
async def test_publish_finalised_roll_writes_summary_sections_to_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    """Integration: if a roll has scores_json + finalised_at set, publish emits
    all six summary sections in addition to Your Notes."""
    import json
    import time

    # Place a minimal taxonomy file.
    tax_dir = tmp_project_root / "tools"
    tax_dir.mkdir(exist_ok=True)
    (tax_dir / "taxonomy.json").write_text(json.dumps({
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing", "category": "standing", "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "CG Bottom", "category": "guard_bottom", "visual_cues": "b"},
        ],
        "valid_transitions": [],
    }))

    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moment_id = await _upload_annotate(client, short_video_path)

    # Directly set summary state on the DB to simulate a finalised roll.
    from server.db import connect, set_summary_state

    conn = connect(tmp_project_root / "test.db")
    try:
        scores_payload = {
            "summary": "Integration-test roll.",
            "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 8},
            "top_improvements": ["one", "two", "three"],
            "strengths": ["strong"],
            "key_moments": [
                {"moment_id": moment_id, "note": "first"},
                {"moment_id": moment_id, "note": "second"},
                {"moment_id": moment_id, "note": "third"},
            ],
        }
        # Test needs 3 distinct moment_ids for key_moments validation, so override manually.
        rows = conn.execute(
            "SELECT id FROM moments WHERE roll_id = ? ORDER BY timestamp_s", (roll_id,)
        ).fetchall()
        if len(rows) >= 3:
            scores_payload["key_moments"] = [
                {"moment_id": rows[0]["id"], "note": "first"},
                {"moment_id": rows[1]["id"], "note": "second"},
                {"moment_id": rows[2]["id"], "note": "third"},
            ]
        set_summary_state(
            conn, roll_id=roll_id, scores_payload=scores_payload, finalised_at=int(time.time()),
        )
    finally:
        conn.close()

    # Publish.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/publish", json={})

    assert response.status_code == 200
    vault_path = tmp_project_root / response.json()["vault_path"]
    text = vault_path.read_text()
    assert "## Summary" in text
    assert "Integration-test roll." in text
    assert "## Scores" in text
    assert "## Position Distribution" in text
    assert "## Key Moments" in text
    assert "## Top Improvements" in text
    assert "## Strengths Observed" in text
    assert "## Your Notes" in text
```

Note: the existing `_upload_annotate` test helper should give us ≥3 moments if the fixture video has sufficient pose deltas. If it only produces fewer moments, use a different short_video fixture or relax the assertion. Adjust the `scores_payload`'s `key_moments` to reference real moment ids as shown.

- [ ] **Step 3: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_api_publish.py -v
```

Expected: all passing (existing M4 tests + new finalised-publish test).

If the new test fails because the fixture produces fewer than 3 moments, the subagent should inspect the fixture's moment count, and either (a) adjust `scores_payload["key_moments"]` to tolerate moment deduplication by picking unique combos of the available moments, or (b) use a shorter timestamp window. Do not skip the test — it's guarding a real integration behaviour.

Full suite:
```bash
pytest tests/backend -v
```

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/publish.py tools/bjj-app/tests/backend/test_api_publish.py
git commit -m "feat(bjj-app): extend publish endpoint to emit summary sections when finalised"
```

---

## Task 10: Summarise API — failing tests

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_summarise.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_api_summarise.py`:

```python
"""Tests for POST /api/rolls/:id/summarise."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _minimal_taxonomy(root: Path) -> None:
    tax_dir = root / "tools"
    tax_dir.mkdir(exist_ok=True)
    (tax_dir / "taxonomy.json").write_text(json.dumps({
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing", "category": "standing", "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "CG Bottom", "category": "guard_bottom", "visual_cues": "b"},
        ],
        "valid_transitions": [],
    }))


async def _upload_and_analyse_moments(
    client: AsyncClient, short_video_path: Path
) -> tuple[str, list[str]]:
    """Upload + pose pre-pass + seed Claude analyses on 3 moments.
    Returns (roll_id, list_of_moment_ids_analysed)."""
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Summarise fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]
    pre = await client.post(f"/api/rolls/{roll_id}/analyse")
    assert pre.status_code == 200
    return roll_id, []  # Subtests insert analyses directly via db.


def _seed_analyses(db_path: Path, roll_id: str, n_moments_to_analyse: int) -> list[str]:
    """Insert analyses on first N moments. Returns the analysed moment_ids."""
    from server.db import connect, insert_analyses

    conn = connect(db_path)
    try:
        moments = conn.execute(
            "SELECT id FROM moments WHERE roll_id = ? ORDER BY timestamp_s LIMIT ?",
            (roll_id, n_moments_to_analyse),
        ).fetchall()
        moment_ids: list[str] = []
        for m in moments:
            insert_analyses(
                conn, moment_id=m["id"],
                players=[
                    {"player": "a", "position_id": "closed_guard_bottom",
                     "confidence": 0.8, "description": "d", "coach_tip": "t"},
                    {"player": "b", "position_id": "closed_guard_bottom",
                     "confidence": 0.75, "description": None, "coach_tip": None},
                ],
                claude_version="test",
            )
            moment_ids.append(m["id"])
    finally:
        conn.close()
    return moment_ids


_VALID_SUMMARY_OUTPUT_TEMPLATE = {
    "summary": "Tight roll in closed guard.",
    "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
    "top_improvements": ["imp a", "imp b", "imp c"],
    "strengths": ["patient grips"],
    "key_moments": [],  # filled in per test
}


@pytest.mark.asyncio
async def test_summarise_happy_path_persists_and_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app
    import server.api.summarise as summarise_mod

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse_moments(client, short_video_path)

    moment_ids = _seed_analyses(tmp_project_root / "test.db", roll_id, 3)
    assert len(moment_ids) == 3

    fake_output = dict(_VALID_SUMMARY_OUTPUT_TEMPLATE)
    fake_output["key_moments"] = [
        {"moment_id": moment_ids[0], "note": "first"},
        {"moment_id": moment_ids[1], "note": "second"},
        {"moment_id": moment_ids[2], "note": "third"},
    ]

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return json.dumps(fake_output)

    monkeypatch.setattr(summarise_mod, "run_claude", fake_run_claude)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["scores"]["summary"] == "Tight roll in closed guard."
    assert body["scores"]["scores"]["guard_retention"] == 8
    assert "distribution" in body
    assert body["finalised_at"] > 0

    # State persisted.
    from server.db import connect, get_roll
    conn = connect(tmp_project_root / "test.db")
    try:
        row = get_roll(conn, roll_id)
    finally:
        conn.close()
    assert row["finalised_at"] is not None
    assert json.loads(row["scores_json"])["summary"] == "Tight roll in closed guard."


@pytest.mark.asyncio
async def test_summarise_returns_400_when_no_analyses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse_moments(client, short_video_path)
        # No analyses inserted — endpoint should 400.
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_summarise_returns_404_for_unknown_roll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/rolls/no-such-roll/summarise", json={})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_summarise_returns_502_on_malformed_claude_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app
    import server.api.summarise as summarise_mod

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse_moments(client, short_video_path)

    _seed_analyses(tmp_project_root / "test.db", roll_id, 3)

    async def fake_malformed(prompt, *, settings, limiter, stream_callback=None):
        return "this is not json"

    monkeypatch.setattr(summarise_mod, "run_claude", fake_malformed)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_summarise_returns_429_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    _minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app
    from server.analysis.claude_cli import RateLimitedError
    import server.api.summarise as summarise_mod

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, _ = await _upload_and_analyse_moments(client, short_video_path)

    _seed_analyses(tmp_project_root / "test.db", roll_id, 3)

    async def fake_rate_limited(prompt, *, settings, limiter, stream_callback=None):
        raise RateLimitedError(retry_after_s=42.0)

    monkeypatch.setattr(summarise_mod, "run_claude", fake_rate_limited)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/rolls/{roll_id}/summarise", json={})

    assert response.status_code == 429
    assert response.headers.get("retry-after") == "42"
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_summarise.py -v
```

Expected: 5 tests fail (endpoint doesn't exist).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_summarise.py
git commit -m "test(bjj-app): add summarise API tests (failing — no impl)"
```

---

## Task 11: Summarise API — implementation

**Files:**
- Create: `tools/bjj-app/server/api/summarise.py`
- Modify: `tools/bjj-app/server/main.py`

- [ ] **Step 1: Create the endpoint**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/api/summarise.py`:

```python
"""POST /api/rolls/:id/summarise — one Claude call across all moments + annotations."""
from __future__ import annotations

import math
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    compute_distribution,
    parse_summary_response,
)
from server.config import Settings, load_settings
from server.db import (
    connect,
    get_analyses,
    get_annotations_by_moment,
    get_moments,
    get_roll,
    set_summary_state,
)

router = APIRouter(prefix="/api", tags=["summarise"])


class _SummariseIn(BaseModel):
    pass


class _SummariseOut(BaseModel):
    finalised_at: int
    scores: dict
    distribution: dict


# Module-level singleton for summary rate limiting.
# Shared across summary + analyse-moment calls — the M3 limiter is bound by
# its consuming endpoints (moments.py has its own). For summary, instantiate
# a separate limiter with the same budget so summaries and per-frame calls
# don't starve each other beyond the 10-per-5-min total. See M6b design for
# revisiting a shared counter.
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
    request: Request,
    settings: Settings = Depends(load_settings),
):
    # ---------- Load inputs ----------
    conn = connect(settings.db_path)
    try:
        roll_row = get_roll(conn, roll_id)
        if roll_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )

        moment_rows = [dict(m) for m in get_moments(conn, roll_id)]
        analyses_by_moment = {
            m["id"]: [dict(a) for a in get_analyses(conn, m["id"])] for m in moment_rows
        }
        annotations_by_moment = {
            m["id"]: [dict(a) for a in get_annotations_by_moment(conn, m["id"])]
            for m in moment_rows
        }
    finally:
        conn.close()

    any_analyses = any(analyses_by_moment[m["id"]] for m in moment_rows)
    if not any_analyses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Roll has no analyses — analyse at least one moment before finalising.",
        )

    # ---------- Build prompt + call Claude ----------
    prompt = build_summary_prompt(
        roll_row=dict(roll_row),
        moment_rows=moment_rows,
        analyses_by_moment=analyses_by_moment,
        annotations_by_moment=annotations_by_moment,
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

    # ---------- Parse + validate ----------
    valid_moment_ids = {m["id"] for m in moment_rows}
    try:
        parsed = parse_summary_response(raw, valid_moment_ids)
    except SummaryResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude gave malformed output: {exc}",
        )

    # ---------- Persist ----------
    now = int(time.time())
    conn = connect(settings.db_path)
    try:
        set_summary_state(
            conn, roll_id=roll_id, scores_payload=parsed, finalised_at=now,
        )
    finally:
        conn.close()

    # ---------- Compute distribution for response ----------
    taxonomy = getattr(request.app.state, "taxonomy", None) or {"categories": [], "positions": []}
    position_to_category = {p["id"]: p["category"] for p in taxonomy.get("positions", [])}
    flat_analyses: list[dict] = []
    for m in moment_rows:
        for a in analyses_by_moment[m["id"]]:
            flat_analyses.append({
                "position_id": a["position_id"],
                "player": a["player"],
                "timestamp_s": m["timestamp_s"],
                "category": position_to_category.get(a["position_id"], "scramble"),
            })
    distribution = compute_distribution(flat_analyses, taxonomy.get("categories", []))

    return _SummariseOut(
        finalised_at=now,
        scores=parsed,
        distribution=distribution,
    )
```

- [ ] **Step 2: Register the router in `main.py`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/main.py`. Add to the import block:

```python
from server.api import summarise as summarise_api
```

Add to the `app.include_router(...)` calls:

```python
    app.include_router(summarise_api.router)
```

- [ ] **Step 3: Reset the singleton between tests**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/conftest.py`. Find the existing `_reset_claude_limiter` fixture (added in M3). Extend it to also reset the summarise limiter:

```python
@pytest.fixture(autouse=True)
def _reset_claude_limiter():
    """Reset the module-level limiter between tests so they don't leak state."""
    yield
    try:
        import server.api.moments as moments_mod
        moments_mod._LIMITER = None
    except Exception:
        pass
    try:
        import server.api.summarise as summarise_mod
        summarise_mod._SUMMARY_LIMITER = None
    except Exception:
        pass
```

- [ ] **Step 4: Run — must pass**

```bash
pytest tests/backend/test_api_summarise.py -v
```

Expected: 5 passed.

Full suite:
```bash
pytest tests/backend -v
```

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/summarise.py tools/bjj-app/server/main.py tools/bjj-app/tests/backend/conftest.py
git commit -m "feat(bjj-app): add POST /api/rolls/:id/summarise endpoint"
```

---

## Task 12: Extend `api/rolls.py` — surface finalised_at, scores, distribution

**Files:**
- Modify: `tools/bjj-app/server/api/rolls.py`

No new test file — existing tests verify no regressions and the new fields have sensible defaults.

- [ ] **Step 1: Extend `RollDetailOut`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/api/rolls.py`.

Extend imports at the top:
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
(this should already be set; keep as-is if it already includes the helpers.)

Add import for the distribution helper:
```python
from server.analysis.summarise import compute_distribution
```

Replace the `RollDetailOut` class with:

```python
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
```

Replace the entire `get_roll_detail` function with:

```python
@router.get("/rolls/{roll_id}", response_model=RollDetailOut)
def get_roll_detail(
    roll_id: str,
    request: Request,
    settings: Settings = Depends(load_settings),
) -> RollDetailOut:
    import json as _json

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

    scores = None
    if row["scores_json"]:
        try:
            scores = _json.loads(row["scores_json"])
        except Exception:
            scores = None

    # Compute distribution if we have analyses + taxonomy.
    distribution = None
    taxonomy = getattr(request.app.state, "taxonomy", None)
    if taxonomy is not None and any(analyses_by_moment[m["id"]] for m in moment_rows):
        position_to_category = {p["id"]: p["category"] for p in taxonomy.get("positions", [])}
        flat_analyses: list[dict] = []
        for m in moment_rows:
            for a in analyses_by_moment[m["id"]]:
                flat_analyses.append({
                    "position_id": a["position_id"],
                    "player": a["player"],
                    "timestamp_s": m["timestamp_s"],
                    "category": position_to_category.get(a["position_id"], "scramble"),
                })
        distribution = compute_distribution(flat_analyses, taxonomy.get("categories", []))

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
        player_a_name=row["player_a_name"] or "Player A",
        player_b_name=row["player_b_name"] or "Player B",
        finalised_at=row["finalised_at"],
        scores=scores,
        distribution=distribution,
        moments=moments_out,
    )
```

Ensure `Request` is imported from FastAPI at the top of the file:
```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
```

- [ ] **Step 2: Run the full suite — no regressions**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend -v
```

Expected: all passing. The new fields have defaults so existing tests that don't mention them still pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/rolls.py
git commit -m "feat(bjj-app): expose finalised_at + scores + distribution on GET /api/rolls/:id"
```

---

## Task 13: Frontend types + `summariseRoll` API client

**Files:**
- Modify: `tools/bjj-app/web/src/lib/types.ts`
- Modify: `tools/bjj-app/web/src/lib/api.ts`

- [ ] **Step 1: Extend types.ts**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/types.ts`. Append at the end of the file:

```typescript

// ---------- M6a: Summary types ----------

export type Scores = {
  guard_retention: number;
  positional_awareness: number;
  transition_quality: number;
};

export type KeyMoment = {
  moment_id: string;
  note: string;
};

export type SummaryPayload = {
  summary: string;
  scores: Scores;
  top_improvements: string[];
  strengths: string[];
  key_moments: KeyMoment[];
};

export type Distribution = {
  timeline: string[];
  counts: Record<string, number>;
  percentages: Record<string, number>;
};

export type SummariseResponse = {
  finalised_at: number;
  scores: SummaryPayload;
  distribution: Distribution;
};
```

Also extend the existing `RollDetail` type. Find:
```typescript
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
  player_a_name: string;
  player_b_name: string;
  moments: Moment[];
};
```

Replace with:
```typescript
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
  player_a_name: string;
  player_b_name: string;
  finalised_at: number | null;
  scores: SummaryPayload | null;
  distribution: Distribution | null;
  moments: Moment[];
};
```

- [ ] **Step 2: Extend api.ts with `summariseRoll`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/api.ts`.

Update the first import block to include the new types. Find:
```typescript
import type {
  AnalyseEvent,
  AnalyseMomentEvent,
  Annotation,
  CreateRollInput,
  GraphPaths,
  GraphTaxonomy,
  PositionNote,
  PublishConflict,
  PublishSuccess,
  RollDetail,
  RollSummary
} from './types';
```

Replace with:
```typescript
import type {
  AnalyseEvent,
  AnalyseMomentEvent,
  Annotation,
  CreateRollInput,
  GraphPaths,
  GraphTaxonomy,
  PositionNote,
  PublishConflict,
  PublishSuccess,
  RollDetail,
  RollSummary,
  SummariseResponse
} from './types';
```

Append at the end of `api.ts`:

```typescript

/**
 * Finalise a roll — one Claude call across all analysed moments + annotations.
 * Returns the parsed summary payload + locally-computed distribution.
 */
export class SummariseRateLimitedError extends Error {
  constructor(
    public readonly retryAfterS: number,
    message: string
  ) {
    super(message);
  }
}

export async function summariseRoll(rollId: string): Promise<SummariseResponse> {
  const response = await fetch(
    `/api/rolls/${encodeURIComponent(rollId)}/summarise`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    }
  );
  if (response.status === 429) {
    const body = await response.json().catch(() => ({}));
    const retryAfter = Number(response.headers.get('Retry-After') ?? body.retry_after_s ?? 60);
    throw new SummariseRateLimitedError(retryAfter, body.detail ?? 'Rate limited');
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as SummariseResponse;
}
```

- [ ] **Step 3: Run existing tests — no regressions**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: all existing tests still pass (new types are additive; no test references them yet).

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/types.ts tools/bjj-app/web/src/lib/api.ts
git commit -m "feat(bjj-app): add SummaryPayload types + summariseRoll API client"
```

---

## Task 14: `ScoresPanel.svelte` — failing tests

**Files:**
- Create: `tools/bjj-app/web/tests/scores-panel.test.ts`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/scores-panel.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import ScoresPanel from '../src/lib/components/ScoresPanel.svelte';
import type { Moment, SummaryPayload } from '../src/lib/types';

function sampleScores(): SummaryPayload {
  return {
    summary: 'A strong roll with good guard retention.',
    scores: {
      guard_retention: 8,
      positional_awareness: 6,
      transition_quality: 7
    },
    top_improvements: [
      'Keep elbows tight when posture is broken.',
      'Frame earlier when the pass shot fires.',
      "Don't overcommit to hip-bump sweeps."
    ],
    strengths: ['Patient grips', 'Strong closed guard'],
    key_moments: [
      { moment_id: 'm1', note: 'Perfect triangle entry timing.' },
      { moment_id: 'm2', note: 'Got swept here — posture broke first.' },
      { moment_id: 'm3', note: 'Clean half-guard recovery.' }
    ]
  };
}

const sampleMoments: Moment[] = [
  { id: 'm1', frame_idx: 3, timestamp_s: 3.0, pose_delta: 1.0, analyses: [], annotations: [] },
  { id: 'm2', frame_idx: 45, timestamp_s: 45.0, pose_delta: 1.0, analyses: [], annotations: [] },
  { id: 'm3', frame_idx: 125, timestamp_s: 125.0, pose_delta: 1.0, analyses: [], annotations: [] }
];

describe('ScoresPanel', () => {
  it('renders three score boxes with the correct values', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText('8/10')).toBeInTheDocument();
    expect(screen.getByText('6/10')).toBeInTheDocument();
    expect(screen.getByText('7/10')).toBeInTheDocument();
  });

  it('renders the one-sentence summary', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(
      screen.getByText('A strong roll with good guard retention.')
    ).toBeInTheDocument();
  });

  it('renders top improvements as a numbered list', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/keep elbows tight/i)).toBeInTheDocument();
    expect(screen.getByText(/frame earlier/i)).toBeInTheDocument();
    expect(screen.getByText(/don't overcommit/i)).toBeInTheDocument();
  });

  it('renders strengths as bullets', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/patient grips/i)).toBeInTheDocument();
    expect(screen.getByText(/strong closed guard/i)).toBeInTheDocument();
  });

  it('renders key moments with timestamp-formatted labels', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    expect(screen.getByText(/0:03/)).toBeInTheDocument();
    expect(screen.getByText(/0:45/)).toBeInTheDocument();
    expect(screen.getByText(/2:05/)).toBeInTheDocument();
    expect(screen.getByText('Perfect triangle entry timing.')).toBeInTheDocument();
  });

  it('key-moment "go to" buttons invoke ongoto with the correct moment_id', async () => {
    const ongoto = vi.fn();
    const user = userEvent.setup();
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto
    });
    // Three go-to buttons.
    const buttons = screen.getAllByRole('button', { name: /go to/i });
    expect(buttons.length).toBe(3);
    await user.click(buttons[0]);
    expect(ongoto).toHaveBeenCalledWith('m1');
    await user.click(buttons[2]);
    expect(ongoto).toHaveBeenCalledWith('m3');
  });

  it('renders a finalised timestamp label', () => {
    render(ScoresPanel, {
      scores: sampleScores(),
      moments: sampleMoments,
      finalisedAt: 1714579500,
      ongoto: vi.fn()
    });
    // Matches "Finalised " prefix (exact date format is locale-dependent).
    expect(screen.getByText(/finalised/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 7 new tests fail (component doesn't exist).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/scores-panel.test.ts
git commit -m "test(bjj-app): add ScoresPanel tests (failing — no impl)"
```

---

## Task 15: `ScoresPanel.svelte` — implementation

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/ScoresPanel.svelte`

- [ ] **Step 1: Write the component**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/components/ScoresPanel.svelte`:

```svelte
<script lang="ts">
  import type { Moment, SummaryPayload } from '$lib/types';

  let {
    scores,
    moments,
    finalisedAt,
    ongoto
  }: {
    scores: SummaryPayload;
    moments: Moment[];
    finalisedAt: number;
    ongoto: (momentId: string) => void;
  } = $props();

  const momentsById = $derived(
    new Map(moments.map((m) => [m.id, m]))
  );

  function formatMmSs(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function formatFinalisedAt(unixS: number): string {
    const d = new Date(unixS * 1000);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function scoreColorClass(score: number): string {
    if (score >= 8) return 'border-emerald-400/50 bg-emerald-500/10 text-emerald-100';
    if (score >= 5) return 'border-amber-400/50 bg-amber-500/10 text-amber-100';
    return 'border-rose-400/50 bg-rose-500/10 text-rose-100';
  }
</script>

<section class="space-y-4 rounded-lg border border-white/10 bg-white/[0.02] p-5">
  <header class="flex items-center justify-between gap-3">
    <h2 class="text-sm font-semibold tracking-tight text-white/90">Summary</h2>
    <span class="text-[11px] text-white/40">
      Finalised {formatFinalisedAt(finalisedAt)}
    </span>
  </header>

  <!-- Three score boxes -->
  <div class="grid grid-cols-3 gap-2">
    <div class="rounded-md border p-3 text-center {scoreColorClass(scores.scores.guard_retention)}">
      <div class="text-xl font-semibold tabular-nums">{scores.scores.guard_retention}/10</div>
      <div class="mt-1 text-[10px] uppercase tracking-wider opacity-75">Retention</div>
    </div>
    <div class="rounded-md border p-3 text-center {scoreColorClass(scores.scores.positional_awareness)}">
      <div class="text-xl font-semibold tabular-nums">{scores.scores.positional_awareness}/10</div>
      <div class="mt-1 text-[10px] uppercase tracking-wider opacity-75">Awareness</div>
    </div>
    <div class="rounded-md border p-3 text-center {scoreColorClass(scores.scores.transition_quality)}">
      <div class="text-xl font-semibold tabular-nums">{scores.scores.transition_quality}/10</div>
      <div class="mt-1 text-[10px] uppercase tracking-wider opacity-75">Transition</div>
    </div>
  </div>

  <!-- One-sentence summary -->
  <p class="text-sm leading-relaxed text-white/85">{scores.summary}</p>

  <!-- Top improvements -->
  <div class="space-y-1">
    <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
      Top improvements
    </div>
    <ol class="list-decimal space-y-1 pl-5 text-sm text-white/80">
      {#each scores.top_improvements as item, i (i)}
        <li>{item}</li>
      {/each}
    </ol>
  </div>

  <!-- Strengths -->
  <div class="space-y-1">
    <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
      Strengths observed
    </div>
    <ul class="list-disc space-y-1 pl-5 text-sm text-white/80">
      {#each scores.strengths as item, i (i)}
        <li>{item}</li>
      {/each}
    </ul>
  </div>

  <!-- Key moments -->
  <div class="space-y-1">
    <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
      Key moments
    </div>
    <ul class="space-y-1 text-sm text-white/80">
      {#each scores.key_moments as km (km.moment_id)}
        {@const moment = momentsById.get(km.moment_id)}
        <li class="flex items-start justify-between gap-3">
          <div class="flex-1">
            <span class="font-mono tabular-nums text-white/60">
              {moment ? formatMmSs(moment.timestamp_s) : '?:??'}
            </span>
            <span class="ml-1">— {km.note}</span>
          </div>
          <button
            type="button"
            onclick={() => ongoto(km.moment_id)}
            aria-label="Go to moment"
            class="shrink-0 rounded-md border border-white/15 bg-white/[0.04] px-2 py-0.5 text-[11px] text-white/75 hover:bg-white/[0.08]"
          >
            Go to →
          </button>
        </li>
      {/each}
    </ul>
  </div>
</section>
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 7 new tests pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/components/ScoresPanel.svelte
git commit -m "feat(bjj-app): add ScoresPanel component"
```

---

## Task 16: Review page — Finalise button + mount ScoresPanel (tests)

**Files:**
- Modify: `tools/bjj-app/web/tests/review-analyse.test.ts`

- [ ] **Step 1: Append tests**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/review-analyse.test.ts`.

Inside the existing `describe('Review page — analyse flow', ...)` block, append before its closing `});`:

```typescript

  it('renders a disabled Finalise button when the roll has no analyses', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => detailWithMoments()
        })
        // getGraph + getGraphPaths may fire in onMount; allow them to fail silently.
        .mockRejectedValueOnce(new Error('ignored'))
    );

    const { default: Page } = await import('../src/routes/review/[id]/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });
    const button = screen.getByRole('button', { name: /finalise/i });
    expect(button).toBeDisabled();
  });

  it('clicking Finalise on a roll with analyses calls POST /summarise and shows the scores panel', async () => {
    const fetchMock = vi.fn();
    // 1. GET roll detail (with one analysed moment)
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        ...detailWithoutMoments(),
        moments: [
          {
            id: 'm1',
            frame_idx: 2,
            timestamp_s: 2.0,
            pose_delta: 0.5,
            analyses: [
              {
                id: 'a1',
                player: 'a',
                position_id: 'closed_guard_bottom',
                confidence: 0.9,
                description: 'd',
                coach_tip: 't'
              },
              {
                id: 'a2',
                player: 'b',
                position_id: 'closed_guard_top',
                confidence: 0.85,
                description: null,
                coach_tip: null
              }
            ],
            annotations: []
          }
        ]
      })
    });
    // 2. getGraph + getGraphPaths — mini graph integration; allow either.
    fetchMock.mockRejectedValueOnce(new Error('no-graph'));
    // 3. POST /summarise
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        finalised_at: 1714579500,
        scores: {
          summary: 'A solid closed-guard roll.',
          scores: {
            guard_retention: 8,
            positional_awareness: 6,
            transition_quality: 7
          },
          top_improvements: ['one', 'two', 'three'],
          strengths: ['strong'],
          key_moments: [
            { moment_id: 'm1', note: 'Perfect entry' },
            { moment_id: 'm1', note: 'Sweep here' },
            { moment_id: 'm1', note: 'Recovery' }
          ]
        },
        distribution: {
          timeline: ['guard_bottom'],
          counts: { guard_bottom: 1 },
          percentages: { guard_bottom: 100 }
        }
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    const { default: Page } = await import('../src/routes/review/[id]/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    const button = screen.getByRole('button', { name: /^finalise$/i });
    expect(button).not.toBeDisabled();
    await user.click(button);

    await waitFor(() => {
      expect(screen.getByText(/a solid closed-guard roll/i)).toBeInTheDocument();
    });
    // Score boxes appear
    expect(screen.getByText('8/10')).toBeInTheDocument();
    // Button relabels to Re-finalise
    expect(screen.getByRole('button', { name: /re-finalise/i })).toBeInTheDocument();
  });

  it('shows a cooldown toast on 429 from summarise', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        ...detailWithoutMoments(),
        moments: [
          {
            id: 'm1',
            frame_idx: 2,
            timestamp_s: 2.0,
            pose_delta: 0.5,
            analyses: [
              {
                id: 'a1', player: 'a', position_id: 'x', confidence: 0.9,
                description: null, coach_tip: null
              },
              {
                id: 'a2', player: 'b', position_id: 'y', confidence: 0.85,
                description: null, coach_tip: null
              }
            ],
            annotations: []
          }
        ]
      })
    });
    fetchMock.mockRejectedValueOnce(new Error('no-graph'));
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 429,
      statusText: 'Too Many Requests',
      headers: new Headers({ 'Retry-After': '42' }),
      json: async () => ({
        detail: 'Claude cooldown — 42s until next call',
        retry_after_s: 42
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    const { default: Page } = await import('../src/routes/review/[id]/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /^finalise$/i }));
    await waitFor(() => {
      expect(screen.getByText(/cooldown/i)).toBeInTheDocument();
    });
  });
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 3 new review-analyse tests fail (Finalise button doesn't exist).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/review-analyse.test.ts
git commit -m "test(bjj-app): add Finalise button + scores panel review tests (failing — no impl)"
```

---

## Task 17: Review page — Finalise button + mount ScoresPanel (impl)

**Files:**
- Modify: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`

- [ ] **Step 1: Wire Finalise button + ScoresPanel**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/routes/review/[id]/+page.svelte`.

Update the import block at the top. Find the existing:
```svelte
  import {
    analyseRoll,
    ApiError,
    getGraph,
    getGraphPaths,
    getRoll,
    publishRoll,
    PublishConflictError
  } from '$lib/api';
```

Replace with:
```svelte
  import {
    analyseRoll,
    ApiError,
    getGraph,
    getGraphPaths,
    getRoll,
    publishRoll,
    PublishConflictError,
    summariseRoll,
    SummariseRateLimitedError
  } from '$lib/api';
  import ScoresPanel from '$lib/components/ScoresPanel.svelte';
```

Also update the types import:
```svelte
  import type { AnalyseEvent, GraphPaths, GraphTaxonomy, Moment, RollDetail } from '$lib/types';
```
(no change needed — RollDetail already gained the new fields).

Add new state near the other `$state` declarations (before `onMount`):
```svelte
  let finalising = $state(false);
  let finaliseError = $state<string | null>(null);
```

Add a new `hasAnyAnalyses` derived near other `$derived`:
```svelte
  const hasAnyAnalyses = $derived(
    roll?.moments?.some((m) => m.analyses.length > 0) ?? false
  );
```

Add the handler function (place near the other handlers like `onSaveToVault`):
```svelte
  async function onFinaliseClick() {
    if (!roll || finalising) return;
    if (!hasAnyAnalyses) return;
    finalising = true;
    finaliseError = null;
    try {
      const result = await summariseRoll(roll.id);
      roll.finalised_at = result.finalised_at;
      roll.scores = result.scores;
      roll.distribution = result.distribution;
    } catch (err) {
      if (err instanceof SummariseRateLimitedError) {
        finaliseError = `Claude cooldown — ${err.retryAfterS}s until next call`;
      } else if (err instanceof ApiError) {
        finaliseError = err.message;
      } else {
        finaliseError = String(err);
      }
    } finally {
      finalising = false;
    }
  }
```

Add a helper for the "go to moment" behaviour (reuse existing chip-click logic):
```svelte
  function onKeyMomentGoTo(momentId: string) {
    const moment = roll?.moments.find((m) => m.id === momentId);
    if (moment) onChipClick(moment);
  }
```

In the template, locate the existing chips row and insert the `ScoresPanel` between the chips row and the `{#if selectedMoment}` block. Find:

```svelte
    {#if roll.moments.length > 0}
      <div class="space-y-2">
        <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
          Moments ({roll.moments.length})
        </div>
        <div class="flex flex-wrap gap-1.5">
          {#each roll.moments as moment (moment.id)}
            ...
          {/each}
        </div>
      </div>

      {#if selectedMoment}
```

Right after the closing `</div>` of the chips wrapper (the outer `<div class="space-y-2">`), and before `{#if selectedMoment}`, insert:

```svelte
      {#if roll.scores && roll.finalised_at}
        <ScoresPanel
          scores={roll.scores}
          moments={roll.moments}
          finalisedAt={roll.finalised_at}
          ongoto={onKeyMomentGoTo}
        />
      {/if}
```

In the footer area, find the existing Save to Vault block. Insert a Finalise row above it (still inside the `{#if roll}` block, before the existing `<footer>`):

```svelte
    <div class="flex items-center justify-between gap-3 border-t border-white/8 pt-4">
      <div class="text-[11px] text-white/40">
        {#if !hasAnyAnalyses}
          Analyse at least one moment first.
        {:else if roll.finalised_at}
          Finalised. Click to recompute with the latest analyses + notes.
        {:else}
          Not yet finalised.
        {/if}
      </div>
      <button
        type="button"
        onclick={onFinaliseClick}
        disabled={finalising || !hasAnyAnalyses}
        class="rounded-md border border-blue-400/40 bg-blue-500/15 px-3 py-1.5 text-xs font-medium text-blue-100 hover:bg-blue-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {finalising ? 'Finalising…' : roll.finalised_at ? 'Re-finalise' : 'Finalise'}
      </button>
    </div>

    {#if finaliseError}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        {finaliseError}
      </div>
    {/if}
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: all tests pass (62 existing frontend + 3 new review-analyse + 7 new scores-panel = 72 total).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/review/[id]/+page.svelte
git commit -m "feat(bjj-app): wire Finalise button + mount ScoresPanel on review page"
```

---

## Task 18: End-to-end browser smoke test

**Files:** none — manual verification.

- [ ] **Step 1: Start dev mode**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && ./scripts/dev.sh
```

- [ ] **Step 2: Prepare a test roll**

Open `http://127.0.0.1:5173/new`. Upload a short video. Name Player A + B (or leave blank). Upload. On the review page click **Analyse** to run the pose pre-pass. Click 3 moment chips and analyse each with Claude so you get per-moment analyses. Optionally type a couple of annotations.

- [ ] **Step 3: Click Finalise**

Click the **Finalise** button in the footer. Expected:
- Label changes to "Finalising…".
- After 10-60s: the scores panel appears above `MomentDetail` with 3 score boxes, a one-sentence summary, numbered improvements, bullet strengths, and 3 key moments.
- The button relabels to "Re-finalise" with "Finalised <timestamp>" subtitle.

- [ ] **Step 4: Go-to a key moment**

Click a key moment's **Go to →** button. Expected: video seeks to that moment's timestamp; the chip for that moment selects; `MomentDetail` updates.

- [ ] **Step 5: Save to Vault**

Click **Save to Vault**. Expected: toast "Published to Roll Log/...".

Open the markdown file in Obsidian (or `cat` it). Expected:
- Frontmatter with `roll_id`.
- `## Summary`, `## Scores` (table), `## Position Distribution` (table + timeline bar), `## Key Moments`, `## Top Improvements`, `## Strengths Observed`.
- `## Your Notes` at the bottom with your annotations.

- [ ] **Step 6: Conflict detection**

In Obsidian, edit a word in `## Summary`. Save. Back in the app, add an annotation somewhere and click Re-finalise → Save to Vault. Expected: the conflict dialog fires. Click Overwrite. Expected: toast success; Obsidian's edit is replaced by the app's version.

- [ ] **Step 7: Unrelated section preserved**

In Obsidian, append a new section `## Extra thoughts` with some text. Save. Back in the app, click Save to Vault. Expected: no conflict dialog; success toast. Re-check the file — `## Extra thoughts` is still there.

- [ ] **Step 8: Regression — unfinalised roll still works**

Upload a new roll, analyse one moment, but do NOT Finalise. Click Save to Vault. Expected: success. The vault markdown has only `## Your Notes`, no summary sections.

- [ ] **Step 9: Stop the dev server** (Ctrl-C).

---

## Task 19: Update README + M3 security audit addendum

**Files:**
- Modify: `tools/bjj-app/README.md`
- Modify: `docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`

- [ ] **Step 1: Update README milestones section**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/README.md`. Replace the `## Milestones` section and everything below with:

```markdown
## Milestones

- **M1 (shipped):** Scaffolding. Home page lists vault's `Roll Log/` via `GET /api/rolls`.
- **M2a (shipped):** Video upload (`POST /api/rolls`), review page skeleton, `/assets/` static mount.
- **M2b (shipped):** MediaPipe pose pre-pass, `POST /api/rolls/:id/analyse` SSE endpoint, timeline chips seek the video on click.
- **M3 (shipped):** Claude CLI adapter (sole `claude -p` caller), `POST /api/rolls/:id/moments/:frame_idx/analyse` streaming, SQLite cache, sliding-window rate limiter. Security audit at `docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`.
- **M4 (shipped):** Append-only annotations per moment, explicit "Save to Vault" publish to `Roll Log/*.md`, hash-based conflict detection on `## Your Notes` only, home page routes via `roll_id` frontmatter.
- **M5 (shipped):** Full `/graph` page with clustered state-space visualisation, both players' paths overlaid, filter chips, vault-markdown side drawer, scrubber with smoothly-animated path-head markers. Mini graph widget on `/review/[id]`.
- **M6a (this milestone):** Summary step. `POST /api/rolls/:id/summarise` runs one Claude call across all moments + annotations → scores + summary + top-3 improvements + strengths + 3 key-moment pointers. `ScoresPanel` renders on the review page; `Save to Vault` now emits `## Summary`, `## Scores`, `## Position Distribution`, `## Key Moments`, `## Top Improvements`, `## Strengths Observed` sections alongside `## Your Notes`. Per-section hash-based conflict detection. Design at `docs/superpowers/specs/2026-04-21-bjj-app-m6a-summary-step-design.md`.
- **M6b (next):** PDF export via WeasyPrint. "Export PDF" button on the review page generates a printed match report from the finalised roll.
- **M7–M8:** PWA + mobile polish; cleanup (delete Streamlit `tools/app.py`).
```

- [ ] **Step 2: Add audit addendum**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`. Append at the end of the file:

```markdown

---

## Addendum (2026-04-21) — `run_claude` second call-site for summary prompts (M6a)

M6a extracts `run_claude(prompt, settings, limiter, stream_callback)` from `analyse_frame` to reuse the subprocess seam for a second prompt type: the coaching summary call at `POST /api/rolls/:id/summarise`.

### What differs from the classification prompt

The classification prompt (M3) was deterministic and contained **no user input** — it interpolated only the taxonomy, a frame-path reference, and a timestamp. That invariant made the cache key stable and eliminated prompt-injection risk.

The summary prompt includes **user-typed annotation text verbatim** (the user's notes on specific moments from M4). This is an explicit design trade-off: the summary endpoint is not cached, Claude's output is schema-validated + used only to populate SQLite + vault markdown (no downstream command execution), and the subprocess still spawns argv-only with `--max-turns 1` and `stderr=DEVNULL`.

### Mitigations in place

1. Prompt never interpolates file paths, shell metacharacters, or URLs. Only natural-language annotation bodies.
2. Claude's output is strictly schema-validated (`parse_summary_response`); unknown keys are dropped, scores are clamped, hallucinated `moment_id`s are rejected.
3. Rate limiting + single-retry behaviour from M3 is preserved.

### Re-audit triggers for this call-site

- If a future change lets the summary prompt execute shell commands based on Claude output, re-audit.
- If `run_claude` is used with any user-supplied *prompt* string (e.g. a "custom coach tip" feature where the user controls the prompt template), re-audit — the current mitigation relies on the prompt structure being ours.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/README.md docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md
git commit -m "docs(bjj-app): document M6a milestone + audit addendum for summary prompt"
```

---

## Completion criteria for M6a

1. `pytest tests/backend -v` → all green (140 + ~30 new M6a tests ≈ 170 passing, 1 opt-in integration deselected).
2. `npm test` → all green (65 + 7 scores-panel + 3 review-analyse ≈ 75 passing).
3. Manual smoke (9 steps above) passes.
4. No M1–M5 tests regress.
5. `claude_cli.run_claude` is used by both `analyse_frame` (M3 behaviour preserved) and `api/summarise.py` (M6a new call-site). No third call-site.
6. The security audit addendum is committed and explicitly notes the relaxed "no user input in prompt" rule for the summary call-site with enumerated mitigations.

---

## Out of scope (deferred to later milestones)

| Deliverable | Why deferred |
|---|---|
| WeasyPrint + `POST /api/rolls/:id/export/pdf` + HTML template | M6b — its own plan. |
| Re-finalise confirmation dialog | Label change + timestamp are enough signal. |
| Per-moment "pin as key" affordance | Claude's key_moments choice is usually good; revisit if it misses. |
| Versioned score history | `scores_json` overwrites on re-finalise. |
| Tunable score rubric / additional metrics | Fixed three metrics in M6a. |
| Auto-finalise after N analyses | Finalise is always explicit. |
| Share-via-PDF / email export | Belongs to M6b or later. |
