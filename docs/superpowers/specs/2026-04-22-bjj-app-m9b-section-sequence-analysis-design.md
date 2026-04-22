# BJJ App M9b — Section Sequence Analysis — Design

**Date:** 2026-04-22
**Status:** Design approved, implementation plan pending
**Parent spec:** [2026-04-20-bjj-local-review-app-design.md](./2026-04-20-bjj-local-review-app-design.md)
**Prior milestone:** M9 (user-picked sections) merged at `5074506` on main.
**Follow-on:** M10 (Obsidian knowledge grounding) — will extend M9b's multi-image prompt with `## How to Identify` vault text.

## Context

M9 shipped user-picked time-range sections in place of the auto pose pre-pass. Each picked range was sampled at user-configurable density (1s / 0.5s / 2s) into individual frames; each frame became a moment chip on the timeline; the user clicked each chip to fire per-frame Claude classification. In practice this produces noise (one narrow classification per frame with a poorly-calibrated confidence number) and asks the user to click N times per section to see what happened.

The user review after M9 smoke-testing identified the real shape: the analyst doesn't want per-frame classifications — they want to know what *happened across a sequence*. Mark 0:10-0:14, get Claude's narrative of the 4-second action in one shot. No per-frame chips, no confidence numbers, no per-moment clicking.

M9b pivots the analysis unit from moment-level to section-level. One Claude call per section, multi-image prompt (5-8 frames from the range in chronological order), narrative + coach_tip output. The existing M9 infrastructure (sections table, SectionPicker component, `/analyse` endpoint, section_id FK on moments) stays. Moments become an internal implementation detail — still stored, never shown.

The graph page is hidden (not deleted) since its per-moment position-path visualisation has no structured data to render post-M9b. It may come back after M11 (eval harness) validates whether structured per-frame output is worth asking Claude for.

## Goals

1. **One Claude call per section.** Multi-image prompt with 5-8 chronologically-ordered frames from the picked range; returns narrative + coach_tip. The user reviews the story of what happened, not a chain of per-frame classifications.
2. **Moments disappear from the UI.** Frames are still extracted (internally, for Claude) but never surfaced as chips or clickable moment detail. Section cards replace moment chips as the primary display unit.
3. **Annotations move to section-level.** A section card has a notes field; each annotation attaches to its section directly. Existing moment-scoped annotation data is discarded (smoke-test only) in the migration.
4. **Finalise rollup consumes sections.** The M6a summarise prompt is rewritten to take per-section narratives + coach_tips + annotations as input, emitting the same output shape (scores, improvements, strengths, key-moment pointers now by section_id).
5. **Batch trigger, sequential execution.** Stage N sections in the picker, click Analyse ranges, backend processes them one at a time, streams per-section progress via SSE, and section cards hydrate as each completes.
6. **Graph page hidden, not deleted.** Nav link removed; route + component kept on disk for potential revival after M11.

## Non-goals (explicit)

- **No per-section Re-analyse button.** Delete + re-mark works for v1.
- **No in-place edit of section timestamps after analysis.** Section rows are insert-only once `analysed_at` is set.
- **No auto-trigger on Mark end.** Staging phase + explicit Analyse ranges button preserved from M9.
- **No user-configurable frame density.** Always 1 fps, capped at 8 frames per section. The sections.sample_interval_s column stays (for schema stability) but is always set to the derived value.
- **No parallel section analysis.** Sequential keeps error isolation clean.
- **No multi-image Claude cache.** The per-frame `claude_cache` table stays; M9b's path doesn't consult it. Hit rate on user-picked ranges would be ~0%.
- **No structured per-frame position IDs in the response.** Narrative only. Could be re-added post-M11 if eval shows value.
- **No numeric confidence scoring.** Dropped entirely — description is the confidence signal.
- **No migration of pre-M9b moment-scoped annotations.** Clean slate.
- **No dedup of overlapping sections.** User can delete duplicates.
- **No graph-page rebuild.** Hidden only.
- **No mobile UX.** M7 abandoned.

## Design decisions (captured from brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Analysis unit | One Claude call per section | User explicitly asked for this; removes per-chip friction. |
| Response shape | Narrative + coach_tip, no structured fields | YAGNI — narratives carry the signal; M10 grounds vocabulary; structured output revisited post-M11. |
| Frame count | 1 fps proportional, cap 8 | Matches typical 3-10 s sections; cap protects context budget. |
| Trigger | Batch "Analyse ranges" button (M9 pattern) | Preserves the staging / edit-before-commit window; explicit cost gate. |
| Annotations model | Migrate FK from moment_id to section_id | Sections are the new UI-level unit; clean break since existing data is smoke-test only. |
| Moment UI | Removed | No per-moment affordance needed; moments become internal storage. |
| Graph page | Hidden (nav un-linked, route + code kept) | No data to render post-M9b; revive post-M11 if worth it. |
| Pipeline semantics | Append new sections, not replace | User expectation: stage → analyse → return tomorrow → stage more → analyse → both preserved. |
| Confidence | Dropped | LLM self-reported confidence is badly calibrated; description suffices. |
| Distribution rollup | Dropped from vault + PDF | No structured per-frame data to aggregate. |

## Architecture

### Data model changes

**`sections` table gains three columns:**

```sql
ALTER TABLE sections ADD COLUMN narrative TEXT;       -- Claude's paragraph
ALTER TABLE sections ADD COLUMN coach_tip TEXT;       -- one-sentence coach tip for player_a
ALTER TABLE sections ADD COLUMN analysed_at INTEGER;  -- unix seconds, NULL = staged but not analysed
```

Existing `sample_interval_s` column is retained but always written as `1.0` (no user affordance). The cap-at-8 behaviour is in the pipeline, not the DB.

**`annotations` table is rebuilt** (FK from `moment_id` to `section_id`). SQLite doesn't drop/alter FK in place — the migration follows the standard recreate pattern:

```sql
CREATE TABLE annotations_new (
    id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
DROP TABLE annotations;
ALTER TABLE annotations_new RENAME TO annotations;
```

Pre-M9b annotation data is dropped (smoke-test artifacts only).

**`moments` table is unchanged.** Rows continue to be inserted per extracted frame, with `section_id` set. No UI surface.

### DB helpers — renames and reworks

**Renamed:**
- `insert_annotation(conn, moment_id, body)` → `insert_annotation(conn, section_id, body)`
- `get_annotations_by_moment(conn, moment_id)` → `get_annotations_by_section(conn, section_id)`

**Reworked:**
- `get_annotations_by_roll(conn, roll_id)` — keeps its name; SQL changes to join sections → annotations (was moments → annotations).
- `delete_section_and_moments(conn, section_id)` — gains a step to delete the frame files on disk for the moments removed. New argument: `frames_dir: Path` or looked up via roll's asset dir.

**New:**
- `update_section_analysis(conn, section_id, narrative, coach_tip, analysed_at)` — UPDATE sections SET narrative=?, coach_tip=?, analysed_at=? WHERE id=?.

### Multi-image Claude call

Verified working via direct CLI test (2026-04-22):

```
claude -p --model claude-opus-4-7 "prompt text with @frame1.jpg @frame2.jpg @frame3.jpg refs"
```

Returns coherent chronological narrative identifying positions, transitions, and tactical reads across frames. Token cost is ~1k per image + prompt; 8 frames + instruction ≈ 9-10k tokens input; output is ~100-200 tokens. Well within Claude Opus context.

### Prompt (V1, un-grounded baseline)

Constructed in `server/analysis/prompt.py` — new function `build_section_prompt(section, frame_paths, player_a_name, player_b_name)`:

```
You are analysing a Brazilian Jiu-Jitsu sequence between {player_a_name} (player_a in output) and {player_b_name} (player_b in output).

Below are {N} chronologically ordered frames spanning {duration_s}s of footage. Review all frames as one continuous sequence and describe what happens.

Frame 1 @t={t1}s: @{frame_paths[0]}
Frame 2 @t={t2}s: @{frame_paths[1]}
...
Frame N @t={tN}s: @{frame_paths[N-1]}

Describe the positions, transitions, who initiates what, and where the sequence ends. Use standard BJJ vocabulary (e.g. "closed guard bottom", "passes half guard to side control", "triangle attempt"). Follow with one actionable coach tip directed at player_a.

Output ONE JSON object and nothing else. No prose outside JSON. No markdown fences.

{
  "narrative": "<one paragraph, 2-5 sentences>",
  "coach_tip": "<one actionable sentence for player_a>"
}
```

`parse_section_response(raw) -> dict` — strict JSON parse + schema validation (narrative non-empty string, coach_tip non-empty string). Raises `SectionResponseError` on malformed output.

M10 will extend `build_section_prompt` with an optional `positions_index` argument that appends `## How to Identify` vault text after the instruction block. That extension doesn't land in M9b — this prompt is the pre-grounding baseline so M10's delta is observable.

### Pipeline rewrite

`server/analysis/pipeline.py::run_section_analysis` is reshaped to do the Claude call inline, per section:

```python
def run_section_analysis(
    *,
    conn,
    roll_id: str,
    video_path: Path,
    frames_dir: Path,
    sections: list[dict],          # [{"start_s", "end_s"}] — sample_interval ignored
    duration_s: float,
    player_a_name: str,
    player_b_name: str,
    settings: Settings,
    limiter: SlidingWindowLimiter,
) -> AsyncIterator[dict]: ...
```

(Async now — Claude calls are awaited; existing M9 version was sync. `api/analyse.py` updates to `async def`.)

**Per-section loop (sequential, append semantics):**

1. Compute timestamps: 1 fps, cap at 8. For a 5-second section, 5 frames; for a 15-second section, 8 frames.
2. Compute `start_index` for frame filenames: `max(existing_moment_frame_idx for this roll) + 1`.
3. Extract frames via `extract_frames_at_timestamps(video, timestamps, frames_dir, start_index)`.
4. Insert section row (narrative, coach_tip, analysed_at all NULL).
5. Insert moment rows with `section_id` set.
6. Yield `{stage: "section_started", section_id, start_s, end_s, idx: i, total: N}`.
7. Build multi-image prompt. Call `await run_claude(prompt, settings, limiter)`.
8. Parse response via `parse_section_response`. On error: yield `{stage: "section_error", section_id, error: "<str>"}`, leave narrative NULL, continue.
9. On success: `update_section_analysis(conn, section_id, narrative, coach_tip, now)`. Yield `{stage: "section_done", section_id, start_s, end_s, narrative, coach_tip}`.
10. After loop: yield `{stage: "done", total: N}`.

**Append semantics (pivot from M9):**

The DELETEs at the start of run_section_analysis (DELETE FROM sections / moments WHERE roll_id) are **removed**. New sections are appended. Existing analysed sections' narratives are preserved. The M9 regression test that asserted re-run replaces prior state is retired in favour of a new test asserting append preserves prior sections.

Frame filenames use a running index computed from existing moment frame_idx values so uniqueness holds.

### Endpoint `POST /api/rolls/:id/analyse`

Same URL, same request body shape. The `sample_interval_s` field is now optional and ignored by the backend (validation accepts it for transition-period frontend compatibility; the derived 1 fps cap 8 is always used).

Streaming response events gain the new per-section shape:
- `{stage: "section_started", section_id, start_s, end_s, idx, total}`
- `{stage: "section_queued", section_id, retry_after_s}` — emitted when the sliding-window rate limiter blocks the next Claude call.
- `{stage: "section_done", section_id, start_s, end_s, narrative, coach_tip}`
- `{stage: "section_error", section_id, error}`
- `{stage: "done", total}`

The old `{stage: "frames", pct}` event is removed (frame extraction is internal to each section's work now). Frontend updates accordingly.

**Rate-limit queue surfacing.** When `run_claude` raises `RateLimitedError` for a section's call, the pipeline emits `{stage: "section_queued", section_id, retry_after_s}`, sleeps for `retry_after_s`, and retries the same section. Max 3 retries per section; after the third, emit `section_error` with a rate-limit-specific message and move on. Frontend renders `"Queued — Claude cooldown, retrying in Xs…"` in the progress strip until the next `section_started` event for that ID arrives.

### Finalise (M6a) rewrite

**`server/analysis/summarise.py`:**
- `build_summary_prompt` is rewritten to take sections + annotations_by_section:
  ```
  Section 1 (0:03 – 0:07):
    Narrative: Player A starts in open guard, breaks opponent's posture, climbs legs for triangle setup.
    Coach tip: Stay tight on the climb — avoid giving up the angle.
    Player A's notes:
      - (2026-04-22 13:45) Triangle was there but I shot my hips up too early.
  
  Section 2 (0:15 – 0:22): ...
  ```
- `parse_summary_response` — `valid_moment_ids` parameter renames to `valid_section_ids`. Each `key_moments[*]` entry validates against section IDs.
- `compute_distribution` — deleted. No per-frame position data to aggregate.

**Schema of the stored `scores_json` changes:** `key_moments[*].moment_id` → `key_moments[*].section_id`. The JSON field at the top level stays named `key_moments` (semantic — "notable moments in the roll"); only the inner ID field renames.

### Vault writer changes

**`server/analysis/vault_writer.py`:**
- `_SUMMARY_SECTION_ORDER` drops `position_distribution`. New order: `summary, scores, key_moments, top_improvements, strengths, report` (where `report` is the M6b-added section).
- `render_summary_sections` — delete `render_position_distribution_body` call. `render_key_moments_body` rewrites to resolve each entry's `section_id` → section's `start_s` for the displayed time (`### 0:03`) and use section's `end_s` for the range (`### 0:03 – 0:07`). Body text stays as Claude's note.
- `render_your_notes` — group annotation rows by their section's start_s/end_s range instead of moment timestamp. Header becomes `### 0:03 – 0:07` (range) instead of `### 0:03` (point).

### API changes (other endpoints)

**`GET /api/rolls/:id` (`server/api/rolls.py`):**
- `RollDetailOut.moments` still exists, still populated from the moments table for backward compatibility. Frontend stops rendering it but the field remains in the response shape.
- `RollDetailOut.sections[*]` gains `narrative: str | None`, `coach_tip: str | None`, `analysed_at: int | None`, and `annotations: list[AnnotationOut]`.
- `RollDetailOut.distribution` stays as `dict | None = None` — always None post-M9b.

**`POST /api/rolls/:id/summarise` (`server/api/summarise.py`):**
- Loads sections + annotations-by-section instead of moments + analyses-by-moment + annotations-by-moment. Passes to the new `build_summary_prompt`.
- No endpoint-shape change.

**`POST /api/sections/:id/annotate` or similar — NEW:**
Actually, reuse the existing `POST /api/annotations` with body `{section_id, body}` instead of `{moment_id, body}`. Field rename only, no new route.

**`DELETE /api/sections/:id` — NEW:**
Cascades to moments + annotations + frame files on disk via `delete_section_and_moments(conn, section_id, frames_dir)`.

### PDF export (M6b) impact

`server/export/pdf.py::build_report_context`:
- Key moments resolution switches from `moment_by_id[mid]['timestamp_s']` → `section_by_id[sid]['start_s']`.
- Position Flow bar rendering becomes conditional on `distribution_bar`. The template currently always renders `<section class="distribution">` unconditionally — wrap it in `{% if distribution_bar %}` so it's omitted when the backend passes an empty list (post-M9b always-empty).

### Frontend

**Removed:**
- Chips row for per-moment moments.
- `$lib/components/MomentDetail.svelte` — deleted (functionality migrates to `SectionCard`).
- `$lib/components/GraphCluster.svelte` — kept on disk but unreferenced (both the full `/graph` page AND the mini-graph that rendered inline on the review page).
- Nav link to `/graph` in the app header.
- The mini-graph block on the review page that previously mounted `<GraphCluster>` below `MomentDetail` — gone.

**Modified:**
- `$lib/components/SectionPicker.svelte` — drop the density dropdown from each staged chip (user-facing density is auto); chip now shows `0:03 – 0:07` only.
- `src/routes/review/[id]/+page.svelte` — remove chips row / MomentDetail / GraphCluster references; add a `<SectionCard>` list rendering `roll.sections` with `analysed_at != null`; handler updates for the new SSE event shape.
- `src/routes/+layout.svelte` (or wherever the nav lives) — remove `/graph` link.
- `src/lib/api.ts` — update `AnalyseEvent` discriminated union to the new shape (section_started / section_done / section_error / done).
- `src/lib/types.ts` — `Section` type gains `narrative, coach_tip, analysed_at, annotations`; drop `Moment.section_id` usage in the UI code (still present in type for backward compat).

**New:**
- `$lib/components/SectionCard.svelte` — props: `section`, `busy: boolean`, `onSeek(start_s)`, `onDelete(section_id)`, `onAddAnnotation(section_id, body)`. Body renders: timestamp-range header + seek/delete buttons + narrative paragraph + coach-tip callout + annotations list + add-annotation textarea.
- `web/tests/section-card.test.ts` — ~6 tests covering render states, callbacks, error state.

**Progress-strip banner** (in the existing review-page progress area): when an SSE `section_queued` event arrives for section X, show `"Queued — Claude cooldown, retrying in {retry_after_s}s…"` with a countdown. Clears when `section_started` for the same X arrives, or when `section_error` fires after the third retry.

### Testing

**Backend (new/modified):**
- `tests/backend/test_db_schema_m9b.py` — new schema migration tests (sections columns, annotations rebuild, idempotency).
- `tests/backend/test_db_sections.py` — extended with tests for `update_section_analysis` and for `delete_section_and_moments` removing frame files.
- `tests/backend/test_db_annotations.py` — rewrite for section-based FK; insert/get_by_section/get_by_roll.
- `tests/backend/test_prompt.py` — extended with `build_section_prompt` (N frames, player names substituted, schema hint present).
- `tests/backend/test_summarise.py` — `build_summary_prompt` rewrite; `parse_summary_response` with valid_section_ids; compute_distribution removed.
- `tests/backend/test_pipeline_sections.py` — retire `test_re_running_replaces_prior_sections`; add `test_adding_sections_preserves_prior_sections`, `test_pipeline_assigns_unique_frame_idx_across_runs`, `test_section_error_continues_batch`.
- `tests/backend/test_api_analyse_sections.py` — SSE event shape updated to section_started/section_done/section_error/done.
- `tests/backend/test_api_summarise.py` — fixture shape updated (sections + annotations_by_section).
- `tests/backend/test_vault_writer_summary.py` — retire position_distribution assertions; key_moments resolve by section_id.
- `tests/backend/test_export_pdf.py` / `test_api_export_pdf.py` — section_id in key_moments fixtures.

**Frontend (new/modified):**
- `web/tests/section-card.test.ts` — new.
- `web/tests/section-picker.test.ts` — drop density-dropdown test.
- `web/tests/review-analyse.test.ts` — rewrite: section-card rendering, new SSE event shape, chips-row removed.
- `web/tests/scores-panel.test.ts` — drop position-distribution rendering assertion.
- `web/tests/export-pdf.test.ts` — update fixture key_moments to use section_id.

### Manual smoke

After implementation:

1. Upload a short clip. Mark start 0:03 → Mark end 0:07. Chip shows `0:03 – 0:07`. Mark start 0:15 → Mark end 0:22. Second chip. Click **Analyse ranges**.
2. Progress shows section 1 of 2 analysing, then section 2. Both cards appear below with narrative text and a coach tip.
3. Click "Seek" on card 1 → video jumps to 0:03 and plays.
4. Add an annotation to card 1 → appears as a bullet under the narrative.
5. Mark start 0:30 → Mark end 0:35. Click Analyse ranges again. Card 1 and 2's narratives are preserved; card 3 appears with its own narrative.
6. Click Finalise. ScoresPanel renders with scores + summary + improvements + strengths + key moments (pointing at the section time ranges).
7. Save to Vault. `Roll Log/<date> - <title>.md` contains `## Summary`, `## Scores`, `## Key Moments` (with section ranges), `## Top Improvements`, `## Strengths Observed`, `## Your Notes` (section-grouped), and `## Report` — no `## Position Distribution`.
8. Export PDF. One-page report renders; no Position Flow bar (distribution null); key moments listed with section time ranges.
9. Navigate to `/graph` directly — route still works (code intact), but no nav link from header.

## File structure impact

**New files:**
- `tools/bjj-app/web/src/lib/components/SectionCard.svelte`
- `tools/bjj-app/web/tests/section-card.test.ts`
- `tools/bjj-app/tests/backend/test_db_schema_m9b.py`
- `tools/bjj-app/tests/backend/test_db_annotations.py`

**Modified files (backend):**
- `server/db.py` — schema migration + rebuilt annotations + new `update_section_analysis` helper + extended `delete_section_and_moments`.
- `server/analysis/pipeline.py` — async rewrite, multi-image Claude call per section, append semantics.
- `server/analysis/prompt.py` — new `build_section_prompt` + `parse_section_response`.
- `server/analysis/summarise.py` — `build_summary_prompt` rewrite (sections input); `parse_summary_response` key rename; `compute_distribution` deleted.
- `server/analysis/vault_writer.py` — drop `position_distribution` from section order; `render_key_moments_body` by section_id; `render_your_notes` group by section range.
- `server/api/analyse.py` — async handler, new SSE events, drop sample_interval validation, threads limiter + player names + settings into the pipeline.
- `server/api/summarise.py` — loads sections + annotations_by_section; drops compute_distribution.
- `server/api/rolls.py` — `SectionOut` gains narrative/coach_tip/analysed_at/annotations; distribution always None.
- `server/api/annotations.py` — `{moment_id: …}` → `{section_id: …}` request body.
- `server/api/export_pdf.py` — key_moments resolve by section_id; distribution always None passes through.

**Modified files (frontend):**
- `web/src/lib/api.ts` — AnalyseEvent discriminated union updated to new SSE shape.
- `web/src/lib/types.ts` — `Section` gains narrative/coach_tip/analysed_at/annotations.
- `web/src/routes/review/[id]/+page.svelte` — removes chips row, MomentDetail, GraphCluster, moment-click state; adds SectionCard list; updates SSE handler.
- `web/src/lib/components/SectionPicker.svelte` — drops density dropdown.
- `web/src/routes/+layout.svelte` (or app header) — removes `/graph` nav link.
- `web/src/lib/components/ScoresPanel.svelte` — wraps position-flow-bar render in `{#if distribution}` (so null skips cleanly).

**Deleted files:**
- `web/src/lib/components/MomentDetail.svelte`
- `web/tests/moment-detail.test.ts` (if it exists)

**README:**
- `tools/bjj-app/README.md` — add M9b line below M9, mark M9 as (shipped).

## Dependencies

No new runtime deps. Multi-image Claude call uses the existing `claude` CLI pathway.

## Out of scope (explicitly deferred)

| Deliverable | Why deferred |
|---|---|
| Per-section "Re-analyse" button | Delete + re-mark works for v1. |
| In-place edit of section timestamps after analysis | Section rows are insert-only once `analysed_at` is set. |
| Dedup of overlapping sections | User-visible; they can delete duplicates. |
| Auto-trigger on Mark end | Batch button preserved per brainstorm decision. |
| User-configurable frame density | 1fps capped at 8 is auto-derived. |
| Parallel section analysis | Sequential keeps error isolation simple. |
| Multi-image Claude caching | Hit rate on bespoke ranges ≈ 0%. |
| Structured per-frame position IDs | Revisit post-M11 if eval shows value. |
| Numeric confidence scoring | Dropped entirely. |
| Distribution rollup (vault + PDF) | No structured per-frame data to aggregate. |
| Graph page re-enable | Hidden only. |
| Mobile UX | M7 abandoned. |
| Migration of pre-M9b moment annotations | Clean slate (smoke-test data only). |
| Per-section Claude metadata (model, tokens, latency) | Noise now; nice-to-have for M11 eval harness. |
