# BJJ App M4 — Annotations + Vault Write-back — Design

**Date:** 2026-04-21
**Status:** Design approved, implementation plan pending
**Parent spec:** [2026-04-20-bjj-local-review-app-design.md](./2026-04-20-bjj-local-review-app-design.md)
**Prior milestone:** M3 (Claude CLI adapter) merged at `37ecd9b` on main.

## Context

M3 gave us working Claude Opus 4.7 classification of individual moments, with results streamed into the review page and cached to SQLite. What M3 didn't do: write anything into the Obsidian vault. The `Roll Log/*.md` files listed on the home page are still only the legacy markdown that predates the app — uploaded rolls have no vault presence.

M4 closes that gap for user annotations specifically. The user can type notes in the selected-moment panel, persist them to SQLite as they work, and explicitly publish the roll + all current annotations to a vault markdown file when they click "Save to Vault". The vault file becomes the long-term store; SQLite is the working draft.

The "vault-first principle" from the parent spec is partially realised here (annotations round-trip to the vault) and will be completed in M6 when the summary step populates the scores, key-moment list, and improvements sections.

## Goals

1. **Capture per-moment notes** as the user reviews. Typing and saving a note is cheap and always succeeds against SQLite.
2. **One explicit publish action** — "Save to Vault" — renders SQLite → markdown and writes atomically.
3. **Hash-based conflict detection on `## Your Notes` only.** If the user has hand-edited that section in Obsidian since the last publish, surface a dialog rather than silently clobbering the external edit. Edits to other sections are preserved automatically because M4 only rewrites `## Your Notes`.
4. **Make uploaded rolls discoverable on the home page** once published. Home tiles with a `roll_id` link to `/review/<uuid>`; legacy vault-only tiles render non-clickable.

## Non-goals (explicit)

- **M4 does not write analyses to the vault.** Position classifications, descriptions, and coach tips stay in SQLite. A later milestone (M6 alongside the summary step) will serialise them into the roll markdown.
- **No edit or delete of annotations in M4.** The model is append-only: you add a new note, old notes stay. If you want to correct a prior note, add a new note saying so. Edit/delete can come later via new HTTP verbs on a future `.../annotations/:annotation_id` path — M4 doesn't reserve them.
- **No auto-save on every keystroke.** The user clicks "Add note" (or Cmd-Enter) to send an annotation. No debounce, no implicit save.
- **No three-way merge on conflict.** The 409 dialog offers Overwrite or Cancel; no in-app diff viewer. Users with mission-critical Obsidian edits can use git to recover (`git checkout HEAD~1 -- "Roll Log/..."`).
- **No retrofit of legacy vault rolls.** Pre-M2a markdown files in `Roll Log/` stay visible on the home page but unclickable — they have no SQLite backing. Creating SQLite rows for them is out of scope.
- **Upload flow unchanged.** `POST /rolls` does not create a vault markdown; that only happens on first publish.

## Design decisions (captured from brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| What M4 writes to vault | Annotations only | Keeps the milestone focused; analyses serialisation moves with the summary step in M6. |
| When vault file is created | On first "Save to Vault" click | Matches the explicit publish model from the parent spec. |
| Publish model | Deferred — SQLite-only until button click | One hash-check per publish, not per keystroke. Clean draft/publish split. |
| Annotation cardinality | Multiple per moment, append-only | Treats notes as a review journal that accumulates over time. |
| `## Your Notes` layout | H3 per moment, bullets within each | Moments become foldable threads in Obsidian. |
| Conflict handling scope | Only on `## Your Notes` section | Other sections can change freely in Obsidian without triggering a conflict. |
| Conflict UX | Terse dialog, no preview | Single-user app; git is the undo mechanism. |
| Filename scheme | `YYYY-MM-DD - <title>.md` with collision suffix | Matches existing Roll Log convention. |
| markdown → SQLite linking | `roll_id` field in frontmatter | Home page resolves this to a `/review/<uuid>` link. |

## Architecture

Annotations live in SQLite as the working store. A single publish endpoint reconciles SQLite state into the vault markdown file for the roll. Annotation writes and publish writes are separate code paths — the annotation endpoint cannot accidentally touch the vault.

### New single-responsibility module: `server/analysis/vault_writer.py`

The **sole** module that writes to `Roll Log/*.md`. Existing `vault.py` stays read-only (one new return field on `RollSummary`, nothing else).

Exported surface:

```python
@dataclass(frozen=True)
class PublishResult:
    vault_path: Path           # path relative to vault_root
    your_notes_hash: str       # sha256 of the new Your Notes section body
    vault_published_at: int    # unix seconds when this publish completed

class ConflictError(Exception):
    """Hash mismatch on Your Notes section during re-publish."""
    current_hash: str
    stored_hash: str

def publish(
    conn: sqlite3.Connection,
    *,
    roll_id: str,
    vault_root: Path,
    force: bool = False,
) -> PublishResult: ...

def render_your_notes(rows: list[sqlite3.Row]) -> str:
    """Pure. Takes annotation rows (with moment's timestamp_s joined in) and
    returns the body of the `## Your Notes` section (H3 per moment, bullets
    per note in chronological order)."""

def slugify_filename(title: str, date: str, vault_root: Path) -> Path:
    """Pure. Generates a collision-safe `YYYY-MM-DD - <title>.md` path under
    `vault_root/Roll Log/`. Resolves collisions by appending ` (2)`, ` (3)`."""
```

### Security boundary

The vault writer is the first M4 code path that writes to files outside the app's own data directory. `slugify_filename` must produce paths that resolve inside `vault_root/Roll Log/` — no `..`, no absolute paths, no symlink traversal. Enforced by a `path.resolve().relative_to(vault_root / "Roll Log")` check (same pattern as the M3 Claude CLI adapter's project-root check).

## Data model

### SQLite — rolls table gains three columns

```sql
ALTER TABLE rolls ADD COLUMN vault_path TEXT;                -- NULL until first publish
ALTER TABLE rolls ADD COLUMN vault_your_notes_hash TEXT;     -- NULL until first publish
ALTER TABLE rolls ADD COLUMN vault_published_at INTEGER;     -- unix seconds; NULL until first publish
```

SQLite lacks `ADD COLUMN IF NOT EXISTS`. `init_db` inspects `PRAGMA table_info(rolls)` and conditionally runs each `ALTER` statement. The change is backwards-compatible — existing rolls get NULLs.

`vault_published_at` is the unix timestamp of the most recent successful publish. The frontend uses it to decide whether to show the "unsaved to vault" marker: show it if `vault_published_at` is NULL, or if any annotation on the roll has `created_at > vault_published_at`.

### SQLite — annotations table (unchanged)

Reused as-is from the M1 schema:

```sql
CREATE TABLE annotations (
  id         TEXT PRIMARY KEY,                      -- uuid4 hex
  moment_id  TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  body       TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL                       -- unused in M4 (append-only)
);
```

No unique constraint on `moment_id` — multiple annotations per moment is deliberate.

### Vault markdown format on first publish

```markdown
---
date: 2026-04-21
partner: Anthony
duration: "3:45"
tags: [roll]
roll_id: 42a7f1b89c6e4abc8d01234567890abc
---

# <roll title>

## Your Notes

### 1:23
- _(2026-04-21 10:15)_ I was flat here; should've framed earlier.

### 2:45
- _(2026-04-21 10:17)_ Good sweep, grip was loose.
```

- `date`, `partner`, `duration`, `tags` mirror the existing Roll Log template.
- `duration` is pulled from `rolls.duration_s`, rendered as `mm:ss` (quoted so YAML doesn't parse it as a number).
- `roll_id` is the SQLite uuid — the new round-trip field.
- H3 per moment, sorted by the moment's `timestamp_s` ascending.
- Bullets under each H3, sorted by `created_at` ascending. Each bullet renders `_(YYYY-MM-DD HH:MM)_` then the note body. Multi-paragraph notes indent their continuation lines to stay inside the bullet.

### `## Your Notes` hash

Hash scope: the text between the `## Your Notes` heading line (exclusive) and the next `^## ` heading (exclusive) or EOF. Leading/trailing whitespace on that slice is stripped before hashing so whitespace-only diffs in Obsidian don't trigger false conflicts. sha256 hex digest.

## API surface

All under `/api`.

| Method | Path | Purpose |
|---|---|---|
| PATCH | `/rolls/:id/moments/:moment_id/annotations` | Append a new annotation. Body `{"body": "..."}`. Returns 201 with `{id, body, created_at}`. |
| POST | `/rolls/:id/publish` | Publish the roll. Body `{"force": bool}` (force defaults to false). Returns 200 `{vault_path, your_notes_hash, vault_published_at}` on success, 409 `{detail, current_hash, stored_hash}` on conflict. |
| GET | `/rolls/:id` | (extended) Each moment now carries `annotations: [{id, body, created_at}]`. Roll carries `vault_path: str | null` and `vault_published_at: int | null`. |
| GET | `/rolls` | (extended) Each summary now carries `roll_id: str | null` (from frontmatter). |

**Why a dedicated `/publish` endpoint rather than a flag on annotation save:** enforces the deferred-publish boundary. The annotation endpoint cannot write to the vault.

**Why PATCH append-only:** reflects the append-only model. Later milestones can add `PUT`/`DELETE` on a sub-path without reshaping M4.

## Flows

### Flow A — Typing and saving an annotation (no vault touch)

```
1. User clicks a chip → moment selected → MomentDetail panel shows prior notes thread + textarea.
2. User types in the textarea.
3. User clicks "Add note" (or Cmd-Enter).
4. Frontend: PATCH /api/rolls/:id/moments/:moment_id/annotations {"body": "..."}
5. Backend: insert_annotation → INSERT row. Returns 201 with new row.
6. Frontend appends the new bullet to the on-page thread. Textarea clears.
7. Vault file untouched.
```

No hash check, no file IO. Trivially fast.

### Flow B — Publishing (with conflict handling)

```
1. User clicks "Save to Vault" in the review page footer.
2. Frontend: POST /api/rolls/:id/publish  { }
3. Backend (vault_writer.publish):
   a. Load roll row + all annotations for the roll, joined with moments.timestamp_s.
      Sorted by timestamp_s, then created_at.
   b. Render the `## Your Notes` body via render_your_notes(rows).
   c. If rolls.vault_path is NULL → first publish:
        - slugify_filename(title, date, vault_root) → collision-safe Path.
        - Build full markdown (frontmatter + `# title` + `## Your Notes\n\n<body>`).
        - Atomic write: write to <path>.tmp then os.replace() → <path>.
        - Compute hash(rendered body), set rolls.vault_path + vault_your_notes_hash.
        - Return PublishResult.
   d. Otherwise → re-publish:
        - Read current file at vault_root / rolls.vault_path.
          - FileNotFoundError (user deleted it in Obsidian) → treat like first publish:
            recreate file at the same path, skip hash check.
        - Locate `## Your Notes` section (heading line → next `^## ` heading or EOF).
          If section absent, treat current body as "".
        - Hash current body, compare to rolls.vault_your_notes_hash.
        - If mismatch AND force is False → raise ConflictError(current, stored).
        - Otherwise: splice new body in place of old section, preserving everything
          outside it. Atomic write. Update stored hash.
        - Return PublishResult.
4. API layer:
   - PublishResult → 200 with JSON body.
   - ConflictError → 409 with {detail, current_hash, stored_hash}.
5. Frontend:
   - 200 → toast "Published to <vault_path>". "Save to Vault" button returns to idle.
   - 409 → modal: "Your Notes was edited in Obsidian since you last published.
     Overwrite? [Overwrite] [Cancel]". Overwrite re-sends with {"force": true}.
     Cancel dismisses the modal, no state change.
```

### Edge cases resolved inline

| Case | Handling |
|---|---|
| First publish: slug collides with an existing vault file not owned by this roll | `slugify_filename` appends ` (2)`, ` (3)` until unique. The roll owns the suffixed file; the pre-existing file is untouched. |
| Re-publish: file was deleted in Obsidian | FileNotFoundError → recreate at the same stored path, skip hash check, treat as a fresh write. |
| `## Your Notes` heading appears twice in the file | Match the first occurrence. Pathological input produces weird splicing but does not crash. |
| Frontmatter is malformed (user edited it in Obsidian) | The `python-frontmatter` library raises on parse. Currently surfaced as an uncaught 500 — acceptable for V1 since malforming frontmatter requires deliberate effort. Revisit if it becomes common. |
| `duration_s` is NULL (upload failed the duration read) | Render `duration: ""` in frontmatter; skip it rather than emit `null`. |
| Multiple concurrent publish requests | SQLite's default behaviour: each transaction serialises. The last one wins. Rare for a single-user app — not worth adding a lock. |

## UI changes

### MomentDetail panel

Below the existing analysis cards + coach tip:

```
Your notes for this moment
---------------------------
• (Apr 21 10:15) I was flat here; should've framed earlier.
• (Apr 21 10:22) Actually — re-watching, the issue was hip position.

[ Text area — type a new note…              ]
[ Add note ]    _unsaved to vault_
```

- Thread above textarea renders existing annotations for this moment in chronological order, newest at bottom.
- Textarea submits on Cmd-Enter or button click. Clears on 201. Reports error inline on failure.
- "unsaved to vault" marker appears when `roll.vault_published_at` is null, or when any annotation on the roll has `created_at > roll.vault_published_at`. After a successful publish, the frontend updates `vault_published_at` locally so the marker disappears immediately.

### Review page footer

One button, replacing the empty footer:

```
[ Save to Vault ]
```

- Normal path: "Publishing…" on click → toast "Published to <vault_path>".
- 409: `PublishConflictDialog` modal — terse text + Overwrite/Cancel.
- Button label is always "Save to Vault" (never "Publish" or "Update") — re-clicks just re-publish.

### Home page

One change: `list_rolls` now returns `roll_id`. The home tile renders an `<a>` with `href={/review/${roll_id}}` when `roll_id` is present, and a muted non-link `<div>` with a ".md only" badge when it's not. Legacy vault-only rolls remain visible, just not actionable.

## File layout

```
tools/bjj-app/
├── server/
│   ├── analysis/
│   │   └── vault_writer.py          # NEW: publish() + render_your_notes() + slugify_filename()
│   ├── api/
│   │   ├── annotations.py           # NEW: PATCH /api/rolls/:id/moments/:moment_id/annotations
│   │   └── publish.py               # NEW: POST /api/rolls/:id/publish
│   ├── db.py                        # MODIFY: insert_annotation, get_annotations_by_roll,
│   │                                #         get_annotations_by_moment, set_vault_state,
│   │                                #         get_vault_state, schema migration for two columns
│   ├── main.py                      # MODIFY: include annotations + publish routers
│   └── api/rolls.py                 # MODIFY: MomentOut gains annotations; RollDetailOut gains vault_path
│   └── analysis/vault.py            # MODIFY: RollSummary gains roll_id from frontmatter
├── tests/backend/
│   ├── test_vault_writer.py         # NEW
│   ├── test_db_annotations.py       # NEW
│   ├── test_db_vault_state.py       # NEW
│   ├── test_api_annotations.py      # NEW
│   ├── test_api_publish.py          # NEW
│   └── test_vault.py                # MODIFY: list_rolls exposes roll_id
├── web/
│   ├── src/
│   │   ├── lib/
│   │   │   ├── api.ts               # MODIFY: addAnnotation, publishRoll
│   │   │   ├── types.ts             # MODIFY: Annotation, Moment.annotations, RollDetail.vault_path, RollSummary.roll_id
│   │   │   └── components/
│   │   │       ├── MomentDetail.svelte      # MODIFY: add notes thread + textarea
│   │   │       └── PublishConflictDialog.svelte  # NEW
│   │   └── routes/
│   │       ├── +page.svelte                 # MODIFY: conditional link on roll_id
│   │       └── review/[id]/+page.svelte     # MODIFY: Save to Vault button + conflict dialog
│   └── tests/
│       ├── moment-detail.test.ts            # MODIFY: notes thread + textarea
│       ├── publish-conflict.test.ts         # NEW
│       └── home.test.ts                     # MODIFY: clickable vs non-clickable tiles
```

## Testing strategy

### Backend (pytest)

- **`test_vault_writer.py`** — round-trip `render_your_notes` → splice → parse → equal. Hash stability across identical inputs. `ConflictError` on mismatched hash. First-publish creates file with correct frontmatter. Atomic write does not leave `.tmp` behind on success. `slugify_filename` handles existing-file collisions. Security: `slugify_filename` rejects paths escaping `Roll Log/`.
- **`test_db_annotations.py`** — insert, retrieve ordered, cascade delete on moment delete, multiple per moment.
- **`test_db_vault_state.py`** — set + get, NULL when unset, round-trip of non-ASCII filename.
- **`test_api_annotations.py`** — PATCH happy path returns 201, 404 on unknown roll/moment, multiple posts accumulate.
- **`test_api_publish.py`** — first publish creates file with frontmatter + Your Notes; re-publish splices only that section (verified by changing a non-Your-Notes section in a fixture file and confirming the re-publish leaves it intact); 409 on external Your-Notes edit; `force=true` overrides; FileNotFoundError path recreates.
- **`test_vault.py`** (existing) — extended: a fixture file with `roll_id` frontmatter yields `roll_id` in the `RollSummary`; a file without yields `None`.

### Frontend (Vitest + Svelte Testing Library)

- **`moment-detail.test.ts`** (existing) — extended: renders prior notes thread; submitting a new note POSTs and appends to thread; empty submit does nothing.
- **`publish-conflict.test.ts`** — renders on a 409 response; Overwrite re-sends with `{force: true}`; Cancel closes without re-sending.
- **`home.test.ts`** (existing) — extended: tile with `roll_id` is an anchor to `/review/<uuid>`; tile without is rendered as non-link with ".md only" badge.

### Manual smoke (M4 completion gate)

1. Upload a video, run pose pre-pass, analyse a moment with Claude.
2. Click a chip → type a note → Add → note appears in thread.
3. Add a second note on the same moment → thread grows.
4. Click "Save to Vault" → toast success → open file in Obsidian → see `## Your Notes` with the H3-per-moment structure.
5. In Obsidian, type in `## Your Notes` directly → save → back in the app, click "Save to Vault" → 409 dialog appears.
6. Click Overwrite → Obsidian edit gets replaced by app version.
7. In Obsidian, edit `## Overall Notes` (not Your Notes) → save → back in the app, "Save to Vault" → 200, no dialog, Obsidian edit preserved.
8. Refresh home page → uploaded roll now appears in the list as a clickable tile.

## Dependencies

No new third-party dependencies. All done with `python-frontmatter` (already installed), `hashlib`, `re`, `pathlib`, `os.replace`.

## Open items (deferred to later milestones)

- **Edit / delete annotations.** User tooling for correcting typos. Not urgent because append-only with "correction notes" works as a workflow; revisit if it becomes friction in practice.
- **Analyses-to-vault.** M6 extends the vault writer to render scores, key moments, summary, and improvements alongside `## Your Notes`. The section-isolated write approach scales: each section owned by the app is independently hash-tracked.
- **Legacy vault retrofit.** Option to create SQLite rows for pre-M2a `Roll Log/*.md` files so they open in the app. Out of scope for M4.
- **Three-way merge on conflict.** An in-app diff viewer for the 409 case. Currently the terse dialog + git recovery is the answer.
- **Concurrent publish serialization.** Not needed for single-user usage; would matter if the app ever served multiple clients.

## Completion criteria

1. `pytest tests/backend -v` all green, including the new M4 tests (~15–20 added tests).
2. `npm test` all green including the new conflict dialog test.
3. Manual smoke (above, 8 steps) passes.
4. No existing M1/M2a/M2b/M3 tests regress.
5. The vault writer is the only module that writes to `Roll Log/*.md` (grep enforces: only `vault_writer.py` under `server/` opens files in the vault's Roll Log for write).
