# BJJ App M6a — Summary Step — Design

**Date:** 2026-04-21
**Status:** Design approved, implementation plan pending
**Parent spec:** [2026-04-20-bjj-local-review-app-design.md](./2026-04-20-bjj-local-review-app-design.md)
**Prior milestone:** M5 (graph page) merged at `101f3db` on main.
**Follow-on:** M6b (PDF export via WeasyPrint) deferred to a separate spec after M6a ships.

## Context

After M5, the app supports upload → pose pre-pass → per-moment Claude classification → per-moment annotations → explicit "Save to Vault" publish of `## Your Notes` → graph visualisation of the roll's state-space path. The parent spec's next milestone is "Summary step + PDF export" — one final Claude call that turns the collected moment analyses + annotations into a coaching report (scores, summary, improvements, strengths, key moments), plus a printed PDF of that report.

M6a ships the summary step only. The user clicks a "Finalise" button on the review page; Claude runs once across all the analysed moments + the user's annotations; the app persists scores + summary text + improvements + strengths + top-3 key moment pointers to SQLite, and the next "Save to Vault" publish emits those as new sections in the roll's markdown file. M6b (deferred) will add the WeasyPrint PDF template and an "Export PDF" button.

## Goals

1. **One Claude call per finalise.** Aggregate all moments' prior classifications + the user's notes into a single summary prompt; return scores + summary + improvements + strengths + three key moment pointers.
2. **Locally compute what doesn't need Claude.** Position category distribution and the timeline bar are deterministic from the moment analyses; compute them server-side, not via Claude.
3. **Vault-first publishing.** Finalise writes SQLite only. Save to Vault (M4) is extended so if the roll is finalised, the markdown file gains `## Summary`, `## Scores`, `## Position Distribution`, `## Key Moments`, `## Top Improvements`, `## Strengths Observed` sections alongside the existing `## Your Notes`.
4. **Per-section hash-based conflict detection.** If the user hand-edits any summary section in Obsidian, the next Save to Vault fires the existing M4 `PublishConflictDialog`. Section-level granularity prevents false conflicts from unrelated section edits.
5. **Show finalised output prominently.** A `ScoresPanel` component renders between the chips row and `MomentDetail` whenever the roll is finalised. Three score boxes, the summary sentence, numbered improvements, bullet strengths, clickable key-moment pointers that seek the video and select the referenced moment.

## Non-goals (explicit)

- **No PDF export.** M6b handles WeasyPrint + "Export PDF" button. This spec is summary-only.
- **No re-finalise confirmation dialog.** Clicking "Re-finalise" one-clicks through; the label change + `finalised_at` timestamp are enough user signal.
- **No auto-finalise.** The user must click Finalise explicitly. The endpoint is never triggered automatically (e.g. after the nth analyse).
- **No section versioning in SQLite.** `scores_json` holds the current state; re-finalise overwrites. Previous scores are not retained.
- **No user-picked key moments.** Claude decides which three are "key". The UI has no "pin this moment as key" affordance.
- **No tunable score rubric.** Scores are Claude's judgment. No UI control over what counts as "8/10 retention".
- **No multi-player scoring.** Only Player A (the person being coached) gets graded. Player B is context, not subject.

## Design decisions (captured from brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Milestone split | M6a summary, M6b PDF | Summary delivers standalone value (Obsidian markdown); PDF is meaningful extra work worth its own plan. |
| Output split | Claude for language; local compute for counts/timeline | Claude gets arithmetic wrong; distribution + timeline are deterministic. |
| Key moment selection | Claude picks 3 by `moment_id`; server validates | "Turning point" is a judgment call where Claude adds value over aggregates. |
| Annotations in prompt | Included by default | Summary is a natural-language task; user context enriches it. The M3 "no user input in prompt" rule applied only to the classification prompt. |
| Vault write timing | Only via extended Save to Vault | Preserves M4's deferred-publish invariant (one button writes to vault). |
| Conflict handling | Per-section hashing in a new JSON column | Lets users edit unrelated sections in Obsidian without triggering false conflicts. |
| Finalise button placement | Review page footer, above Save to Vault | Logical grouping of "commit" actions. |
| Re-run semantics | Label changes to "Re-finalise"; one-click, no confirm; shows `finalised_at` underneath | A modal for every re-run is friction; label change is enough. |
| Scores display | New `ScoresPanel` between chips and `MomentDetail` | Summary is what users re-read on later sessions — deserves prime real estate. |

## Architecture

One new Claude-calling endpoint, one reused Claude subprocess seam (refactored from M3), one extended vault writer, one new frontend component.

### New single-responsibility backend module: `server/analysis/summarise.py`

Pure helpers, no IO, no subprocess:

```python
def build_summary_prompt(
    roll: dict,
    moments: list[dict],           # each with id, timestamp_s, frame_idx
    analyses_by_moment: dict[str, list[dict]],
    annotations_by_moment: dict[str, list[dict]],
) -> str: ...

def parse_summary_response(
    raw: str,
    valid_moment_ids: set[str],
) -> SummaryPayload: ...

def compute_distribution(
    analyses: list[dict],           # flat list, each with position_id joined to category
    categories: list[dict],          # taxonomy categories (id, label)
) -> Distribution: ...
```

`SummaryPayload` is a `TypedDict` matching the `scores_json` shape. `Distribution` has `{timeline: list[str], counts: dict[str, int], percentages: dict[str, int]}`.

### Refactored single seam: `server/analysis/claude_cli.py`

Extract `run_claude(prompt: str, settings: Settings) -> str` from the existing `analyse_frame`. Returns the raw assistant text; caller parses. Reuses:
- `asyncio.create_subprocess_exec` with argv (no shell).
- `stream-json` stdout parsing.
- One retry on non-zero exit.
- Shared `SlidingWindowLimiter` — each `run_claude` call is one token against the 10/5-min budget (applies to both per-frame analyses AND summary calls).

`analyse_frame` refactors to use `run_claude` internally. The security invariants (argv only, no shell) carry forward unchanged.

### Extended `vault_writer.publish`

Generalised from "splice `## Your Notes`" to "splice each owned section".

- New internal function `render_summary_sections(scores_json, distribution, categories) -> dict[section_id, body]` maps each of the six summary section ids (`summary`, `scores`, `position_distribution`, `key_moments`, `top_improvements`, `strengths`) to a rendered markdown body string.
- The publish flow now:
  1. Renders Your Notes body (existing M4 logic).
  2. If `rolls.scores_json` is set: renders the six summary sections.
  3. For each owned section: locate in the file, hash current body, compare to stored hash, raise `ConflictError` on mismatch (unless `force=True`).
  4. Splice each section body into the file in the correct order (see vault markdown layout below).
  5. On success: atomic write + update `rolls.vault_your_notes_hash` AND `rolls.vault_summary_hashes` (new JSON column: `{section_id: sha256_hex}`).

A non-finalised roll (no `scores_json`) still publishes — just `## Your Notes` as before.

### Security note

The summary prompt includes user-controlled annotation text verbatim. This diverges from the M3 classification prompt's "no user input" invariant. Acceptable because:
- The summary endpoint is not cached (prompt hash isn't reused across users).
- Claude's output is schema-validated and used only to populate SQLite + vault markdown — no downstream command execution from the response.
- The `run_claude` subprocess still spawns with argv-only, `--max-turns 1`, `stderr=DEVNULL`, and is rate-limited.

The M3 subprocess audit doc will get a one-line addendum noting that `run_claude` is a second call-site with a different prompt-construction invariant (summary-specific).

## Data model

### SQLite migration (idempotent, same pattern as M4/M5)

```sql
-- Already exist from M1 (unused until now):
--   rolls.scores_json TEXT
--   rolls.finalised_at INTEGER
-- New in M6a:
ALTER TABLE rolls ADD COLUMN vault_summary_hashes TEXT;
```

`vault_summary_hashes` stores a JSON dict like:
```json
{
  "summary": "a3f8b2c1...",
  "scores": "b2e7d9a4...",
  "position_distribution": "c4f1a8e2...",
  "key_moments": "d5e2b7f3...",
  "top_improvements": "e6f3c8d4...",
  "strengths": "f7d4e9a5..."
}
```

One sha256 hex digest per summary-owned section, captured on every successful publish. Used to detect external edits on subsequent publishes.

### `scores_json` payload shape

```json
{
  "summary": "You held closed guard well for 2 minutes but were swept when you over-committed on a hip-bump.",
  "scores": {
    "guard_retention": 8,
    "positional_awareness": 6,
    "transition_quality": 7
  },
  "top_improvements": [
    "Keep your elbows connected to your ribs when your posture is broken.",
    "When you shoot a hip-bump, trap the far arm first.",
    "Recognise when you're in half-guard bottom and don't waste energy on sweeps from there."
  ],
  "strengths": [
    "Strong closed-guard breakdown",
    "Patient with your grips"
  ],
  "key_moments": [
    {"moment_id": "abc...", "note": "Perfect timing on the triangle setup"},
    {"moment_id": "def...", "note": "This is where the sweep got reversed"},
    {"moment_id": "ghi...", "note": "Good recovery to half guard"}
  ]
}
```

### Distribution (not persisted, recomputed on read)

```json
{
  "timeline": ["standing", "guard_bottom", "guard_bottom", "scramble", ...],
  "counts": {"standing": 2, "guard_bottom": 7, "scramble": 4},
  "percentages": {"standing": 15, "guard_bottom": 54, "scramble": 31}
}
```

## API surface

All under `/api`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/rolls/:id/summarise` | Run the summary Claude call + persist. Returns parsed payload + distribution. |
| POST | `/rolls/:id/publish` | (extended) Now emits summary sections if the roll is finalised. |
| GET | `/rolls/:id` | (extended) Response gains `finalised_at`, `scores` (parsed `scores_json`), `distribution`. |

### `POST /api/rolls/:id/summarise`

Request body: `{}`. No params.

Responses:
- **200 OK** — body:
  ```json
  {
    "finalised_at": 1714579500,
    "scores": { /* the full scores_json payload */ },
    "distribution": { /* {timeline, counts, percentages} */ }
  }
  ```
- **400 Bad Request** — roll has no analyses yet. Body: `{"detail": "Roll has no analyses — analyse at least one moment before finalising."}`
- **404 Not Found** — unknown roll.
- **429 Too Many Requests** — rate-limiter rejected (reuses M3's limiter). Body: `{"detail": "Claude cooldown — Ns until next call", "retry_after_s": N}`. Header: `Retry-After: N`.
- **502 Bad Gateway** — Claude returned malformed output after retry. Body: `{"detail": "Claude gave malformed output"}`.

### Claude summary prompt (built by `build_summary_prompt`)

```
You are a BJJ coach reviewing a roll. Analyse the sequence below and produce
a concise coaching report. The practitioner is {player_a_name} (the person
being coached); {player_b_name} is their partner.

Roll metadata:
- Duration: {duration_mm_ss}
- Date: {date}
- Total moments analysed: {n_moments}

Per-moment analyses (chronological):
- {mm:ss} moment_id={id} — {player_a_name}: {position_a} ({conf_a*100}%); {player_b_name}: {position_b}.
  {description}
  Coach tip: {coach_tip}
- ...

User's own notes on specific moments:
- {mm:ss} moment_id={id}: "{annotation_body}"
- ...
(omit the entire "User's own notes" block when there are zero annotations)

Output ONE JSON object with this exact shape — no prose, no markdown fences:
{
  "summary": "<one-sentence summary>",
  "scores": {
    "guard_retention": <integer 0..10>,
    "positional_awareness": <integer 0..10>,
    "transition_quality": <integer 0..10>
  },
  "top_improvements": ["<sentence>", "<sentence>", "<sentence>"],
  "strengths": ["<short phrase>", ...],    // 2-4 items
  "key_moments": [                         // exactly 3 items
    {"moment_id": "<from the list above>", "note": "<brief pointer sentence>"},
    {"moment_id": "<...>", "note": "<...>"},
    {"moment_id": "<...>", "note": "<...>"}
  ]
}
```

### Server-side validation of Claude output

- JSON parses.
- Top-level keys present: `summary`, `scores`, `top_improvements`, `strengths`, `key_moments`.
- `scores` has all three metrics; each is an int in `[0, 10]` (clamped if Claude overshoots).
- `top_improvements` is a list of 3 non-empty strings (not more, not fewer; `ClaudeResponseError` otherwise).
- `strengths` is a list of 2–4 non-empty strings.
- `key_moments` is a list of exactly 3 objects; each has `moment_id` (string, present in the roll's moments) and `note` (non-empty string); all three `moment_id`s are distinct.

Validation failure → raise `ClaudeResponseError`. The endpoint translates to HTTP 502.

## Flows

### Flow A — Finalise

```
1. User clicks "Finalise" (or "Re-finalise") in the review page footer.
2. Frontend: POST /api/rolls/:id/summarise
3. Backend (api/summarise.py):
   a. Load roll row. 404 if missing.
   b. Load moment_rows + analyses_by_moment + annotations_by_moment.
   c. If every moment has zero analyses → 400.
   d. build_summary_prompt(roll, moments, analyses_by_moment, annotations_by_moment) → str
   e. run_claude(prompt, settings) → raw assistant text. (Rate-limiter token acquired inside.
      Raises RateLimitedError → translate to 429; raises ClaudeProcessError → 502.)
   f. parse_summary_response(raw, valid_moment_ids) → SummaryPayload.
      Raises ClaudeResponseError → 502.
   g. Persist: UPDATE rolls SET scores_json=?, finalised_at=? WHERE id=?
   h. Compute distribution from analyses + taxonomy.
   i. Return 200 with {finalised_at, scores, distribution}.
4. Frontend:
   - 200 → update roll.scores, roll.distribution, roll.finalised_at reactively.
           ScoresPanel renders. Finalise button relabels to "Re-finalise".
           Subtitle: "Finalised <local-formatted timestamp>".
   - 429 → toast "Claude cooldown — Ns until next call". Button re-enables after N.
   - 502 → toast "Claude gave malformed output — try again". Button re-enables immediately.
   - 400 → toast "Analyse at least one moment before finalising." Button stays disabled.
```

### Flow B — Publish (extended)

```
1. User clicks "Save to Vault" (existing M4 button).
2. Frontend: POST /api/rolls/:id/publish {force?: boolean}
3. Backend (vault_writer.publish, extended):
   a. Load roll row, annotations, analyses (with moment joins).
   b. Build body for each owned section:
        - Your Notes: render_your_notes(annotations) (existing M4).
        - If roll.scores_json is set, also:
            Summary, Scores, Position Distribution, Key Moments,
            Top Improvements, Strengths Observed
            via render_summary_sections(scores_json, distribution, categories).
   c. Decide target path: existing vault_path if set, else slugify_filename.
   d. If file exists:
        For each owned section that should be present:
          existing_body = extract_section(current_text, section_heading)
          current_hash = sha256(existing_body.strip())
          stored_hash = (rolls.vault_your_notes_hash if section == "your_notes"
                         else rolls.vault_summary_hashes[section])
          if stored_hash is not None and current_hash != stored_hash and not force:
            raise ConflictError(...)
      Splice each section in place.
      Else: build fresh skeleton with all owned sections + Your Notes.
   e. Atomic write (.tmp + os.replace).
   f. Update rolls.vault_path, vault_published_at, vault_your_notes_hash,
      vault_summary_hashes (JSON dict of all 6 section hashes or NULL if not finalised).
4. Frontend: 200 toast; 409 conflict dialog.
```

### Flow C — Re-finalise after more annotations

```
1. User adds more annotations to a finalised roll.
2. User clicks "Re-finalise".
3. Same as Flow A, but the existing scores_json + finalised_at are overwritten.
4. Scores panel updates reactively.
5. Save to Vault on next click: the summary sections will be re-emitted with
   the updated scores. If the user had hand-edited any section in Obsidian
   since the last publish, the conflict dialog fires.
```

## Vault markdown layout (finalised + published roll)

```markdown
---
date: 2026-04-21
partner:
duration: "3:45"
tags: [roll]
roll_id: 42a7f1b89c6e4...
---

# <roll title>

## Summary

You held closed guard well for 2 min but were swept when you over-committed on a hip-bump.

## Scores

| Metric                 | Score |
|------------------------|-------|
| Guard Retention        | 8/10  |
| Positional Awareness   | 6/10  |
| Transition Quality     | 7/10  |

## Position Distribution

| Category        | Count | %   |
|-----------------|-------|-----|
| Standing        | 2     | 15% |
| Guard (Bottom)  | 7     | 54% |
| Scramble        | 4     | 31% |

### Position Timeline Bar

⬜⬜🟦🟦🟦🟦🟦🟦🟦🟪🟪🟪🟪

Legend: ⬜Standing 🟦Guard(Bottom) 🟨Guard(Top) 🟩Dominant(Top) 🟥Inferior(Bottom) 🟫LegEnt 🟪Scramble

## Key Moments

- **1:23** — Perfect timing on the triangle setup.
- **2:45** — Where the sweep got reversed.
- **3:10** — Good recovery to half guard.

## Top Improvements

1. Keep elbows connected when posture is broken.
2. When you shoot a hip-bump, trap the far arm first.
3. Recognise when you're in half-guard bottom and don't waste energy on sweeps from there.

## Strengths Observed

- Strong closed-guard breakdown
- Patient with grips

## Your Notes

### 1:23
- _(2026-04-21 10:15)_ I was flat here; should've framed earlier.
```

Ordering is fixed: Summary → Scores → Position Distribution (with H3 Timeline Bar) → Key Moments → Top Improvements → Strengths Observed → Your Notes. Any section the user inserts in Obsidian outside this set (e.g. `## Extra thoughts`) is preserved verbatim by the splice logic.

### Category → emoji mapping

```python
CATEGORY_EMOJI = {
    "standing":          "⬜",
    "guard_bottom":      "🟦",
    "guard_top":         "🟨",
    "dominant_top":      "🟩",
    "inferior_bottom":   "🟥",
    "leg_entanglement":  "🟫",
    "scramble":          "🟪",
}
```

Hardcoded in `summarise.py`. The legend line in the `Position Distribution` section is generated from this dict.

## UI layout

### Review page — updated

```
Header: title, date, partner, Analyse button           (existing)
Video player                                            (existing)
Progress indicator                                      (existing)
Moments chip row                                        (existing)
┌─ NEW: ScoresPanel (only when finalised) ───────────────────────────┐
│  [8/10 Retention] [6/10 Awareness] [7/10 Transition]              │
│                                                                     │
│  "You held closed guard well for 2 min but were swept."            │
│                                                                     │
│  Top improvements:                                                  │
│   1. Keep elbows connected when posture is broken.                  │
│   2. …                                                              │
│   3. …                                                              │
│                                                                     │
│  Strengths observed: Strong closed-guard breakdown · Patient grips  │
│                                                                     │
│  Key moments:                                                       │
│   • 1:23 — Perfect timing on the triangle setup      [go to →]     │
│   • 2:45 — Where the sweep got reversed              [go to →]     │
│   • 3:10 — Good recovery to half guard               [go to →]     │
└───────────────────────────────────────────────────────────────────┘
MomentDetail (when moment selected)                     (existing)
Mini graph (when moment selected)                       (existing, M5)

── NEW: Finalise control ──
[Finalise]    Not yet finalised.
  or
[Re-finalise]    Finalised Apr 21 10:15.

── Existing footer ──
Vault: <path>   [Save to Vault]

PublishConflictDialog (existing, M4)
```

**ScoresPanel rules:**
- Renders only when `roll.scores !== null && roll.finalised_at !== null`.
- Score boxes: green (≥8), amber (5–7), rose (≤4). `/10` denominator prominent.
- "Go to" button reuses the existing `onChipClick(moment)` handler on the review page, which seeks the video and selects the moment (scrolls MomentDetail into view).
- No collapse/expand toggle — always visible when present.

**Finalise button rules:**
- Disabled if `roll.moments.every(m => m.analyses.length === 0)`. Tooltip on hover: "Analyse at least one moment first."
- Label: `"Finalise"` when `finalised_at === null`, else `"Re-finalise"` + subtitle `"Finalised <local-formatted>"`.
- On click: disabled + "Finalising…" label during the fetch. On 200: reactive UI update. On 429/502: toast + button re-enables.
- Footer placement: above the existing Save-to-Vault row, visually separated by a hairline.

## File layout

```
tools/bjj-app/
├── server/
│   ├── analysis/
│   │   ├── summarise.py              # NEW
│   │   ├── claude_cli.py             # MODIFY: extract run_claude()
│   │   └── vault_writer.py           # MODIFY: render_summary_sections + per-section splice
│   ├── api/
│   │   ├── summarise.py              # NEW: POST /api/rolls/:id/summarise
│   │   ├── publish.py                # MODIFY: pass summary sections into publish() call path
│   │   └── rolls.py                  # MODIFY: RollDetailOut gains finalised_at + scores + distribution
│   ├── db.py                         # MODIFY: migrate vault_summary_hashes; set_summary_state helper
│   └── main.py                       # MODIFY: register summarise_api.router
├── tests/backend/
│   ├── test_summarise.py             # NEW
│   ├── test_api_summarise.py         # NEW
│   ├── test_vault_writer_summary.py  # NEW
│   ├── test_api_publish.py           # MODIFY
│   └── test_db_schema_migration.py   # MODIFY
└── web/
    ├── src/
    │   ├── lib/
    │   │   ├── api.ts                # MODIFY: summariseRoll()
    │   │   ├── types.ts              # MODIFY: Scores, KeyMoment, Distribution, RollDetail gains scores/distribution/finalised_at
    │   │   └── components/
    │   │       └── ScoresPanel.svelte            # NEW
    │   └── routes/
    │       └── review/[id]/+page.svelte          # MODIFY: mount ScoresPanel + Finalise button
    └── tests/
        ├── scores-panel.test.ts                  # NEW
        └── review-analyse.test.ts                # MODIFY: add Finalise + scores panel tests
```

## Testing strategy

### Backend (pytest)

- **`test_summarise.py`** — Pure helpers in isolation. `build_summary_prompt` (includes moments, includes annotations when present, omits annotations block cleanly when empty, uses player names not hardcoded). `parse_summary_response` (accepts well-formed, rejects missing keys, rejects bad scores (clamped), rejects hallucinated moment_ids, rejects duplicate moment_ids in key_moments, rejects key_moments length != 3). `compute_distribution` (counts per category, percentages sum to 100, timeline emoji mapping correct).
- **`test_api_summarise.py`** — Endpoint contract. 200 happy path (mock `run_claude` to return valid JSON string). 400 on no analyses. 404 on unknown roll. 429 via forced limiter exhaustion. 502 on malformed output. Verify `scores_json` + `finalised_at` persisted after 200. Re-finalise overwrites previous state.
- **`test_vault_writer_summary.py`** — `render_summary_sections` emits each section in the right shape (golden-string spot checks). First publish of a finalised roll creates file with all 6 sections + `## Your Notes` in correct order. Re-publish preserves user-inserted sections (`## Extra thoughts`) and splices only owned sections. Hand-edit to `## Summary` raises `ConflictError`; `force=True` overrides. Unrelated section edit does not conflict.
- **`test_api_publish.py`** (existing, extend) — Publish on a finalised roll produces all 6 summary sections. Publish on an unfinalised roll still produces just `## Your Notes` (regression test).
- **`test_db_schema_migration.py`** (existing, extend) — Fresh DB has `vault_summary_hashes` column. Pre-M6a DB gains the column on next `init_db` call. Idempotent.

### Frontend (Vitest + Svelte Testing Library)

- **`scores-panel.test.ts`** — Renders score boxes with correct color bucketing. Renders numbered improvements. Renders bulleted strengths. Renders key moments with "go to" buttons that invoke the callback with the correct `moment_id`. Doesn't render when `scores` is null.
- **`review-analyse.test.ts`** (existing, extend) — Finalise button disabled when no analyses exist. Click Finalise → POST `/summarise` → ScoresPanel appears. Button relabels to "Re-finalise". `finalised_at` timestamp renders. 429 response surfaces a cooldown toast. 502 response surfaces an error toast.

### Manual smoke (M6a completion gate)

1. Upload roll, analyse 3+ moments, type 2+ annotations.
2. Click **Finalise** → "Finalising…" → scores panel appears with scores, summary, improvements, strengths, 3 key moments. Button → "Re-finalise" + timestamp.
3. Click a key moment's "go to" → video seeks, chip selected, MomentDetail shows for that moment.
4. Click **Save to Vault** → toast success.
5. Open the markdown file in Obsidian → all 6 summary sections present in the right order, `## Your Notes` at bottom.
6. Add a new annotation in the app. Click **Re-finalise**. Scores panel updates.
7. Click **Save to Vault** → success; Obsidian file's `## Your Notes` now includes the new note; summary sections re-emit with any adjusted content.
8. In Obsidian, edit a word in `## Summary`. Save. Back in the app, click **Save to Vault** → conflict dialog fires. Click Overwrite → toast success; Obsidian edit replaced.
9. Regression: a fresh unfinalised roll can Save to Vault and ends with just `## Your Notes`.

## Dependencies

No new third-party dependencies. All Python stdlib + `python-frontmatter` (already present). No npm additions.

## Out of scope (explicitly deferred)

| Deliverable | Why deferred |
|---|---|
| WeasyPrint + `POST /export/pdf` + HTML template | M6b — separate plan. |
| Re-finalise confirmation dialog | Re-run is one click with clear label; Claude call is recoverable (one extra budget token if misclicked). |
| User-picked key moments (pin a moment as "important") | Would add per-moment state to M4's annotations model. Revisit if Claude's picks frequently miss. |
| Per-session score history / versioning | `scores_json` overwrites. A future extension could stash each run in `analyses`-like table if useful. |
| Tunable score rubric | The scoring metrics are fixed (Retention, Awareness, Transition). Adding user-configurable weights is out of scope. |
| Auto-finalise on Nth analyse | Finalise is always an explicit user action. |
| Summary in languages other than English | Claude follows its default English output. |

## Completion criteria

1. `pytest tests/backend -v` all green, including ~15 new M6a tests.
2. `npm test` all green, including ~4 new `scores-panel.test.ts` + 4 review-analyse extensions.
3. Manual smoke (9 steps above) passes.
4. No M1–M5 tests regress.
5. The `run_claude` refactor preserves all M3 behaviour — `analyse_frame` tests still pass unchanged.
6. The M3 `--dangerously-skip-permissions` security audit gains a one-line addendum noting the second call-site (`run_claude`) is used for the summary prompt, and the invariant "no user input in the classification prompt" is explicitly relaxed for the summary prompt (with the mitigations enumerated in the Architecture section).
