# BJJ Local Review App

Local web app for reviewing BJJ rolls — replaces the Streamlit prototype at `../app.py`.
See `docs/superpowers/specs/2026-04-20-bjj-local-review-app-design.md` for full design.

## One-time setup

```bash
cd tools/bjj-app

# Backend
python3.11 -m venv .venv
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

## Current milestone: M1 (Scaffolding)

Home page lists rolls already in the Obsidian vault's `Roll Log/` folder.
Upload, analysis, graph, annotations, and PDF export come in M2–M7.
