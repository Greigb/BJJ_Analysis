# BJJ App M9 — User-Picked Sections — Design

**Date:** 2026-04-22
**Status:** Design approved, implementation plan pending
**Parent spec:** [2026-04-20-bjj-local-review-app-design.md](./2026-04-20-bjj-local-review-app-design.md)
**Prior milestone:** M8 (Streamlit retirement) shipped at `402b63d` on main.
**Follow-on:** M10 (Obsidian knowledge grounding) — separate spec, pairs with the denser analysis this milestone delivers.

## Context

Since M2b the app has used a MediaPipe pose pre-pass on the whole video to flag 3-30 "interesting" moments based on skeleton delta, then Claude classifies each flagged moment on demand. In practice this selection is a poor proxy for the moments the user actually wants to analyse: a reviewer knows a roll's turning points (sweep at 0:14, back-take attempt at 1:53) and wants to focus Claude there, not on whichever frames happened to have sharp pose changes.

M9 replaces the pose pre-pass with explicit user-picked time ranges. The reviewer plays the video, marks start/end timestamps for each section of interest, tunes per-section sampling density, and clicks Analyse. Only the picked ranges go through frame extraction → Claude classification. Each section is a first-class DB record so the UI can reference, edit, and (in M9b) visually band the picked ranges on the scrubber.

M9 is deliberately self-contained: it improves focus and density. **M10** (separate) layers Obsidian vault notes into the classification prompt for better accuracy. Shipping them sequentially gives a clean A/B signal on each change.

## Goals

1. **Replace auto-selection with explicit user intent.** Picked sections are the only source of moments; no pose-delta heuristic runs.
2. **Denser analysis inside picked ranges.** Default 1 fps inside a picked range (vs. the old top-20%-of-1-fps global filter). User can tune per-section to 0.5s or 2s intervals when they want more or less detail.
3. **Persist sections as first-class data.** Sections are a new DB entity so the UI, graph page, and future features can reason about "these are the moments in my 0:10-0:14 section."
4. **Zero-friction UX tuned to the review loop.** Play the video, press Mark start / Mark end while watching — no modal, no separate picker view. Add multiple sections across a roll, then one Analyse click processes them all.
5. **Clean deletion of the pose pre-pass.** Remove MediaPipe dep, remove pose-delta selection code, remove related tests. Existing rolls' moments (with `section_id = NULL`) keep rendering.

## Non-goals (explicit)

- **No band overlay on the video scrubber.** Showing the picked sections as coloured regions on the timeline is a nice-to-have; M9b if we want it. Sections are visible as chips in a list next to the video; the chips on the per-moment timeline strip are their own render.
- **No section-level analyses.** Each moment inside a section still gets its own Claude call on chip-click (M3 per-moment flow unchanged). There is no "summarise the section" Claude call.
- **No automatic section suggestions.** If the user later wants "show me candidate sections from the pose-delta signal", that's M9b. M9 has no auto mode.
- **No cross-section dedup.** If two sections overlap, frames are extracted twice (filesystem is idempotent on `os.replace`, DB has a uniqueness index on `(roll_id, frame_idx)` so the second insert collapses). No effort to warn the user.
- **No in-place edit of a section after its moments land.** Once Analyse has run and a section's moments exist, the chip becomes read-only (timestamps + density are frozen). To change a range, delete the section (cascade-deletes its moments) and add a new one. Pre-analyse chips remain fully editable via their `mm:ss` inputs and density dropdown. M9b can relax this.
- **No import of the old pose-pre-pass signal as "starter sections".** Fresh mental model.

## Design decisions (captured from brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Replace vs. coexist | Replace pose pre-pass entirely | Dual paths double UI + state complexity. Old heuristic was wrong in practice. |
| Section selection UX | Play-and-mark buttons + editable chip list | Ergonomic inside the existing video-watch loop. No custom scrubber widget. |
| Density | User-configurable per section (1s / 0.5s / 2s) | Directly matches "I want more focus here" intent. 1s default matches existing extractor. |
| Persistence model | Persistent `sections` table | Sections are a first-class UI concept ("I picked these ranges"), not a mid-pipeline detail. Enables M9b scrubber bands + grouping. |
| Split from M10 | M9 sections, M10 knowledge grounding | Clean A/B signal; each milestone is small + testable. |

## Architecture

One new backend module (sections pipeline), one small DB migration, one new frontend component, deletions of the pose pre-pass code.

### New DB schema (migration runs at startup)

```sql
CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    roll_id TEXT NOT NULL REFERENCES rolls(id) ON DELETE CASCADE,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    sample_interval_s REAL NOT NULL,
    created_at INTEGER NOT NULL
);

-- Added in M9 migration; NULL for pre-M9 rolls.
-- FK constraint with ON DELETE SET NULL so deleting a section doesn't
-- orphan-delete its moment rows; callers that want cascade-delete call
-- `delete_section_and_moments` which does both inside one transaction.
ALTER TABLE moments ADD COLUMN section_id TEXT REFERENCES sections(id) ON DELETE SET NULL;

-- Guarantees overlapping sections don't double-insert the same (roll_id, frame_idx).
CREATE UNIQUE INDEX IF NOT EXISTS idx_moments_roll_frame ON moments(roll_id, frame_idx);
```

SQLite requires `PRAGMA foreign_keys = ON` per connection for FK constraints to fire; `server/db.py::connect` already sets it. The migration is idempotent — re-running against a DB that already has the table / column / index is a no-op.

On section delete: `delete_section_and_moments(conn, section_id)` (new helper) runs `DELETE FROM moments WHERE section_id = ?` followed by `DELETE FROM sections WHERE id = ?` in one transaction, which is what the UI chip-delete button calls. The FK's `ON DELETE SET NULL` is a safety net for direct SQL edits.

### New backend module: `server/analysis/sections.py`

Pure helpers, no SQLite, no subprocess:

```python
def build_sample_timestamps(
    start_s: float,
    end_s: float,
    interval_s: float,
) -> list[float]: ...

def frame_paths_for_timestamps(
    video_path: Path,
    timestamps: list[float],
    out_dir: Path,
) -> list[Path]: ...
```

`build_sample_timestamps` returns a deterministic list of timestamps: inclusive at `start_s`, strictly less than `end_s`, stepped by `interval_s`. Clamped so 0.0 ≤ start < end ≤ duration (caller passes `duration_s`).

`frame_paths_for_timestamps` seeks OpenCV to each requested timestamp and writes `frame_<frame_idx>.jpg` with `frame_idx` derived from `round(timestamp_s * VIDEO_FPS)` so chips map cleanly to the source FPS. Reuses `server/analysis/frames.py`'s write helpers — small refactor to expose a `write_frame_at_timestamp(video_path, ts, out_path)` function.

### Replaced module: `server/analysis/pipeline.py`

- Delete `_flag_moments` + `PoseDetector` import + pose_delta calculation + top-20%-of-deltas filter.
- Replace the single `run_analysis(video_path, frames_dir) -> Iterator[Event]` with:

```python
def run_section_analysis(
    *,
    conn,
    roll_id: str,
    video_path: Path,
    frames_dir: Path,
    sections: list[dict],          # [{"start_s", "end_s", "sample_interval_s"}]
    duration_s: float,
) -> Iterator[Event]: ...
```

Emits the existing SSE event shapes so the frontend handler needs only minimal change:

- `{"stage": "frames", "pct": 0..100}` — frame extraction progress.
- `{"stage": "done", "total": int, "moments": [...]}` — with each moment including `id`, `frame_idx`, `timestamp_s`, `section_id`.

The pose stage is simply removed — no event emitted for it.

Implementation order inside the pipeline:

1. Open a single transaction on `conn`.
2. For each input section, insert a row into `sections` and collect the generated section_id.
3. Build the full timestamp list across all sections (flat, sorted, deduped on `frame_idx`).
4. Write frames to `frames_dir` one at a time, yielding `frames/pct` events every N frames.
5. Batch-insert moment rows with the correct `section_id` FK. Unique index on `(roll_id, frame_idx)` collapses overlaps.
6. Yield the final `done` event with the persisted moments.
7. Commit.

No partial-failure rollback beyond the transaction boundary — if frame extraction crashes mid-stream, the SSE stream errors, the transaction rolls back, the user retries.

### Rewritten endpoint: `POST /api/rolls/:id/analyse`

**Request body:**

```json
{
  "sections": [
    {"start_s": 10.0, "end_s": 14.0, "sample_interval_s": 1.0},
    {"start_s": 113.0, "end_s": 130.0, "sample_interval_s": 0.5}
  ]
}
```

**Validation:**
- `400` if `sections` missing or empty.
- `400` if any section has `start_s >= end_s`, `start_s < 0`, or `end_s > roll.duration_s + epsilon`.
- `400` if `sample_interval_s` is not one of `{2.0, 1.0, 0.5}`.
- `404` if roll not found.

**Response:** streaming SSE (`text/event-stream`), same shape as today. Existing client `onAnalyseClick` → `handleAnalyseEvent` path adapts with a one-line change.

### Deletions (carry-forward cleanup)

- `server/analysis/pose.py` (MediaPipe loader).
- `mediapipe` from `tools/bjj-app/pyproject.toml`.
- `opencv-python-headless` stays (still used for frame reads).
- `tests/backend/test_pose.py` (if present) and any pose-pre-pass cases in `test_api_analyse.py`.
- MediaPipe-related imports at module top of `pipeline.py`.

### Frontend: new `SectionPicker.svelte` + review page wiring

New component `web/src/lib/components/SectionPicker.svelte`:

**Props:**
```typescript
{
  videoEl: HTMLVideoElement | undefined;
  durationS: number;
  onAnalyse: (sections: Section[]) => void;
  busy: boolean;
}
```

where `Section = { id: string; start_s: number; end_s: number; sample_interval_s: 1 | 0.5 | 2 }` (client-only; server-side section_id is assigned post-POST).

**State:**
- `sections: $state<Section[]>` — the staged list.
- `pendingStart: $state<number | null>` — set by Mark start, cleared by Mark end or Cancel.
- `currentTime: $state(0)` — mirrored from `videoEl.currentTime` via `timeupdate` listener.

**Rendered layout:**

1. Two primary buttons: **Mark start** (disabled if `pendingStart != null`), **Mark end** (disabled if `pendingStart == null || currentTime <= pendingStart`). A secondary **Cancel** resets the pending state.
2. A pending indicator strip when `pendingStart != null`: `Pending section starting at 0:03 — play and click Mark end.`
3. A chip list (one per committed section):
   - Two editable `<input type="text">` fields showing `mm:ss` with a parser (`0:03` → 3.0 s). `blur` commits; invalid input reverts to previous value.
   - Density dropdown: `1s (default)` / `0.5s` / `2s`.
   - Delete button (trash icon).
   - A seek button (arrow icon) that calls `videoEl.currentTime = start_s; videoEl.play()`.
4. **Analyse ranges** button at the bottom, disabled when `sections.length === 0 || busy`.

**Review page wiring (`web/src/routes/review/[id]/+page.svelte`):**
- Replace the current header-bar Analyse button with a compact placeholder when the roll has no picked-yet-analysed sections.
- Drop `<SectionPicker>` into the left column below the video element.
- `onAnalyse(sections)` wires to the existing `onAnalyseClick` handler (renamed `onAnalyseSections`) — calls `analyseRoll(id, sections)` (new signature), streams SSE, updates `roll.moments` as today.
- Keep the existing chip timeline under the video; chips show as today regardless of `section_id`.

### Types + API client

`web/src/lib/types.ts`:

```typescript
export interface Section {
  id: string;
  start_s: number;
  end_s: number;
  sample_interval_s: 1 | 0.5 | 2;
}

// Added to Moment
section_id: string | null;

// Added to RollDetail
sections: Section[];
```

`web/src/lib/api.ts`:

```typescript
export async function analyseRoll(rollId: string, sections: SectionInput[]): Promise<Response>;
```

where `SectionInput = { start_s, end_s, sample_interval_s }` (no client id — server assigns).

## Testing

### Backend

`tests/backend/test_sections.py` — unit tests for `build_sample_timestamps` + `frame_paths_for_timestamps`:
- Timestamps: inclusive-left/exclusive-right semantics; `interval_s=1`, `0.5`, `2`; edge cases (start==end returns empty; interval bigger than range returns `[start_s]`).
- Frame paths: seeking to an out-of-range timestamp raises `ValueError`; frame_idx is `round(ts * fps)`.

`tests/backend/test_api_analyse_sections.py` (rewrite of `test_api_analyse.py`):
- `400` on empty sections.
- `400` on invalid section (end ≤ start, negative start, end > duration, bad interval).
- `404` on missing roll.
- Happy path: POST with two sections → SSE stream → `sections` rows inserted → `moments` rows inserted with `section_id` FK set → `frames_dir` contains the expected files.
- Overlap path: sections 0-5 and 3-8 → unique index prevents double `frame_idx` rows; moments that would clash map to whichever section's transaction inserted first (documented; we don't resolve it more cleverly).

### Frontend

`web/tests/section-picker.test.ts`:
- Mark start captures current time and stages it; Mark end commits a section and resets pending.
- Cancel resets pending without creating a section.
- Delete removes a chip.
- Editable mm:ss parsing: `0:03` → `3.0`; invalid → revert.
- Density dropdown updates `sample_interval_s`.
- Analyse ranges button disabled when sections empty / busy.
- onAnalyse callback fires with the current sections on click.

`web/tests/review-analyse.test.ts` (rewrite):
- SSE-stream mocks for frame-only progress (no pose stage).
- Chips appear with `section_id` propagated from the done event.

### Manual smoke

After implementation:

1. Upload a short clip. In the video player, play to 0:03 → Mark start. Play to 0:07 → Mark end. Chip `0:03 – 0:07 @ 1s`.
2. Seek to 0:15 → Mark start. Play to 0:25 → Mark end. Change dropdown to 0.5s. Chip `0:15 – 0:25 @ 0.5s`.
3. Click Analyse ranges. SSE `frames/pct` ticks 0 → 100. Done event lands.
4. Expect 4 chips from section 1 (timestamps 3, 4, 5, 6) and 20 chips from section 2 (0.5s steps in 0:15-0:25). Total 24 chips on the timeline.
5. Click a chip → the existing per-moment Claude analyse endpoint fires, MomentDetail renders the result.
6. On disk: `assets/<roll_id>/frames/frame_<int>.jpg` only for the picked timestamps.
7. In SQLite: `SELECT count(*) FROM sections WHERE roll_id = '<id>'` = 2; `SELECT section_id, count(*) FROM moments GROUP BY section_id` shows 4 + 20.
8. Delete a section chip (UI) → row removed from `sections` (FK cascade deletes its moments) → chips disappear from the timeline.

## Dependencies

**Removed:**
- `mediapipe` from `tools/bjj-app/pyproject.toml` dependencies list.

**Unchanged:**
- `opencv-python-headless` (still reads frames).
- `python-frontmatter`, `weasyprint`, `jinja2`, all prior M1-M8 deps.
- No npm additions.

## File structure impact

**New files:**
- `tools/bjj-app/server/analysis/sections.py`
- `tools/bjj-app/tests/backend/test_sections.py`
- `tools/bjj-app/tests/backend/test_api_analyse_sections.py`
- `tools/bjj-app/web/src/lib/components/SectionPicker.svelte`
- `tools/bjj-app/web/tests/section-picker.test.ts`

**Modified files:**
- `tools/bjj-app/server/db.py` — migration for `sections` table + `moments.section_id` column + unique index + `insert_section`, `get_sections_by_roll`, `delete_section_and_moments` helpers.
- `tools/bjj-app/server/analysis/pipeline.py` — delete pose-delta logic, add `run_section_analysis`.
- `tools/bjj-app/server/analysis/frames.py` — small refactor to expose `write_frame_at_timestamp`.
- `tools/bjj-app/server/api/analyse.py` — accept `sections` body, validate, call new pipeline.
- `tools/bjj-app/server/api/rolls.py` — `RollDetailOut.moments[*]` gains `section_id`; add `sections: list[SectionOut]` field.
- `tools/bjj-app/web/src/lib/api.ts` — `analyseRoll(id, sections)` signature change.
- `tools/bjj-app/web/src/lib/types.ts` — `Section` type + RollDetail extension.
- `tools/bjj-app/web/src/routes/review/[id]/+page.svelte` — swap Analyse button for `<SectionPicker>`.
- `tools/bjj-app/pyproject.toml` — drop `mediapipe`.
- `tools/bjj-app/tests/backend/test_api_analyse.py` — rewrite for new endpoint (or replace with the new file above and delete this one).
- `tools/bjj-app/web/tests/review-analyse.test.ts` — rewrite for the new flow.
- `tools/bjj-app/README.md` — M9 section.

**Deleted files:**
- `tools/bjj-app/server/analysis/pose.py` (MediaPipe loader).
- Any `tests/backend/test_pose.py` if it exists.

## Out of scope (explicitly deferred)

| Deliverable | Why deferred |
|---|---|
| Coloured section bands on the video scrubber | M9b if the chip list alone feels insufficient. Requires a custom scrubber overlay. |
| In-place section edit after analysis | M9b. For now, delete + re-create. |
| Auto-suggest sections from pose-delta signal | M9b. Would reintroduce the MediaPipe path we just retired, behind a "Suggest" button. |
| Multi-select chip dedup across overlapping sections | Relies on DB unique-index fallback. Good enough for now. |
| Section summaries (Claude call per section) | Out of scope — finalise/summarise roll-level stays the M6a pathway. |
| Mobile range-picking UX | M7 was abandoned; mobile isn't supported. |
