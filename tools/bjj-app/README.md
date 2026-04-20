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
- **M2a (this milestone):** Video upload (`POST /api/rolls`), review page skeleton (`/review/[id]` with video player + empty timeline), `/assets/` static mount.
- **M2b (next):** MediaPipe pose pre-pass, `POST /api/rolls/:id/analyse` SSE stream, timeline populates with flagged moments.
- **M3–M8:** Claude CLI adapter, annotations, graph page, summary + PDF, PWA, cleanup.
