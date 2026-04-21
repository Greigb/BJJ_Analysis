# BJJ Local Review App

Local web app for reviewing BJJ rolls — replaces the Streamlit prototype at `../app.py`.
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
- **M6a (this milestone):** Summary step. `POST /api/rolls/:id/summarise` runs one Claude call across all moments + annotations → scores + summary + top-3 improvements + strengths + 3 key-moment pointers. `ScoresPanel` renders on the review page; `Save to Vault` now emits `## Summary`, `## Scores`, `## Position Distribution`, `## Key Moments`, `## Top Improvements`, `## Strengths Observed` sections alongside `## Your Notes`. Per-section hash-based conflict detection. Design at `docs/superpowers/specs/2026-04-21-bjj-app-m6a-summary-step-design.md`.
- **M6b (next):** PDF export via WeasyPrint. "Export PDF" button on the review page generates a printed match report from the finalised roll.
- **M7–M8:** PWA + mobile polish; cleanup (delete Streamlit `tools/app.py`).
