# BJJ Local Review App — Design

**Date:** 2026-04-20
**Status:** Design approved, implementation plan pending
**Author:** Greig (with Claude Opus 4.7)
**Supersedes:** The Streamlit prototype at `tools/app.py` (to be deleted at M8)

## Context

Greig has an Obsidian-vault-as-repo at `/Users/greigbradley/Desktop/BJJ_Analysis/` with:
- 68 BJJ positions and 111+ techniques, interconnected via wikilinks.
- An existing analysis pipeline using mixed tools: `analyse_roll.py`, `groq_analyser.py`, `pose_analyser.py`, and a Streamlit web app at `tools/app.py` (1,161 lines).
- Roll analyses landing as markdown in `Roll Log/`.

The Streamlit app is being retired. It requires a Groq API key, its aesthetic feels clunky, and it doesn't support the two workflows Greig actually wants: (1) an enjoyable video review experience with inline annotations and PDF export, (2) a dedicated graph view showing both players' paths through the BJJ state-space.

The new app must:
- Look and feel polished enough that Greig enjoys using it.
- Run entirely locally, with no paid API dependency at runtime.
- Use Greig's existing Claude Code subscription as the analysis engine (no `ANTHROPIC_API_KEY`).
- Work on mobile over local wifi (view-only, PWA-installable).
- Write all analyses and annotations back into the Obsidian vault as markdown (vault-first principle).
- Export a printed "match report" PDF for sharing with training partners.

## Goals

1. **Upload → analyse → review → annotate → export** as a smooth single-app flow on Greig's Mac.
2. **Use Claude Opus 4.7 via the `claude` CLI** (subscription-backed) — not the paid API.
3. **Two distinct pages**, each with a clear identity:
   - **Roll Review** — video + dual-lane timeline + selected-moment detail + mini current-position indicator.
   - **BJJ Graph** — category-clustered node-link visualisation of all 68 positions, with both players' roll paths overlaid.
4. **Vault-first data** — all analyses and user notes end up in `Roll Log/*.md`, rendering identically in Obsidian.
5. **Mobile view** — phone reaches the Mac's app over local wifi, installs as a PWA, reads analyses produced on the Mac.
6. **Printed match report PDF** — white-paper, serif-headed, "coaching artifact" feel, suitable for sharing.

## Non-goals (explicit)

- No analysis initiated from mobile (phone is view-only).
- No remote access / Tailscale / cloud sync in V1.
- No multi-user accounts or authentication.
- No training of a custom ML classifier (that belongs to the separate ML Learning Path).
- No real-time / live-mat analysis.
- No in-app video editing.
- No cross-roll trend statistics in V1 (needs ≥5 rolls to be useful — revisit later).

## User-facing requirements

### Roll Review page (`/review/:id`)

Layout — vertical stack (mobile-first):

1. **Header:** roll title, date, partner, duration, result badge (editable dropdown: win/loss/draw + method), primary actions (Re-analyse, Finalise (runs the summary step), Export PDF).
2. **Video player:** HTML5 `<video>` with native controls. 16:9 aspect. A secondary scrubber below is bound to the timeline.
3. **Dual-lane timeline:** Greig's lane (white dot, ivory chips) above Anthony's (red dot, warm chips). Each chip is coloured by the **category** of the position at that moment (standing, guard-top, guard-bottom, dominant, inferior, leg-ent, scramble, pass, submission). Clicking a chip jumps the video and selects the moment. Unanalysed moments (pose-delta flagged but not yet Claude-analysed) show as outlined/dashed chips.
4. **Selected-moment detail panel:** large timestamp, both players' positions as category-tinted pills, description paragraph, coach tip (highlighted left border), annotation input box. For unanalysed moments: shows an "Analyse this moment with Claude Opus 4.7" button instead.
5. **Mini graph:** small, static, category-clustered graph showing both players' current node. Dashed trail behind each. "Open full BJJ graph" link to `/graph`. (Shares rendering code with the main graph page from M5.)
6. **Footer:** three score chips (Guard Retention, Positional Awareness, Transition Quality, each /10). Shown only after `/summarise` has run. Save to Vault button, Share Link button.

### BJJ Graph page (`/graph`)

- Full-screen, category-clustered node-link graph using Cytoscape.js.
- Six soft-tinted regions for categories: Guard Bottom, Guard Top, Dominant/Submission, Leg Entanglement, Scramble, Neutral/Standing.
- All 68 taxonomy positions as nodes; all transitions as faint edges.
- Two path overlays: Greig (white) and Anthony (red), drawn over the baseline edges with animated direction arrows.
- Filter chips at top: "All", per-category, per-player.
- Timeline scrubber at bottom — scrubbing animates the path head through the graph.
- Clicking a node opens a side panel with that position's Obsidian note content (read-only view).

### PDF export (printed match report)

- White paper, Georgia/serif headings, -apple-system/sans-serif body.
- Page 1: brand header, roll title + subtitle (date, duration, no-gi/gi, frames analysed), result badge, one-sentence summary, three score boxes (/10), compact position-flow bar for Greig, three key moments as a readable list.
- Page 2: annotated frames of key moments (with vault-sourced coach tips), full user annotations, vault links for further reading.
- Rendered by WeasyPrint (pure Python, no Chromium dependency).

### Annotation workflow

- User types a note in the selected-moment panel.
- On save, app:
  1. Writes to SQLite (immediate).
  2. Reads the vault markdown file, verifies hash hasn't changed since last read.
  3. If unchanged: appends/updates the `## Your Notes` section and writes atomically (`.tmp` + rename).
  4. If changed: shows a merge/overwrite dialog. No silent clobbering.

### Mobile

- PWA manifest (`web/static/manifest.json`), service worker for offline caching of the app shell + last-viewed roll's JSON.
- Layout is identical (already mobile-first). Touch targets ≥44px.
- Reach via `http://<mac-local-ip>:8000` on same wifi. Home-screen install prompt surfaces automatically on first visit.

## Architecture

Two processes in dev, one in production.

### Backend — FastAPI (Python 3.11+)

Binds to `0.0.0.0:8000`. Owns: frame extraction, MediaPipe pose pre-pass, the `claude -p` subprocess wrapper, SQLite, WeasyPrint, and vault read/write.

### Frontend — SvelteKit (static build)

In development: Vite dev server on `:5173`, proxies `/api/*` to FastAPI.
In production: `@sveltejs/adapter-static` builds to static assets; FastAPI serves them at `/` and API calls at `/api/*`. One process, one URL.

### Directory layout

```
tools/bjj-app/
├── server/
│   ├── main.py              # FastAPI entrypoint + CORS + static mount
│   ├── api/
│   │   ├── rolls.py         # upload, list, get, annotate
│   │   ├── analyse.py       # MediaPipe pre-pass + SSE stream of Claude results
│   │   ├── graph.py         # taxonomy + transitions (reads taxonomy.json)
│   │   └── export.py        # PDF + markdown export
│   ├── analysis/
│   │   ├── frames.py        # OpenCV frame extraction
│   │   ├── pose.py          # MediaPipe BlazePose wrapper + pose-delta scoring
│   │   ├── claude_cli.py    # SOLE wrapper around `claude -p`
│   │   └── vault.py         # Read/write Obsidian markdown, hash-based conflict detect
│   ├── pdf/
│   │   ├── template.html    # WeasyPrint template (printed match report)
│   │   └── render.py
│   └── db.py                # SQLite schema + queries
├── web/
│   ├── src/
│   │   ├── routes/
│   │   │   ├── +page.svelte            # roll list (home)
│   │   │   ├── new/+page.svelte        # upload + analyse flow
│   │   │   ├── review/[id]/+page.svelte # Roll Review page
│   │   │   └── graph/+page.svelte      # dedicated BJJ graph page
│   │   └── lib/
│   │       ├── components/
│   │       │   ├── VideoPlayer.svelte
│   │       │   ├── Timeline.svelte
│   │       │   ├── MomentDetail.svelte
│   │       │   ├── GraphCluster.svelte
│   │       │   └── PWAInstall.svelte
│   │       └── api.ts                  # typed fetch wrappers
│   └── static/
│       └── manifest.json               # PWA manifest
├── tests/
│   ├── backend/
│   │   ├── test_claude_cli.py          # fake subprocess, contract tests
│   │   ├── test_vault.py               # round-trip annotation I/O
│   │   ├── test_api.py                 # endpoint smoke tests
│   │   └── integration/
│   │       └── test_claude_real.py     # opt-in (@pytest.mark.integration)
│   └── frontend/
│       └── components.test.ts
├── scripts/
│   ├── dev.sh                          # runs backend + frontend in dev
│   └── run.sh                          # production: build frontend, start FastAPI
└── pyproject.toml
```

### Key boundary choices

1. **`analysis/claude_cli.py` is the only module that spawns `claude`.** All calls — position classification, coach tips, any future model work — go through this seam. Makes rate-limiting, caching, retries, and model swaps trivially replaceable.
2. **Vault is the canonical store; SQLite is ephemeral.** The markdown in `Roll Log/` remains source-of-truth. SQLite holds app state (uploaded video paths, pose data, moment selections, Claude response cache) but deleting it doesn't lose any knowledge — just forces a re-run.
3. **Existing CLI tools stay.** `tools/analyse_roll.py`, `tools/groq_analyser.py`, `tools/pose_analyser.py`, etc. are untouched (they're independent CLIs). The new app lives in `tools/bjj-app/`. Only `tools/app.py` (Streamlit) is deleted, at M8, after the new app is confirmed working.

## Backend API surface

All under `/api`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/rolls` | Upload a video file. Returns `{roll_id, path}`. Video stored at `assets/<roll_id>/source.mp4`. |
| GET | `/rolls` | List all rolls (home page). |
| GET | `/rolls/:id` | Full roll: metadata, moments, analyses, annotations, scores. |
| POST | `/rolls/:id/analyse` | Kick off pose pre-pass. Returns SSE stream of progress events. |
| POST | `/rolls/:id/moments/:frame_idx/analyse` | Single-frame Claude analysis. Streams partial JSON as Claude generates. |
| PATCH | `/rolls/:id/annotations` | Save a user note. Triggers vault markdown rewrite. |
| POST | `/rolls/:id/summarise` | Single Claude call to compute scores + summary + top-3 improvements across all completed moment analyses. Writes to SQLite + vault frontmatter. |
| POST | `/rolls/:id/export/pdf` | Render printed match report; returns PDF. |
| GET | `/graph` | Taxonomy + transitions (reads `tools/taxonomy.json`). Cached in memory. |
| GET | `/vault/position/:id` | Position note markdown (for graph side panel). |

## Analysis pipeline — end-to-end data flow

```
1. POST /rolls                          user drops video
                                        saves file, creates SQLite row
                                        returns roll_id
                                        ↓
2. POST /rolls/:id/analyse              user clicks "Analyse"
                                        ↓
   Step A — frame extraction (OpenCV)
     frames → assets/<id>/frames/*.jpg at 1fps
     SSE: {stage: "frames", pct: ...}
   Step B — pose pre-pass (MediaPipe BlazePose, fully local)
     pose landmarks per frame
     compute frame-to-frame pose delta
     flag frames with delta > threshold as "interesting"
     SSE: {stage: "pose", pct: ...}
   Step C — finish
     SSE: {stage: "done", moments: [...]}
                                        ↓
   Browser renders timeline with suggested moments

3. User clicks a moment →
   POST /rolls/:id/moments/:frame_idx/analyse
                                        ↓
   Check SQLite cache (frame_hash + prompt_hash). Hit → return cached.
   Miss → build prompt (frame image path + taxonomy + vault snippet)
        → spawn `claude -p --model claude-opus-4-7 --output-format stream-json ...`
        → pipe stdout to browser as SSE
        → parse final JSON (both players' positions, coach tip, confidence)
        → write to SQLite + append to vault markdown
                                        ↓
   Browser streams analysis into the selected-moment panel

4. User clicks "Finalise roll" (optional summary step) →
   POST /rolls/:id/summarise
                                        ↓
   Assembles all completed per-frame analyses into a single prompt
   Spawns one more `claude -p` call that returns:
     - scores (retention, awareness, transition — each /10)
     - one-sentence summary
     - top-3 improvements
     - strengths
   Writes to rolls.scores_json + updates vault markdown frontmatter
                                        ↓
   Roll is "finalised" — PDF export and the scores/summary sections
   of the vault markdown are now populated.
```

**Note on summary step:** This is a single additional Claude call (counted against the rate limiter like any other), not a per-frame operation. Running it is optional — users can export a PDF without it, just the scores/summary sections will be empty. It's typically run once when the user has analysed all the moments they care about.

## Claude CLI adapter (`analysis/claude_cli.py`)

The load-bearing module. Detailed design:

**Single entry point:**
```python
async def analyse_frame(
    frame_path: Path,
    vault_context: str,
    stream_callback: Callable[[dict], Awaitable[None]],
) -> AnalysisResult
```

**Subprocess construction:**
- `asyncio.create_subprocess_exec` — never `shell=True`.
- All args in a list; frame paths are validated (must exist, must be inside `assets/`) and passed as plain args.

**CLI flags:**
- `--model claude-opus-4-7`
- `--output-format stream-json`
- `--include-partial-messages`
- `--max-turns 1`
- `--dangerously-skip-permissions` (programmatic use — bypasses Claude Code's tool-use permission prompts so the subprocess can run without interactive approval. Safe in this context because we fully control the prompt, never pass user input into it unescaped, and the only tool we'd need Claude to use is image reading. The implementation plan must explicitly audit this.)
- `-p "<prompt>"`

**Image passing — to be verified at implementation:**
The exact mechanism for giving `claude -p` a frame image is an open detail: it may be `@path/to/frame.jpg` inline in the prompt, or a dedicated `--image` flag, or stdin-piped content. M3 (Claude CLI adapter) must start with a 30-minute spike to confirm the working syntax with `claude -p` v2.1.114 before implementing the rest of the adapter. If image input is only possible via interactive mode, fall back to a different mechanism (e.g., writing a temp markdown file that references the image and passing that as the prompt).

**Prompt structure:**
1. Fixed system preamble: "You are a BJJ position classifier. Output JSON matching the following schema…"
2. Compressed taxonomy (categories + position IDs + key visual cues — not full 500-line taxonomy).
3. Relevant vault snippet (position notes for the categories most likely given pose pre-pass).
4. Frame image reference (CLI reads file by path).
5. Output JSON schema:
   ```json
   {
     "timestamp": 0.0,
     "greig": {"position": "<id>", "confidence": 0.0},
     "anthony": {"position": "<id>", "confidence": 0.0},
     "description": "...",
     "coach_tip": "..."
   }
   ```

**Rate-limit protection:**
- Token bucket in memory, default **10 calls per 5-minute rolling window** (configurable in `config.py`).
- Exceeded → HTTP 429 with `Retry-After`; UI surfaces "Claude cooldown — Ns until next call".

**Retry policy:**
- One retry on subprocess exit ≠ 0, with 2s backoff. Second failure → error response surfaced to UI.
- Partial stream captured before failure is discarded (better than showing half an analysis).

**Caching:**
- `(frame_hash, prompt_hash) → response_json` in SQLite `claude_cache` table.
- Re-analysing the same frame with the same prompt costs zero subscription budget.

## SQLite schema

```sql
CREATE TABLE rolls (
  id            TEXT PRIMARY KEY,
  title         TEXT NOT NULL,      -- user-entered on upload (default: "Roll <date>")
  date          TEXT NOT NULL,      -- user-entered on upload (default: today)
  video_path    TEXT NOT NULL,
  duration_s    REAL,               -- auto-detected from video on upload
  partner       TEXT,               -- user-entered on upload (optional)
  result        TEXT,               -- 'unknown' (default) | win_submission | loss_submission | win_points | loss_points | draw | continuation; user sets via the header's result badge dropdown
  scores_json   TEXT,               -- null until /summarise has run; {retention, awareness, transition, summary, top_3_improvements, strengths}
  finalised_at  INTEGER,            -- when summary step completed; null means not yet finalised
  created_at    INTEGER NOT NULL
);

CREATE TABLE moments (
  id                    TEXT PRIMARY KEY,
  roll_id               TEXT NOT NULL REFERENCES rolls(id) ON DELETE CASCADE,
  frame_idx             INTEGER NOT NULL,
  timestamp_s           REAL NOT NULL,
  pose_delta            REAL,
  selected_for_analysis INTEGER DEFAULT 0  -- 0/1
);

CREATE TABLE analyses (
  id             TEXT PRIMARY KEY,
  moment_id      TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  player         TEXT NOT NULL,  -- 'greig' or 'anthony'
  position_id    TEXT NOT NULL,
  confidence     REAL,
  description    TEXT,
  coach_tip      TEXT,
  claude_version TEXT,
  created_at     INTEGER NOT NULL
);

CREATE TABLE annotations (
  id         TEXT PRIMARY KEY,
  moment_id  TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  body       TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE claude_cache (
  prompt_hash   TEXT,
  frame_hash    TEXT,
  response_json TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  PRIMARY KEY (prompt_hash, frame_hash)
);
```

## Error handling

| Failure | Response |
|---|---|
| Claude CLI exits non-zero / unparseable JSON | One retry at 2s backoff. If second fails, mark moment `error`, UI shows red badge + retry button. Other moments unaffected. |
| Rate limit (token bucket exhausted) | HTTP 429 + `Retry-After`. UI toast: "Claude cooldown — Ns". Cached moments remain viewable. |
| Claude not logged in / wrong plan | First call detects via stderr. UI prompts: "Run `claude auth login`, then refresh." |
| Invalid/corrupted video | OpenCV fails to open → HTTP 400 with codec hint. Roll row not persisted. |
| MediaPipe finds no interesting moments | Fallback: offer uniform sampling at 10s intervals. |
| Vault write conflict (markdown edited in Obsidian) | Hash mismatch detected. UI shows merge/overwrite dialog. No silent clobbering. |
| SQLite corruption | Startup `PRAGMA integrity_check`. On fail: move to `.broken.<ts>`, start fresh. Vault retains all knowledge. |
| PDF render failure | Log error. Show HTML preview. Offer raw HTML download as fallback. |
| SSE dropped (mobile loses connection) | Backend job continues. Browser can reconnect with same job ID to resume stream. |
| Disk space | Manual "clear frame cache" button keeps videos but drops regeneratable frames. |

## Testing strategy

**Backend (pytest):**
- `test_claude_cli.py` — fake subprocess fixtures verify stream parsing, partial-message handling, cache hits, rate-limit errors, non-zero exits. No real CLI calls (slow + spends budget).
- `test_vault.py` — annotation round-trip (write → read → assert). Wikilink preservation. Uses tmp vault fixtures.
- `test_api.py` — `httpx.AsyncClient` in-process; 200 happy + 400 bad + 404 missing per endpoint.
- `test_pose.py` — short fixture video (`tests/fixtures/short_roll.mp4`), asserts pose-delta values are plausible.
- `integration/test_claude_real.py` — marked `@pytest.mark.integration`, skipped by default. Run manually to verify live CLI hasn't drifted. Caches the result.

**Frontend (Vitest + Svelte Testing Library):**
- Component tests only: `Timeline.svelte` renders N chips, dispatches `select` on click. `MomentDetail.svelte` calls PATCH on annotation edit.
- No Playwright / end-to-end automation — overkill for a one-user app.

**Manual smoke test (documented in `README.md`):**
A numbered checklist ("1. Upload fixture video. 2. Click Analyse. 3. Pick a moment. 4. Confirm stream. 5. Annotate. 6. Check vault markdown. 7. Export PDF. 8. Open on phone via local IP.") run after every significant change. ~5 minutes.

## Dependencies (all free)

**Backend Python:**
- `fastapi` — web framework
- `uvicorn[standard]` — ASGI server with SSE support
- `opencv-python-headless` — frame extraction
- `mediapipe` — pose estimation
- `Pillow` — image handling
- `weasyprint` — PDF rendering (no Chromium)
- `pydantic` — schema validation
- `aiofiles` — async file I/O

**Frontend JS:**
- `svelte`, `@sveltejs/kit`, `@sveltejs/adapter-static`
- `vite`
- `tailwindcss` (build-time via PostCSS — not CDN — because we need custom design tokens and content purge for a small production bundle)
- CDN loads: `cytoscape.js` (graph rendering), optional `hls.js` (if video needs adaptive streaming)

**External tooling required on the host Mac:**
- `claude` CLI v2.1.114+ (already installed at `/Users/greigbradley/.local/bin/claude`).
- Greig must be authenticated (`claude auth login`) with a plan that supports `claude-opus-4-7`.

## Phased delivery

| Milestone | Scope |
|---|---|
| **M1 — Scaffolding** | FastAPI skeleton + SvelteKit skeleton with static build pipeline. Home page renders. Vault read works (list rolls in `Roll Log/`). |
| **M2 — Upload + pose pre-pass** | `POST /rolls` persists video. MediaPipe runs end-to-end. Timeline renders with pose-delta-detected moments. |
| **M3 — Claude CLI adapter** | Spike on image-passing syntax for `claude -p` (30 min). Then: single-frame analysis via CLI, streams back to UI, SQLite cache, rate limiter. Selected-moment panel displays result live. |
| **M4 — Annotations + vault write-back** | Edit note, saves to SQLite AND vault markdown. Hash-based conflict detection. |
| **M5 — Graph page + mini graph** | Cytoscape.js clustered layout (shared `GraphCluster.svelte`). Full graph at `/graph` with both players' paths, click-to-vault-note side panel. Mini graph widget on the Roll Review page uses the same component with a static/small variant. |
| **M6 — Summary step + PDF export** | `POST /rolls/:id/summarise` → scores, summary, top-3 improvements via a final Claude call. WeasyPrint template. "Export PDF" button downloads printed match report. |
| **M7 — PWA + mobile polish** | Manifest, service worker, responsive CSS, "Add to Home Screen" prompt. |
| **M8 — Cleanup** | Delete `tools/app.py` (Streamlit). |

## Post-V1 revisit list

- Tune pose-delta threshold for "interesting moments" from real usage.
- Evaluate clustered graph readability when paths cross 7+ times on a 10-minute roll.
- Token bucket sizing — adjust from 10/5min baseline.
- Potential future additions: video editing, remote access (Tailscale), multi-roll trend dashboards, training the custom position classifier from the ML Learning Path.

## Assumptions baked into this design

- Greig's Claude subscription plan (Pro / Max) supports `claude-opus-4-7` access via CLI.
- Greig's Mac is the only analysis host (app is single-machine, no cloud).
- Rolls are ≤15 minutes long (M2 frame-extraction perf assumes this).
- Analysis is ad-hoc, not batch — Greig reviews one roll at a time.
- The phone and Mac share a local wifi network during review sessions.
