# BJJ Local Review App — M1 Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the FastAPI backend + SvelteKit frontend scaffolding with a working home page that lists existing rolls from the Obsidian vault's `Roll Log/` directory. This is M1 of the 8-milestone implementation defined in `docs/superpowers/specs/2026-04-20-bjj-local-review-app-design.md`.

**Architecture:** A FastAPI Python backend reads the Obsidian vault markdown files directly, parses their YAML frontmatter, and exposes `GET /api/rolls` returning a JSON list. A SvelteKit frontend renders that list as a home page. Development uses two processes (FastAPI on `:8000`, Vite on `:5173` with a proxy for `/api/*`); production builds the frontend to static assets served by FastAPI on a single port.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, aiofiles, python-frontmatter, pytest, httpx (test client) | Node 24+, SvelteKit, @sveltejs/adapter-static, Vite, TypeScript, Tailwind CSS, Vitest, @testing-library/svelte.

**Scope (M1 only):**
- Project directory structure at `tools/bjj-app/`.
- Backend: one endpoint (`GET /api/rolls`), vault reader, SQLite schema initialisation (empty tables for now).
- Frontend: home page that fetches and renders the roll list, layout shell, typed API wrapper.
- Two run scripts: `dev.sh` and `run.sh`.
- Backend tests: vault reader + API endpoint.
- Frontend tests: home page component renders.
- README with run instructions.

**Explicitly out of scope (later milestones):**
- Video upload (M2), analysis (M2/M3), annotations (M4), graph page (M5), PDF (M6), PWA (M7), Streamlit deletion (M8).
- Any UI beyond the home page (e.g., no `/review/[id]` route yet).

---

## File Structure

```
tools/bjj-app/
├── pyproject.toml                       # Python project + dep pins
├── .python-version                      # 3.11
├── README.md                            # how to run dev + production
├── scripts/
│   ├── dev.sh                           # run backend + frontend in dev mode
│   └── run.sh                           # build frontend + start backend (prod)
├── server/
│   ├── __init__.py
│   ├── main.py                          # FastAPI app entrypoint
│   ├── config.py                        # settings (paths, ports, env overrides)
│   ├── db.py                            # SQLite connect + schema init
│   ├── api/
│   │   ├── __init__.py
│   │   └── rolls.py                     # GET /api/rolls router
│   └── analysis/
│       ├── __init__.py
│       └── vault.py                     # list_rolls() — parses Roll Log/*.md frontmatter
└── web/
    ├── package.json
    ├── svelte.config.js                 # adapter-static
    ├── vite.config.ts                   # /api proxy in dev
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── postcss.config.js
    ├── src/
    │   ├── app.html
    │   ├── app.css                      # Tailwind entry + design tokens
    │   ├── lib/
    │   │   ├── api.ts                   # typed fetch wrappers
    │   │   └── types.ts                 # RollSummary, etc.
    │   └── routes/
    │       ├── +layout.svelte           # app shell (header, nav)
    │       └── +page.svelte             # home page (roll list)
    └── static/
        └── favicon.svg

tools/bjj-app/tests/backend/              # Python tests only
├── conftest.py                          # tmp vault fixture
├── fixtures/
│   └── sample_vault/
│       └── Roll Log/
│           ├── 2026-04-14 - sample roll (win).md
│           └── 2026-04-01 - other roll (continuation).md
├── test_vault.py                        # list_rolls() parsing tests
└── test_api.py                          # GET /api/rolls contract tests

tools/bjj-app/web/tests/                  # Frontend tests (colocated under web/)
├── setup.ts                             # Vitest setup
└── home.test.ts                         # +page.svelte renders roll list
```

Each file has **one responsibility**:
- `vault.py` reads markdown files, nothing else.
- `rolls.py` maps the HTTP interface onto `vault.list_rolls()`, nothing else.
- `db.py` manages SQLite, nothing else.
- `api.ts` is the only frontend module that knows the API shape.

---

## Tasks

### Task 1: Create directory structure

**Files:**
- Create: `tools/bjj-app/` and all subdirs listed in File Structure above (empty, no content yet).

- [ ] **Step 1: Create all directories**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
mkdir -p tools/bjj-app/{server/api,server/analysis,web/src/lib,web/src/routes,web/static,web/tests,scripts,tests/backend/fixtures/sample_vault/Roll\ Log}
```

- [ ] **Step 2: Verify structure**

```bash
find tools/bjj-app -type d | sort
```

Expected output:
```
tools/bjj-app
tools/bjj-app/scripts
tools/bjj-app/server
tools/bjj-app/server/analysis
tools/bjj-app/server/api
tools/bjj-app/tests
tools/bjj-app/tests/backend
tools/bjj-app/tests/backend/fixtures
tools/bjj-app/tests/backend/fixtures/sample_vault
tools/bjj-app/tests/backend/fixtures/sample_vault/Roll Log
tools/bjj-app/web
tools/bjj-app/web/src
tools/bjj-app/web/src/lib
tools/bjj-app/web/src/routes
tools/bjj-app/web/static
tools/bjj-app/web/tests
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/
# Note: empty dirs won't be tracked; a .gitkeep approach is unnecessary because
# upcoming tasks populate every dir. Skip commit here — commit after Task 2.
```

(No commit yet — directories will be committed with their contents in Task 2.)

---

### Task 2: Python project configuration

**Files:**
- Create: `tools/bjj-app/pyproject.toml`
- Create: `tools/bjj-app/.python-version`

- [ ] **Step 1: Write `.python-version`**

Create `tools/bjj-app/.python-version`:

```
3.11
```

- [ ] **Step 2: Write `pyproject.toml`**

Create `tools/bjj-app/pyproject.toml`:

```toml
[project]
name = "bjj-app"
version = "0.1.0"
description = "Local BJJ roll review app — FastAPI backend"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "aiofiles>=24.1.0",
    "python-frontmatter>=1.1.0",
    "pydantic>=2.9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["server*"]

[tool.pytest.ini_options]
testpaths = ["tests/backend"]
asyncio_mode = "auto"
pythonpath = ["."]
```

- [ ] **Step 3: Create Python venv and install**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 4: Verify install**

```bash
python -c "import fastapi, uvicorn, frontmatter; print('ok')"
```

Expected output: `ok`

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/pyproject.toml tools/bjj-app/.python-version
git commit -m "chore(bjj-app): add python project config for M1 scaffold"
```

---

### Task 3: Update repo .gitignore for bjj-app

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append bjj-app ignores to `.gitignore`**

Add these lines to the end of `/Users/greigbradley/Desktop/BJJ_Analysis/.gitignore`:

```
# bjj-app — local build artifacts
tools/bjj-app/.venv/
tools/bjj-app/web/node_modules/
tools/bjj-app/web/build/
tools/bjj-app/web/.svelte-kit/
tools/bjj-app/**/__pycache__/
tools/bjj-app/**/*.egg-info/
tools/bjj-app/bjj-app.db
tools/bjj-app/bjj-app.db.broken.*
tools/bjj-app/.pytest_cache/
```

- [ ] **Step 2: Verify git status respects ignores**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git status | grep -E "(venv|node_modules|__pycache__|svelte-kit)" && echo "LEAK!" || echo "ok"
```

Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore bjj-app build artifacts"
```

---

### Task 4: Write vault fixture files

**Files:**
- Create: `tools/bjj-app/tests/backend/fixtures/sample_vault/Roll Log/2026-04-14 - sample roll (win).md`
- Create: `tools/bjj-app/tests/backend/fixtures/sample_vault/Roll Log/2026-04-01 - other roll (continuation).md`

These drive the vault reader tests.

- [ ] **Step 1: Write first fixture**

Create `tools/bjj-app/tests/backend/fixtures/sample_vault/Roll Log/2026-04-14 - sample roll (win).md`:

```markdown
---
date: 2026-04-14
partner: Anthony
duration: "2:23"
frames_analysed: 28
guard_retention: 7
positional_awareness: 7
transition_quality: 7
method: claude-vision
result: win_submission
tags: [roll, claude-analysis, visual-review]
---

# Roll 1: Greig vs Anthony — WIN by Submission

Sample content for the fixture vault.
```

- [ ] **Step 2: Write second fixture**

Create `tools/bjj-app/tests/backend/fixtures/sample_vault/Roll Log/2026-04-01 - other roll (continuation).md`:

```markdown
---
date: 2026-04-01
partner: Bob
duration: "1:45"
frames_analysed: 15
result: continuation
tags: [roll]
---

# Other roll — continuation

Sample content.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/fixtures/
git commit -m "test(bjj-app): add vault fixture files for vault reader tests"
```

---

### Task 5: Write failing test for vault reader

**Files:**
- Create: `tools/bjj-app/tests/backend/conftest.py`
- Create: `tools/bjj-app/tests/backend/test_vault.py`

- [ ] **Step 1: Write `conftest.py`**

Create `tools/bjj-app/tests/backend/conftest.py`:

```python
from pathlib import Path

import pytest


@pytest.fixture
def sample_vault() -> Path:
    """Path to the fixture vault used by vault.py tests."""
    return Path(__file__).parent / "fixtures" / "sample_vault"
```

- [ ] **Step 2: Write `test_vault.py`**

Create `tools/bjj-app/tests/backend/test_vault.py`:

```python
from pathlib import Path

import pytest

from server.analysis.vault import RollSummary, list_rolls


def test_list_rolls_returns_summaries_sorted_newest_first(sample_vault: Path):
    rolls = list_rolls(sample_vault)

    assert len(rolls) == 2
    assert all(isinstance(r, RollSummary) for r in rolls)

    assert rolls[0].date == "2026-04-14"
    assert rolls[0].partner == "Anthony"
    assert rolls[0].duration == "2:23"
    assert rolls[0].result == "win_submission"
    assert rolls[0].title == "Roll 1: Greig vs Anthony — WIN by Submission"
    assert rolls[0].path.name == "2026-04-14 - sample roll (win).md"

    assert rolls[1].date == "2026-04-01"
    assert rolls[1].partner == "Bob"


def test_list_rolls_handles_missing_roll_log_dir(tmp_path: Path):
    # No Roll Log/ subdir — should return empty list, not raise.
    rolls = list_rolls(tmp_path)
    assert rolls == []


def test_list_rolls_skips_files_without_frontmatter(tmp_path: Path):
    roll_log = tmp_path / "Roll Log"
    roll_log.mkdir()
    (roll_log / "no_frontmatter.md").write_text("# Just a markdown file\n")
    (roll_log / "has_frontmatter.md").write_text(
        "---\ndate: 2026-01-01\nresult: draw\n---\n# Has frontmatter\n"
    )

    rolls = list_rolls(tmp_path)
    assert len(rolls) == 1
    assert rolls[0].title == "Has frontmatter"
```

- [ ] **Step 3: Run the tests — they MUST fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_vault.py -v
```

Expected output: ImportError or ModuleNotFoundError — `server.analysis.vault` does not exist yet.

- [ ] **Step 4: Commit the failing tests**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/conftest.py tools/bjj-app/tests/backend/test_vault.py
git commit -m "test(bjj-app): add vault reader tests (failing — no implementation)"
```

---

### Task 6: Implement vault reader to make tests pass

**Files:**
- Create: `tools/bjj-app/server/__init__.py` (empty)
- Create: `tools/bjj-app/server/analysis/__init__.py` (empty)
- Create: `tools/bjj-app/server/analysis/vault.py`

- [ ] **Step 1: Create empty `__init__.py` files**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
touch server/__init__.py
touch server/analysis/__init__.py
```

- [ ] **Step 2: Write `vault.py`**

Create `tools/bjj-app/server/analysis/vault.py`:

```python
"""Read roll summaries from the Obsidian vault's Roll Log/ directory."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class RollSummary:
    """One row in the home page's roll list."""

    path: Path
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None


def list_rolls(vault_root: Path) -> list[RollSummary]:
    """Scan `vault_root/Roll Log/*.md` and return parsed summaries, newest first.

    Files without YAML frontmatter are skipped. If `Roll Log/` does not exist,
    returns an empty list.
    """
    roll_log = vault_root / "Roll Log"
    if not roll_log.is_dir():
        return []

    summaries: list[RollSummary] = []
    for md_path in sorted(roll_log.glob("*.md")):
        post = frontmatter.load(md_path)
        if not post.metadata:
            continue

        title = _extract_title(post.content, fallback=md_path.stem)
        summaries.append(
            RollSummary(
                path=md_path,
                title=title,
                date=str(post.metadata.get("date", "")),
                partner=_str_or_none(post.metadata.get("partner")),
                duration=_str_or_none(post.metadata.get("duration")),
                result=_str_or_none(post.metadata.get("result")),
            )
        )

    summaries.sort(key=lambda r: r.date, reverse=True)
    return summaries


def _extract_title(content: str, *, fallback: str) -> str:
    match = _TITLE_RE.search(content)
    return match.group(1) if match else fallback


def _str_or_none(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
```

- [ ] **Step 3: Run the tests — they MUST pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_vault.py -v
```

Expected output: `3 passed`.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/__init__.py tools/bjj-app/server/analysis/
git commit -m "feat(bjj-app): implement vault reader (list_rolls)"
```

---

### Task 7: Write `config.py` for backend settings

**Files:**
- Create: `tools/bjj-app/server/config.py`

- [ ] **Step 1: Write `config.py`**

Create `tools/bjj-app/server/config.py`:

```python
"""Runtime configuration for the BJJ app backend."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _project_root() -> Path:
    # tools/bjj-app/server/config.py → project root is three parents up
    return Path(__file__).resolve().parent.parent.parent.parent


@dataclass(frozen=True)
class Settings:
    project_root: Path
    vault_root: Path
    db_path: Path
    host: str
    port: int
    frontend_build_dir: Path


def load_settings() -> Settings:
    project_root = Path(os.getenv("BJJ_PROJECT_ROOT", str(_project_root()))).resolve()
    return Settings(
        project_root=project_root,
        vault_root=project_root,  # vault IS the project root per the spec
        db_path=project_root / "tools" / "bjj-app" / "bjj-app.db",
        host=os.getenv("BJJ_HOST", "0.0.0.0"),
        port=int(os.getenv("BJJ_PORT", "8000")),
        frontend_build_dir=project_root / "tools" / "bjj-app" / "web" / "build",
    )
```

- [ ] **Step 2: Quick sanity check**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
python -c "from server.config import load_settings; s = load_settings(); print(s.vault_root, s.port)"
```

Expected output: `/Users/greigbradley/Desktop/BJJ_Analysis 8000`

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/config.py
git commit -m "feat(bjj-app): add runtime settings module"
```

---

### Task 8: Write `db.py` with SQLite schema (all tables, empty for now)

**Files:**
- Create: `tools/bjj-app/server/db.py`

- [ ] **Step 1: Write `db.py`**

Create `tools/bjj-app/server/db.py`:

```python
"""SQLite connection + schema initialisation.

Schema matches the spec at docs/superpowers/specs/2026-04-20-bjj-local-review-app-design.md.
M1 only initialises the schema — no reads/writes from/to these tables yet.
Later milestones populate them.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
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
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS moments (
    id TEXT PRIMARY KEY,
    roll_id TEXT NOT NULL REFERENCES rolls(id) ON DELETE CASCADE,
    frame_idx INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    pose_delta REAL,
    selected_for_analysis INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    moment_id TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
    player TEXT NOT NULL,
    position_id TEXT NOT NULL,
    confidence REAL,
    description TEXT,
    coach_tip TEXT,
    claude_version TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    moment_id TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS claude_cache (
    prompt_hash TEXT,
    frame_hash TEXT,
    response_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (prompt_hash, frame_hash)
);
"""


def init_db(db_path: Path) -> None:
    """Create the schema if it doesn't already exist. Safe to call every startup."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with foreign-key enforcement enabled."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 2: Smoke-test schema initialisation**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
python -c "
from pathlib import Path
from server.db import init_db, connect
p = Path('/tmp/bjj_smoke.db')
p.unlink(missing_ok=True)
init_db(p)
conn = connect(p)
names = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print(sorted(names))
p.unlink()
"
```

Expected output: `['analyses', 'annotations', 'claude_cache', 'moments', 'rolls']`

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py
git commit -m "feat(bjj-app): add sqlite schema init (empty tables for M1)"
```

---

### Task 9: Write failing test for `GET /api/rolls`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api.py`

- [ ] **Step 1: Write the test**

Create `tools/bjj-app/tests/backend/test_api.py`:

```python
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_get_rolls_returns_list_from_vault(
    monkeypatch: pytest.MonkeyPatch,
    sample_vault: Path,
    tmp_path: Path,
) -> None:
    # Point settings at the sample vault fixture.
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(sample_vault))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))

    # Import AFTER monkeypatching so settings pick up the env.
    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/rolls")

    assert response.status_code == 200
    body = response.json()

    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["date"] == "2026-04-14"
    assert body[0]["partner"] == "Anthony"
    assert body[0]["title"] == "Roll 1: Greig vs Anthony — WIN by Submission"
    assert body[0]["result"] == "win_submission"
    assert "path" in body[0]


@pytest.mark.asyncio
async def test_get_rolls_returns_empty_list_when_no_roll_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))

    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/rolls")

    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 2: Run the tests — they MUST fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_api.py -v
```

Expected output: ImportError — `server.main.create_app` does not exist yet.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api.py
git commit -m "test(bjj-app): add api contract tests (failing — no implementation)"
```

---

### Task 10: Implement API endpoint + FastAPI app factory

**Files:**
- Create: `tools/bjj-app/server/api/__init__.py` (empty)
- Create: `tools/bjj-app/server/api/rolls.py`
- Create: `tools/bjj-app/server/main.py`
- Modify: `tools/bjj-app/server/config.py` (support `BJJ_DB_OVERRIDE` for tests)

- [ ] **Step 1: Update `config.py` to support DB path override**

Replace the entire contents of `tools/bjj-app/server/config.py` with:

```python
"""Runtime configuration for the BJJ app backend."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


@dataclass(frozen=True)
class Settings:
    project_root: Path
    vault_root: Path
    db_path: Path
    host: str
    port: int
    frontend_build_dir: Path


def load_settings() -> Settings:
    project_root = Path(os.getenv("BJJ_PROJECT_ROOT", str(_project_root()))).resolve()
    db_override = os.getenv("BJJ_DB_OVERRIDE")
    db_path = (
        Path(db_override)
        if db_override
        else project_root / "tools" / "bjj-app" / "bjj-app.db"
    )
    return Settings(
        project_root=project_root,
        vault_root=project_root,
        db_path=db_path,
        host=os.getenv("BJJ_HOST", "0.0.0.0"),
        port=int(os.getenv("BJJ_PORT", "8000")),
        frontend_build_dir=project_root / "tools" / "bjj-app" / "web" / "build",
    )
```

- [ ] **Step 2: Write `server/api/rolls.py`**

Create `tools/bjj-app/server/api/__init__.py` (empty file first):

```bash
touch /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/api/__init__.py
```

Then create `tools/bjj-app/server/api/rolls.py`:

```python
"""GET /api/rolls — list roll summaries from the Obsidian vault."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from server.analysis.vault import RollSummary, list_rolls
from server.config import Settings, load_settings


class RollSummaryOut(BaseModel):
    path: str
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None

    @classmethod
    def from_domain(cls, r: RollSummary) -> "RollSummaryOut":
        return cls(
            path=str(r.path),
            title=r.title,
            date=r.date,
            partner=r.partner,
            duration=r.duration,
            result=r.result,
        )


router = APIRouter(prefix="/api", tags=["rolls"])


@router.get("/rolls", response_model=list[RollSummaryOut])
def get_rolls(settings: Settings = Depends(load_settings)) -> list[RollSummaryOut]:
    return [RollSummaryOut.from_domain(r) for r in list_rolls(settings.vault_root)]
```

- [ ] **Step 3: Write `server/main.py`**

Create `tools/bjj-app/server/main.py`:

```python
"""FastAPI entrypoint — creates the app and wires routers + static frontend."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api import rolls as rolls_api
from server.config import load_settings
from server.db import init_db


def create_app() -> FastAPI:
    settings = load_settings()
    init_db(settings.db_path)

    app = FastAPI(title="BJJ Review App", version="0.1.0")

    # Dev-time CORS so Vite on :5173 can call /api directly if proxy is bypassed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(rolls_api.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 4: Run the API tests — they MUST pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_api.py -v
```

Expected output: `2 passed`.

- [ ] **Step 5: Run full backend test suite**

```bash
pytest tests/backend -v
```

Expected output: `5 passed` (3 vault + 2 api).

- [ ] **Step 6: Smoke-test the live server**

Run in one terminal:

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Run in a second terminal:

```bash
curl -s http://127.0.0.1:8000/api/health
echo
curl -s http://127.0.0.1:8000/api/rolls | python -m json.tool | head -40
```

Expected: health returns `{"status":"ok"}`; rolls returns the actual content of `Roll Log/` from the real vault (should include the real `2026-04-14 - Greig vs Anthony - Roll 1 (WIN by submission).md` and siblings).

Kill the server with Ctrl-C.

- [ ] **Step 7: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/
git commit -m "feat(bjj-app): add fastapi app with GET /api/rolls endpoint"
```

---

### Task 11: Initialise SvelteKit project

**Files:**
- Create: `tools/bjj-app/web/package.json`
- Create: `tools/bjj-app/web/svelte.config.js`
- Create: `tools/bjj-app/web/vite.config.ts`
- Create: `tools/bjj-app/web/tsconfig.json`
- Create: `tools/bjj-app/web/src/app.html`

- [ ] **Step 1: Write `package.json`**

Create `tools/bjj-app/web/package.json`:

```json
{
  "name": "bjj-app-web",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite dev --host 0.0.0.0 --port 5173",
    "build": "vite build",
    "preview": "vite preview",
    "check": "svelte-kit sync && svelte-check --tsconfig ./tsconfig.json",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "@sveltejs/adapter-static": "^3.0.8",
    "@sveltejs/kit": "^2.15.0",
    "@sveltejs/vite-plugin-svelte": "^5.0.0",
    "@testing-library/svelte": "^5.2.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@types/node": "^22.10.0",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.0",
    "postcss": "^8.4.49",
    "svelte": "^5.15.0",
    "svelte-check": "^4.1.0",
    "tailwindcss": "^3.4.15",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2: Install**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm install
```

Expected: installs without errors. Shows `added N packages`. A `node_modules/` dir appears (gitignored).

- [ ] **Step 3: Write `svelte.config.js`**

Create `tools/bjj-app/web/svelte.config.js`:

```javascript
import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      fallback: 'index.html',
      precompress: false,
      strict: true
    }),
    alias: {
      $lib: 'src/lib'
    }
  }
};

export default config;
```

- [ ] **Step 4: Write `vite.config.ts`**

Create `tools/bjj-app/web/vite.config.ts`:

```typescript
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  resolve: {
    // Needed so Vitest picks the browser exports of Svelte 5 in jsdom tests.
    conditions: ['browser']
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['./tests/**/*.test.ts']
  }
});
```

- [ ] **Step 5: Write `tsconfig.json`**

Create `tools/bjj-app/web/tsconfig.json`:

```json
{
  "extends": "./.svelte-kit/tsconfig.json",
  "compilerOptions": {
    "allowJs": true,
    "checkJs": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "skipLibCheck": true,
    "sourceMap": true,
    "strict": true,
    "module": "NodeNext",
    "moduleResolution": "NodeNext"
  }
}
```

- [ ] **Step 6: Write `src/app.html`**

Create `tools/bjj-app/web/src/app.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <link rel="icon" href="%sveltekit.assets%/favicon.svg" type="image/svg+xml" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <meta name="theme-color" content="#0e1014" />
    <title>BJJ Review</title>
    %sveltekit.head%
  </head>
  <body class="bg-neutral-950 text-neutral-100 antialiased" data-sveltekit-preload-data="hover">
    <div style="display: contents">%sveltekit.body%</div>
  </body>
</html>
```

- [ ] **Step 7: Generate `.svelte-kit/tsconfig.json` (required for alias resolution)**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npx svelte-kit sync
```

Expected: creates `.svelte-kit/` dir.

- [ ] **Step 8: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/package.json tools/bjj-app/web/package-lock.json tools/bjj-app/web/svelte.config.js tools/bjj-app/web/vite.config.ts tools/bjj-app/web/tsconfig.json tools/bjj-app/web/src/app.html
git commit -m "feat(bjj-app): scaffold sveltekit frontend project"
```

---

### Task 12: Add Tailwind CSS with design tokens

**Files:**
- Create: `tools/bjj-app/web/tailwind.config.ts`
- Create: `tools/bjj-app/web/postcss.config.js`
- Create: `tools/bjj-app/web/src/app.css`

- [ ] **Step 1: Write `tailwind.config.ts`**

Create `tools/bjj-app/web/tailwind.config.ts`:

```typescript
import type { Config } from 'tailwindcss';

export default {
  content: ['./src/**/*.{html,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        // Category chip colours — match the approved mockup
        cat: {
          standing: '#b7bcc7',
          'guard-top': '#f0c958',
          'guard-bottom': '#7ba9e6',
          'dominant-top': '#7fc98d',
          'inferior-bottom': '#d89090',
          'leg-ent': '#f0965c',
          scramble: '#b083d8',
          pass: '#e6c47e',
          sub: '#8bd6a1'
        },
        player: {
          greig: '#f2f2f2',
          anthony: '#e36a6a'
        }
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'SF Pro Display',
          'Segoe UI',
          'system-ui',
          'sans-serif'
        ]
      }
    }
  },
  plugins: []
} satisfies Config;
```

- [ ] **Step 2: Write `postcss.config.js`**

Create `tools/bjj-app/web/postcss.config.js`:

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {}
  }
};
```

- [ ] **Step 3: Write `src/app.css`**

Create `tools/bjj-app/web/src/app.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  html {
    background-color: #0e1014;
    color: #e8e9ec;
  }
}
```

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tailwind.config.ts tools/bjj-app/web/postcss.config.js tools/bjj-app/web/src/app.css
git commit -m "feat(bjj-app): add tailwind with design tokens"
```

---

### Task 13: Write typed API client and types

**Files:**
- Create: `tools/bjj-app/web/src/lib/types.ts`
- Create: `tools/bjj-app/web/src/lib/api.ts`

- [ ] **Step 1: Write `src/lib/types.ts`**

Create `tools/bjj-app/web/src/lib/types.ts`:

```typescript
export type RollSummary = {
  path: string;
  title: string;
  date: string;
  partner: string | null;
  duration: string | null;
  result: string | null;
};
```

- [ ] **Step 2: Write `src/lib/api.ts`**

Create `tools/bjj-app/web/src/lib/api.ts`:

```typescript
import type { RollSummary } from './types';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
  }
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function listRolls(): Promise<RollSummary[]> {
  return request<RollSummary[]>('/api/rolls');
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/
git commit -m "feat(bjj-app): add typed api client and types"
```

---

### Task 14: Build the app shell (`+layout.svelte`)

**Files:**
- Create: `tools/bjj-app/web/src/routes/+layout.svelte`
- Create: `tools/bjj-app/web/src/routes/+layout.ts`

- [ ] **Step 1: Write `+layout.ts` (disables SSR for static adapter compatibility)**

Create `tools/bjj-app/web/src/routes/+layout.ts`:

```typescript
// SvelteKit static adapter with SPA fallback — render everything client-side.
export const ssr = false;
export const prerender = false;
```

- [ ] **Step 2: Write `+layout.svelte`**

Create `tools/bjj-app/web/src/routes/+layout.svelte`:

```svelte
<script lang="ts">
  import '../app.css';

  let { children } = $props();
</script>

<div class="min-h-screen flex flex-col">
  <header
    class="flex items-center justify-between px-6 py-4 border-b border-white/5 bg-white/[0.02]"
  >
    <a href="/" class="flex items-center gap-2">
      <div class="size-8 rounded-lg bg-white/10 grid place-items-center text-sm font-bold">
        B
      </div>
      <div>
        <div class="text-[15px] font-semibold tracking-tight">BJJ Review</div>
        <div class="text-[11px] text-white/50">Tempo Jiu Jitsu</div>
      </div>
    </a>
    <nav class="flex gap-1 text-sm">
      <a
        class="px-3 py-1.5 rounded-md hover:bg-white/5 text-white/70 hover:text-white transition-colors"
        href="/graph"
      >
        Graph
      </a>
      <a
        class="px-3 py-1.5 rounded-md bg-blue-500/15 text-blue-200 border border-blue-400/40"
        href="/new"
      >
        + New Roll
      </a>
    </nav>
  </header>

  <main class="flex-1 max-w-4xl w-full mx-auto px-4 sm:px-6 py-6">
    {@render children?.()}
  </main>

  <footer class="px-6 py-4 text-center text-[11px] text-white/35">
    Analyses powered by Claude Opus 4.7 via local CLI · v0.1.0
  </footer>
</div>
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/+layout.svelte tools/bjj-app/web/src/routes/+layout.ts
git commit -m "feat(bjj-app): add app shell layout"
```

---

### Task 15: Write failing test for the home page

**Files:**
- Create: `tools/bjj-app/web/tests/setup.ts`
- Create: `tools/bjj-app/web/tests/home.test.ts`

- [ ] **Step 1: Write `web/tests/setup.ts`**

Create `tools/bjj-app/web/tests/setup.ts`:

```typescript
import '@testing-library/jest-dom/vitest';
```

- [ ] **Step 2: Write `web/tests/home.test.ts`**

Create `tools/bjj-app/web/tests/home.test.ts`:

```typescript
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Page from '../src/routes/+page.svelte';

const sampleRolls = [
  {
    path: '/vault/Roll Log/2026-04-14 - sample.md',
    title: 'Roll 1: Greig vs Anthony — WIN by Submission',
    date: '2026-04-14',
    partner: 'Anthony',
    duration: '2:23',
    result: 'win_submission'
  },
  {
    path: '/vault/Roll Log/2026-04-01 - other.md',
    title: 'Other roll — continuation',
    date: '2026-04-01',
    partner: 'Bob',
    duration: '1:45',
    result: 'continuation'
  }
];

describe('Home page', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => sampleRolls
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders a list item for each roll returned by the API', async () => {
    render(Page);

    await waitFor(() => {
      expect(
        screen.getByText('Roll 1: Greig vs Anthony — WIN by Submission')
      ).toBeInTheDocument();
    });

    expect(screen.getByText('Other roll — continuation')).toBeInTheDocument();
    expect(screen.getByText('Anthony')).toBeInTheDocument();
    expect(screen.getByText('2:23')).toBeInTheDocument();
  });

  it('shows an empty-state message when no rolls are returned', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => []
      })
    );

    render(Page);

    await waitFor(() => {
      expect(screen.getByText(/No rolls analysed yet/i)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 3: Run the tests — they MUST fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected output: test run fails because `+page.svelte` doesn't exist yet.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/
git commit -m "test(bjj-app): add home page tests (failing — no implementation)"
```

---

### Task 16: Implement the home page

**Files:**
- Create: `tools/bjj-app/web/src/routes/+page.svelte`

- [ ] **Step 1: Write `+page.svelte`**

Create `tools/bjj-app/web/src/routes/+page.svelte`:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { listRolls } from '$lib/api';
  import type { RollSummary } from '$lib/types';

  let rolls = $state<RollSummary[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      rolls = await listRolls();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load rolls';
    } finally {
      loading = false;
    }
  });

  function resultBadgeClass(result: string | null): string {
    if (!result) return 'bg-white/5 text-white/60';
    if (result.startsWith('win')) return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40';
    if (result.startsWith('loss')) return 'bg-rose-500/15 text-rose-300 border-rose-500/40';
    return 'bg-white/5 text-white/60 border-white/10';
  }

  function resultLabel(result: string | null): string {
    if (!result) return 'unknown';
    return result.replace(/_/g, ' ');
  }
</script>

<section class="space-y-4">
  <div class="flex items-baseline justify-between">
    <h1 class="text-2xl font-semibold tracking-tight">Rolls</h1>
    <p class="text-sm text-white/50">
      {rolls.length} analysed
    </p>
  </div>

  {#if loading}
    <p class="text-white/50 text-sm">Loading rolls from vault…</p>
  {:else if error}
    <div class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
      <strong>Couldn't load rolls:</strong>
      {error}
    </div>
  {:else if rolls.length === 0}
    <div class="rounded-lg border border-white/10 bg-white/[0.02] p-8 text-center">
      <p class="text-white/70">No rolls analysed yet.</p>
      <p class="text-white/40 text-sm mt-2">
        Upload a video to get started — the <code>Roll Log/</code> folder in your vault is empty.
      </p>
    </div>
  {:else}
    <ul class="space-y-2">
      {#each rolls as roll (roll.path)}
        <li>
          <a
            href={`/review/${encodeURIComponent(roll.path)}`}
            class="block rounded-lg border border-white/8 bg-white/[0.02] hover:bg-white/[0.05] p-4 transition-colors"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <h2 class="text-base font-medium leading-tight truncate">{roll.title}</h2>
                <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/55">
                  <span>{roll.date}</span>
                  {#if roll.partner}<span>{roll.partner}</span>{/if}
                  {#if roll.duration}<span>{roll.duration}</span>{/if}
                </div>
              </div>
              <span
                class={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${resultBadgeClass(roll.result)}`}
              >
                {resultLabel(roll.result)}
              </span>
            </div>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</section>
```

- [ ] **Step 2: Run the tests — they MUST pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected output: `2 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/+page.svelte
git commit -m "feat(bjj-app): implement home page with roll list"
```

---

### Task 17: Add favicon and placeholder routes

**Files:**
- Create: `tools/bjj-app/web/static/favicon.svg`
- Create: `tools/bjj-app/web/src/routes/graph/+page.svelte`
- Create: `tools/bjj-app/web/src/routes/new/+page.svelte`

These routes are linked from the app shell — clicking them shouldn't 404, even though they're not functional in M1.

- [ ] **Step 1: Write `favicon.svg`**

Create `tools/bjj-app/web/static/favicon.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#0e1014"/>
  <text x="16" y="22" text-anchor="middle" font-family="system-ui, sans-serif" font-size="18" font-weight="700" fill="#e8e9ec">B</text>
</svg>
```

- [ ] **Step 2: Write `routes/graph/+page.svelte`**

Create `tools/bjj-app/web/src/routes/graph/+page.svelte`:

```svelte
<section class="space-y-4">
  <h1 class="text-2xl font-semibold tracking-tight">BJJ Graph</h1>
  <div class="rounded-lg border border-white/10 bg-white/[0.02] p-8 text-center">
    <p class="text-white/70">Coming in M5.</p>
    <p class="text-white/40 text-sm mt-2">
      The category-clustered position graph with both players' paths will live here.
    </p>
  </div>
</section>
```

- [ ] **Step 3: Write `routes/new/+page.svelte`**

Create `tools/bjj-app/web/src/routes/new/+page.svelte`:

```svelte
<section class="space-y-4">
  <h1 class="text-2xl font-semibold tracking-tight">New Roll</h1>
  <div class="rounded-lg border border-white/10 bg-white/[0.02] p-8 text-center">
    <p class="text-white/70">Video upload comes in M2.</p>
    <p class="text-white/40 text-sm mt-2">
      For now, the home page lists rolls that already exist in your Obsidian vault's <code>Roll Log/</code> folder.
    </p>
  </div>
</section>
```

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/static/favicon.svg tools/bjj-app/web/src/routes/graph/ tools/bjj-app/web/src/routes/new/
git commit -m "feat(bjj-app): add favicon and placeholder routes for /graph and /new"
```

---

### Task 18: Write dev and production run scripts

**Files:**
- Create: `tools/bjj-app/scripts/dev.sh`
- Create: `tools/bjj-app/scripts/run.sh`
- Modify: `tools/bjj-app/server/main.py` (serve static files in production when build dir exists)

- [ ] **Step 1: Update `server/main.py` to serve frontend build in production**

Replace the entire contents of `tools/bjj-app/server/main.py` with:

```python
"""FastAPI entrypoint — creates the app and wires routers + static frontend."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.api import rolls as rolls_api
from server.config import load_settings
from server.db import init_db


def create_app() -> FastAPI:
    settings = load_settings()
    init_db(settings.db_path)

    app = FastAPI(title="BJJ Review App", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(rolls_api.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Serve the built SvelteKit SPA when the build dir exists (production mode).
    # Must be mounted LAST so /api/* is matched first.
    if settings.frontend_build_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=settings.frontend_build_dir, html=True),
            name="frontend",
        )

    return app


app = create_app()
```

- [ ] **Step 2: Re-run backend tests to confirm nothing broke**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend -v
```

Expected: `5 passed`.

- [ ] **Step 3: Write `scripts/dev.sh`**

Create `tools/bjj-app/scripts/dev.sh`:

```bash
#!/usr/bin/env bash
# Run backend (FastAPI on :8000) and frontend (Vite on :5173) concurrently.
# Ctrl-C stops both.

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_ROOT"

if [ ! -d .venv ]; then
  echo "Error: .venv not found. Run: python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'"
  exit 1
fi

if [ ! -d web/node_modules ]; then
  echo "Error: web/node_modules not found. Run: cd web && npm install"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true' INT TERM EXIT

echo "Starting FastAPI backend on http://127.0.0.1:8000 ..."
uvicorn server.main:app --reload --host 127.0.0.1 --port 8000 &
pids+=($!)

echo "Starting SvelteKit frontend on http://127.0.0.1:5173 ..."
(cd web && npm run dev) &
pids+=($!)

echo
echo "Backend:  http://127.0.0.1:8000/api/health"
echo "Frontend: http://127.0.0.1:5173   (open this in your browser)"
echo
echo "Ctrl-C to stop both."
wait
```

- [ ] **Step 4: Write `scripts/run.sh`**

Create `tools/bjj-app/scripts/run.sh`:

```bash
#!/usr/bin/env bash
# Production mode: build the frontend, then start FastAPI binding to 0.0.0.0
# so your phone (on the same wifi) can reach it.

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_ROOT"

if [ ! -d .venv ]; then
  echo "Error: .venv not found. See scripts/dev.sh for setup."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Building frontend..."
(cd web && npm run build)

echo
echo "Starting production server on http://0.0.0.0:8000 ..."
echo "Local: http://127.0.0.1:8000"
echo "LAN:   http://$(ipconfig getifaddr en0 2>/dev/null || echo '<your-mac-ip>'):8000"
echo
exec uvicorn server.main:app --host 0.0.0.0 --port 8000
```

- [ ] **Step 5: Make scripts executable**

```bash
chmod +x /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/scripts/dev.sh
chmod +x /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/scripts/run.sh
```

- [ ] **Step 6: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/scripts/ tools/bjj-app/server/main.py
git commit -m "feat(bjj-app): add dev.sh and run.sh scripts; serve built frontend from backend"
```

---

### Task 19: End-to-end manual smoke test in dev mode

**Files:** None created — this is a manual verification step.

- [ ] **Step 1: Run dev mode**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
./scripts/dev.sh
```

Expected: backend starts on `:8000`, frontend starts on `:5173`.

- [ ] **Step 2: Open browser**

Open `http://127.0.0.1:5173` in your browser.

Expected: The home page renders with:
- Header with "BJJ Review / Tempo Jiu Jitsu" title.
- A list of your real Roll Log entries (e.g., "Greig vs Anthony — Roll 1"), sorted newest first.
- Each entry shows date, partner, duration, result badge.
- Clicking nav buttons takes you to `/graph` and `/new` placeholder pages.

- [ ] **Step 3: Verify API directly**

In another terminal:

```bash
curl -s http://127.0.0.1:5173/api/rolls | python -m json.tool | head -20
```

Expected: JSON array with your actual vault rolls. (The proxy from Vite to FastAPI is working.)

- [ ] **Step 4: Kill dev server**

Ctrl-C in the `./scripts/dev.sh` terminal.

- [ ] **Step 5: Run production mode**

```bash
./scripts/run.sh
```

Expected: builds frontend (takes ~15 seconds), then starts server on `0.0.0.0:8000`.

- [ ] **Step 6: Verify production**

Open `http://127.0.0.1:8000` (note: port 8000, not 5173).

Expected: Same home page, served from built static assets.

- [ ] **Step 7: Verify LAN reachability (from your phone)**

Note the LAN URL printed by `run.sh` (e.g., `http://192.168.1.50:8000`). On your iPhone connected to the same wifi, open Safari and visit that URL.

Expected: Home page loads on phone. Roll list renders. Both nav items work.

- [ ] **Step 8: Kill production server**

Ctrl-C.

- [ ] **Step 9: Optional — run the full test suite**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend -v
(cd web && npm test)
```

Expected: all green.

---

### Task 20: Write README for `tools/bjj-app/`

**Files:**
- Create: `tools/bjj-app/README.md`

- [ ] **Step 1: Write README**

Create `tools/bjj-app/README.md`:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/README.md
git commit -m "docs(bjj-app): add README with setup and run instructions"
```

---

## Completion criteria for M1

All of the following must be true:

1. Backend tests: `pytest tests/backend -v` → 5 passed.
2. Frontend tests: `npm test` (in `web/`) → 2 passed.
3. `./scripts/dev.sh` starts both servers; `http://127.0.0.1:5173` shows the home page with real roll list.
4. `./scripts/run.sh` builds the frontend and serves everything on `:8000` from one process.
5. The home page is reachable from your phone over local wifi at `http://<mac-lan-ip>:8000`.
6. Clicking "Graph" or "+ New Roll" navigates to placeholder pages (not 404s).
7. Repo has no untracked files under `tools/bjj-app/` other than the ignored `.venv`, `node_modules`, `.svelte-kit`, `build`, and `bjj-app.db`.

---

## Out of scope (next plans will cover)

| Plan | Covers |
|---|---|
| Plan 2 | M2 — video upload + MediaPipe pose pre-pass |
| Plan 3 | M3 — Claude CLI adapter (with image-passing spike first) |
| Plan 4 | M4 — annotations + vault markdown write-back |
| Plan 5 | M5 — graph page + mini graph widget |
| Plan 6 | M6 — summary step + PDF export |
| Plan 7 | M7 — PWA + mobile polish |
| Plan 8 | M8 — delete `tools/app.py` (Streamlit) |

Each subsequent plan will be drafted after the preceding milestone ships, so we can incorporate learnings.
