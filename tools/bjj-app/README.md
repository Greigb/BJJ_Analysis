# BJJ Local Review App

Local web app for reviewing BJJ rolls.
See `docs/superpowers/specs/2026-04-20-bjj-local-review-app-design.md` for full design.

## One-time setup

```bash
cd tools/bjj-app

# Backend (Python 3.12 — MediaPipe does not yet support 3.13/3.14)
/usr/local/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Frontend
cd web
npm install
cd ..
```

## Running

### Dev mode (hot-reload both sides)

```bash
./scripts/dev.sh
```

Open: http://127.0.0.1:5173

Backend runs on 8000; Vite proxies `/api/*` to it.

### Production mode (builds frontend, binds 0.0.0.0)

```bash
./scripts/run.sh
```

Open: http://127.0.0.1:8000 (locally) or http://<mac-lan-ip>:8000 (from your phone on the same wifi).

## Running tests

```bash
# Backend
pytest tests/backend -v

# Frontend
cd web && npm test
```

## Milestones

- **M1 (shipped):** Scaffolding. Home page lists vault's `Roll Log/` via `GET /api/rolls`.
- **M2a (shipped):** Video upload (`POST /api/rolls`), review page skeleton, `/assets/` static mount.
- **M2b (shipped):** MediaPipe pose pre-pass, `POST /api/rolls/:id/analyse` SSE endpoint, timeline chips seek the video on click.
- **M3 (shipped):** Claude CLI adapter (sole `claude -p` caller), `POST /api/rolls/:id/moments/:frame_idx/analyse` streaming, SQLite cache, sliding-window rate limiter. Security audit at `docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`.
- **M4 (shipped):** Append-only annotations per moment, explicit "Save to Vault" publish to `Roll Log/*.md`, hash-based conflict detection on `## Your Notes` only, home page routes via `roll_id` frontmatter.
- **M5 (shipped):** Full `/graph` page with clustered state-space visualisation, both players' paths overlaid, filter chips, vault-markdown side drawer, scrubber with smoothly-animated path-head markers. Mini graph widget on `/review/[id]`.
- **M6a (shipped):** Summary step. `POST /api/rolls/:id/summarise` runs one Claude call across all moments + annotations → scores + summary + top-3 improvements + strengths + 3 key-moment pointers. `ScoresPanel` renders on the review page; `Save to Vault` now emits `## Summary`, `## Scores`, `## Position Distribution`, `## Key Moments`, `## Top Improvements`, `## Strengths Observed` sections alongside `## Your Notes`. Per-section hash-based conflict detection. Design at `docs/superpowers/specs/2026-04-21-bjj-app-m6a-summary-step-design.md`.
- **M6b (shipped):** PDF export via WeasyPrint. "Export PDF" button on the review page renders a one-page white-paper match report (header, one-sentence summary, three score boxes, position-flow bar, improvements, strengths, key moments). The PDF writes to `assets/<roll_id>/report.pdf`, the roll's markdown gains a `## Report` section with an Obsidian wikilink, and the browser downloads the file. Export internally invokes `publish()` first so vault summary sections stay current; if any section conflicts, the existing PublishConflictDialog fires (generalised copy covers Notes, summary sections, and the Report section). Requires a one-time `brew install pango` on macOS for WeasyPrint's Cairo/Pango backend. Design at `docs/superpowers/specs/2026-04-21-bjj-app-m6b-pdf-export-design.md`.
- **M7 (abandoned):** PWA + mobile polish. Mobile use case cut — desktop-only is sufficient.
- **M8 (shipped):** Retired the Streamlit prototype (`tools/app.py` deleted, `streamlit` + `streamlit-agraph` removed from root `requirements.txt`).
- **M9 (shipped):** Replaced the auto pose pre-pass with user-picked time-range sections. Users play the video, click **Mark start** / **Mark end** for each section of interest, tune per-section sampling density (1s / 0.5s / 2s), and click **Analyse ranges** to run Claude classification densely inside the picked ranges. Sections persist in a new `sections` table; `moments.section_id` FKs back (nullable; pre-M9 data keeps rendering). MediaPipe dep and pose-pre-pass code retired. Design at `docs/superpowers/specs/2026-04-22-bjj-app-m9-user-picked-sections-design.md`.
- **M9b (shipped):** Section sequence analysis. Pivoted from per-frame moment classification to one Claude call per section with a multi-image narrative prompt — each picked range yields a narrative + coach_tip in a single call, no per-chip clicks. Moments persist internally (for frame storage) but disappear from the UI; chips and the mini-graph are gone. Annotations re-scope to section-level (`annotations.section_id` FK). The finalise / vault / PDF paths all consume sections; `key_moments` resolves by `section_id`; `## Position Distribution` is retired from vault and PDF. SSE events stream `section_started` / `section_queued` / `section_done` / `section_error` / `done` per section; rate-limit hiccups show a "Queued — retrying in Ns…" banner and retry up to 3 times per section. `/graph` is hidden (nav link removed; route + code kept for possible post-M11 revival). Design at `docs/superpowers/specs/2026-04-22-bjj-app-m9b-section-sequence-analysis-design.md`.
- **M10 (shipped):** Vault knowledge grounding. `build_section_prompt` gains an optional ordered `positions: list[PositionNote]` that renders a "Canonical BJJ positions" reference block (one bullet per position: name, id, and `## How to Identify` body) inserted between the frame refs and the guidance sentence. Plumbed from `app.state.positions_index` + `app.state.taxonomy` (both loaded in `create_app`) through `/analyse` → `run_section_analysis`. Pure prompt-level change — no schema, UI, or DB updates. Adds ~2.5 k tokens to each section call; covers 44/46 real vault notes (meta-positions without `## How to Identify` are silently skipped). Editing a position note in Obsidian requires a backend restart to take effect (index is built once at startup).
- **M11 (shipped):** LLM-as-judge eval harness. `python -m server.eval section|summary --fixture …yaml --variants a b --output run.md` regenerates narratives + summaries for fixture entries across multiple prompt variants, scores each with a second Claude call against a rubric, and writes a markdown comparison report. Lives under `tools/bjj-app/server/eval/`; no UI, no CI, ad-hoc only. First use: quantify M9b-baseline vs M10-grounded section narratives. See `tools/bjj-app/server/eval/README.md` for CLI + fixture format.
- **M12 (shipped, live):** Vault **techniques** grounding — extends M10 with technique references pulled from `Techniques/*.md`. 115 technique notes carry `technique_id` frontmatter; `## Used from` wikilinks (44 unique targets, all resolving to taxonomy positions) map each technique to its source positions. `server/analysis/techniques_vault.py` mirrors the M10 positions module; `build_section_prompt` takes `techniques` + `techniques_mode` and renders nested `Techniques from here: armbar, triangle, …` sub-lines under each position bullet (names mode, live default) or an additional detail block with each technique's `## How to Identify` body (names+bodies mode, eval-only, heavier token cost). `BJJ_GROUNDING_MODE` env defaults to `positions+techniques` (live) after a 4-way eval (n=5) showed techniques-names/-bodies beating M10 on accuracy (+0.8) and overall (+0.2 to +0.4). Set env to `positions` for the M10 path or `off` for M9b. Eval harness has `m10-techniques-names` and `m10-techniques-bodies` variants. Content bootstrap handled by `scripts/bootstrap_technique_notes.py` + `scripts/apply_technique_drafts.py`.
