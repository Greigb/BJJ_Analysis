# BJJ App M2a — Video Upload + Review Page Skeleton

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Greig upload a BJJ video through the web UI, persist it under `assets/<roll_id>/source.mp4`, and view it on a `/review/[id]` page (video player + empty timeline placeholder). The timeline populates with pose-flagged moments in M2b, but by the end of M2a you can already drop a file in and watch it back in the app.

**Architecture:** Backend adds `POST /api/rolls` (multipart upload) and `GET /api/rolls/:id` (full roll detail) on the FastAPI app. Videos served via a `/assets/` StaticFiles mount (supports byte-range for scrubbing). Frontend gains a `/new` page (real upload form, replaces M1 placeholder) and a `/review/[id]` page (video + metadata + disabled "Analyse" button). OpenCV reads video duration on upload. MediaPipe is installed but unused until M2b.

**Tech Stack:** FastAPI multipart, OpenCV (`opencv-python-headless`), UUID4 roll ids, StaticFiles for video serving. Frontend: SvelteKit 2 dynamic route (`/review/[id]`), native `<video>` element, `FormData` upload via `fetch`.

**Scope (M2a only):**
- Python 3.12 venv rebuild (MediaPipe has no 3.14 wheels).
- New deps: `opencv-python-headless`, `Pillow`, `python-multipart`, `mediapipe` (not used until M2b — installed now to confirm the 3.12 env supports it).
- Backend: `POST /api/rolls`, `GET /api/rolls/:id`, `/assets/` static mount, db helpers.
- Frontend: upload form at `/new`, review page at `/review/[id]`, video player component, API wrappers.
- Tests: db helpers, upload endpoint, get endpoint, upload form, review page.
- Uses `assets/test_roll.mp4` as the integration smoke-test fixture.

**Explicitly out of scope (M2b covers):**
- Frame extraction.
- MediaPipe pose inference and pose-delta scoring.
- `POST /api/rolls/:id/analyse` SSE endpoint.
- Timeline population (stays an empty placeholder here).
- The "Analyse" button is rendered but disabled.

---

## File Structure

```
tools/bjj-app/
├── pyproject.toml                             # MODIFY: add opencv + mediapipe + multipart
├── .python-version                            # MODIFY: 3.11 → 3.12
├── server/
│   ├── main.py                                # MODIFY: mount /assets
│   ├── db.py                                  # MODIFY: add create_roll/get_roll helpers
│   ├── api/
│   │   └── rolls.py                           # MODIFY: add POST, GET :id; rename RollSummaryOut → Summary; add Detail
│   └── analysis/
│       └── video.py                           # CREATE: read duration via OpenCV
├── tests/backend/
│   ├── conftest.py                            # MODIFY: add shared fixtures (tmp project root with assets/)
│   ├── fixtures/short_video.mp4               # CREATE: 2s of blank frames for deterministic upload tests
│   ├── test_db.py                             # CREATE: create/get roll helpers
│   ├── test_api_upload.py                     # CREATE: POST /api/rolls contract
│   ├── test_api_get_roll.py                   # CREATE: GET /api/rolls/:id contract
│   └── test_video.py                          # CREATE: duration extraction
└── web/
    ├── src/
    │   ├── lib/
    │   │   ├── types.ts                       # MODIFY: add RollDetail
    │   │   └── api.ts                         # MODIFY: add createRoll, getRoll
    │   └── routes/
    │       ├── new/+page.svelte               # REPLACE: real upload form
    │       └── review/
    │           └── [id]/
    │               └── +page.svelte           # CREATE: review page with <video>
    └── tests/
        ├── new.test.ts                        # CREATE: upload form behaviour
        └── review.test.ts                     # CREATE: review page render
```

### Responsibilities

- `db.py` — owns all SQLite writes/reads. M2a adds `create_roll(cursor, **fields) -> row` and `get_roll(cursor, roll_id) -> row | None`. Keep these *pure* — they don't open connections, they accept a cursor/connection so tests can supply an in-memory DB.
- `analysis/video.py` — one function: `read_duration(path: Path) -> float`. OpenCV-only. Nothing else belongs here until M2b adds `extract_frames` alongside it.
- `api/rolls.py` — HTTP surface only. Delegates to `db` + `analysis.video`. No business logic lives here. Grows by ~40 lines.
- `/new` page — owns the form state and the POST call. Redirects on success.
- `/review/[id]` page — fetches the roll on mount, renders the static layout (video + metadata + disabled Analyse button). No analysis logic; that's M2b.

---

## Tasks

### Task 1: Rebuild Python venv on 3.12

**Files:**
- Modify: `tools/bjj-app/.python-version`
- Delete + recreate: `tools/bjj-app/.venv/`

- [ ] **Step 1: Update `.python-version`**

Replace the contents of `tools/bjj-app/.python-version` with exactly:

```
3.12
```

- [ ] **Step 2: Remove the existing 3.14 venv**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
rm -rf .venv
```

- [ ] **Step 3: Create a 3.12 venv**

```bash
/usr/local/bin/python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

Expected output: `Python 3.12.13` (or whatever 3.12.x is installed).

- [ ] **Step 4: Commit the version bump**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/.python-version
git commit -m "chore(bjj-app): pin python to 3.12 for mediapipe compat"
```

(The `.venv/` itself is gitignored; don't commit it.)

---

### Task 2: Add M2 dependencies

**Files:**
- Modify: `tools/bjj-app/pyproject.toml`

- [ ] **Step 1: Update `pyproject.toml` dependencies**

Replace the entire contents of `tools/bjj-app/pyproject.toml` with:

```toml
[project]
name = "bjj-app"
version = "0.1.0"
description = "Local BJJ roll review app — FastAPI backend"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "aiofiles>=24.1.0",
    "python-frontmatter>=1.1.0",
    "python-multipart>=0.0.12",
    "pydantic>=2.9.0",
    "opencv-python-headless>=4.10.0",
    "mediapipe>=0.10.18",
    "Pillow>=10.4.0",
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

- [ ] **Step 2: Install everything**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pip install -e ".[dev]"
```

This will take 1–3 minutes (MediaPipe is a large wheel, OpenCV too).

- [ ] **Step 3: Verify key imports**

```bash
python -c "import cv2, mediapipe, PIL; print('cv2', cv2.__version__); print('mp', mediapipe.__version__); print('PIL', PIL.__version__)"
```

Expected: three version lines print. If any ImportError, report BLOCKED.

- [ ] **Step 4: Re-run the M1 tests to confirm nothing broke**

```bash
pytest tests/backend -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/pyproject.toml
git commit -m "chore(bjj-app): add opencv, mediapipe, pillow, multipart for M2"
```

---

### Task 3: Create a deterministic test video fixture

**Files:**
- Create: `tools/bjj-app/tests/backend/fixtures/short_video.mp4`
- Create: `tools/bjj-app/tests/backend/fixtures/make_short_video.py` (one-shot generator, lives with fixture for reproducibility)

A real MP4 fixture is needed so upload + duration tests don't depend on ffmpeg or external video files. Generate a tiny, deterministic video once and commit it.

- [ ] **Step 1: Write the generator script**

Create `tools/bjj-app/tests/backend/fixtures/make_short_video.py`:

```python
"""One-shot: generate tests/backend/fixtures/short_video.mp4 via OpenCV.

Run once, commit the output. Regenerate only if the fixture format ever
needs to change.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).parent / "short_video.mp4"
WIDTH, HEIGHT, FPS, SECONDS = 64, 48, 10, 2


def main() -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(OUT), fourcc, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("OpenCV failed to open VideoWriter")

    for i in range(FPS * SECONDS):
        # Slowly shift a grey gradient so frames differ frame-to-frame.
        value = (i * 8) % 256
        frame = np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    if not OUT.exists() or OUT.stat().st_size == 0:
        raise RuntimeError("VideoWriter produced an empty file")

    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the fixture**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
python tests/backend/fixtures/make_short_video.py
```

Expected: prints `wrote .../short_video.mp4 (NNNN bytes)` with a non-zero byte count.

- [ ] **Step 3: Verify the fixture**

```bash
python -c "
import cv2
cap = cv2.VideoCapture('tests/backend/fixtures/short_video.mp4')
fps = cap.get(cv2.CAP_PROP_FPS)
n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
print(f'fps={fps} frames={n} duration={n/fps:.2f}s')
cap.release()
"
```

Expected: `fps=10.0 frames=20.0 duration=2.00s`.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/fixtures/make_short_video.py tools/bjj-app/tests/backend/fixtures/short_video.mp4
git commit -m "test(bjj-app): add deterministic short_video.mp4 fixture"
```

**Note:** the root `.gitignore` ignores `*.mp4`, but this fixture must be committed. Force-add if git ignores it:

```bash
git check-ignore -v tools/bjj-app/tests/backend/fixtures/short_video.mp4
# If it reports ignored, add with -f:
git add -f tools/bjj-app/tests/backend/fixtures/short_video.mp4
```

---

### Task 4: Write failing tests for `read_duration`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_video.py`

- [ ] **Step 1: Write the test**

Create `tools/bjj-app/tests/backend/test_video.py`:

```python
from pathlib import Path

import pytest

from server.analysis.video import read_duration

FIXTURE = Path(__file__).parent / "fixtures" / "short_video.mp4"


def test_read_duration_returns_seconds_for_short_video():
    duration = read_duration(FIXTURE)
    # Fixture is 2.0s but tolerate tiny OpenCV rounding.
    assert 1.8 <= duration <= 2.2


def test_read_duration_raises_on_nonexistent_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_duration(tmp_path / "nope.mp4")


def test_read_duration_raises_on_non_video_file(tmp_path: Path):
    bad = tmp_path / "text.mp4"
    bad.write_text("this is not a video")
    with pytest.raises(ValueError):
        read_duration(bad)
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_video.py -v
```

Expected: ImportError on `server.analysis.video`.

- [ ] **Step 3: Commit the failing tests**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_video.py
git commit -m "test(bjj-app): add read_duration tests (failing — no impl)"
```

---

### Task 5: Implement `read_duration`

**Files:**
- Create: `tools/bjj-app/server/analysis/video.py`

- [ ] **Step 1: Write `video.py`**

Create `tools/bjj-app/server/analysis/video.py`:

```python
"""Video metadata helpers — OpenCV-based."""
from __future__ import annotations

from pathlib import Path

import cv2


def read_duration(path: Path) -> float:
    """Return the duration of a video in seconds.

    Raises:
        FileNotFoundError: if the path does not exist.
        ValueError: if the file exists but can't be opened as a video.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Not a readable video: {path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or frames <= 0:
            raise ValueError(f"Video has no frames / unknown fps: {path}")

        return float(frames / fps)
    finally:
        cap.release()
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_video.py -v
```

Expected: `3 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/video.py
git commit -m "feat(bjj-app): add read_duration helper"
```

---

### Task 6: Write failing tests for db helpers

**Files:**
- Create: `tools/bjj-app/tests/backend/test_db.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_db.py`:

```python
import time
from pathlib import Path

import pytest

from server.db import connect, create_roll, get_roll, init_db


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def test_create_roll_inserts_and_returns_row(db):
    now = int(time.time())
    row = create_roll(
        db,
        id="roll-1",
        title="Test roll",
        date="2026-04-20",
        video_path="assets/roll-1/source.mp4",
        duration_s=123.4,
        partner="Anthony",
        result="unknown",
        created_at=now,
    )

    assert row["id"] == "roll-1"
    assert row["title"] == "Test roll"
    assert row["duration_s"] == 123.4
    assert row["result"] == "unknown"
    assert row["created_at"] == now


def test_get_roll_returns_inserted_row(db):
    now = int(time.time())
    create_roll(
        db,
        id="roll-2",
        title="Another",
        date="2026-04-20",
        video_path="assets/roll-2/source.mp4",
        duration_s=60.0,
        partner=None,
        result="unknown",
        created_at=now,
    )

    row = get_roll(db, "roll-2")
    assert row is not None
    assert row["id"] == "roll-2"
    assert row["partner"] is None


def test_get_roll_returns_none_for_unknown_id(db):
    assert get_roll(db, "does-not-exist") is None
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_db.py -v
```

Expected: ImportError on `create_roll` / `get_roll` from `server.db`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_db.py
git commit -m "test(bjj-app): add db helper tests (failing — no impl)"
```

---

### Task 7: Implement `create_roll` and `get_roll`

**Files:**
- Modify: `tools/bjj-app/server/db.py`

- [ ] **Step 1: Append helpers to `db.py`**

Append the following to the end of `tools/bjj-app/server/db.py`:

```python


def create_roll(
    conn,
    *,
    id: str,
    title: str,
    date: str,
    video_path: str,
    duration_s: float | None,
    partner: str | None,
    result: str,
    created_at: int,
) -> sqlite3.Row:
    """Insert a roll row and return it. Callers pass an open connection."""
    conn.execute(
        """
        INSERT INTO rolls (
            id, title, date, video_path, duration_s, partner,
            result, scores_json, finalised_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
        """,
        (id, title, date, video_path, duration_s, partner, result, created_at),
    )
    conn.commit()
    return get_roll(conn, id)  # type: ignore[return-value]


def get_roll(conn, roll_id: str) -> sqlite3.Row | None:
    """Return the roll row, or None if not found."""
    cur = conn.execute("SELECT * FROM rolls WHERE id = ?", (roll_id,))
    return cur.fetchone()
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_db.py -v
```

Expected: `3 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py
git commit -m "feat(bjj-app): add create_roll and get_roll db helpers"
```

---

### Task 8: Extract shared API test helpers into conftest

**Files:**
- Modify: `tools/bjj-app/tests/backend/conftest.py`

The upcoming upload/get tests need a reusable "project root with assets dir writable" fixture. Add it now before either test file references it.

- [ ] **Step 1: Replace `conftest.py` with the new version**

Replace the entire contents of `tools/bjj-app/tests/backend/conftest.py` with:

```python
from pathlib import Path

import pytest


@pytest.fixture
def sample_vault() -> Path:
    """Path to the fixture vault used by vault.py tests."""
    return Path(__file__).parent / "fixtures" / "sample_vault"


@pytest.fixture
def short_video_path() -> Path:
    """Path to the committed short_video.mp4 fixture (2s, 10fps, 64×48)."""
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


@pytest.fixture
def tmp_project_root(tmp_path: Path) -> Path:
    """A writable project root with an empty assets/ dir for upload tests."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "Roll Log").mkdir()
    return tmp_path
```

- [ ] **Step 2: Confirm vault tests still pass (the original `sample_vault` fixture is unchanged)**

```bash
pytest tests/backend/test_vault.py -v
```

Expected: `3 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/conftest.py
git commit -m "test(bjj-app): add short_video and tmp_project_root fixtures"
```

---

### Task 9: Write failing test for `POST /api/rolls`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_upload.py`

- [ ] **Step 1: Write the test**

Create `tools/bjj-app/tests/backend/test_api_upload.py`:

```python
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_post_rolls_uploads_video_and_returns_roll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with short_video_path.open("rb") as f:
            response = await client.post(
                "/api/rolls",
                files={"video": ("short.mp4", f, "video/mp4")},
                data={"title": "Smoke roll", "date": "2026-04-20", "partner": "Anthony"},
            )

    assert response.status_code == 201, response.text
    body = response.json()

    assert "id" in body
    assert body["title"] == "Smoke roll"
    assert body["date"] == "2026-04-20"
    assert body["partner"] == "Anthony"
    assert body["result"] == "unknown"
    # Duration from the 2s fixture, allowing OpenCV rounding slack.
    assert 1.8 <= body["duration_s"] <= 2.2

    # Video physically stored under assets/<id>/source.mp4
    video_file = tmp_project_root / "assets" / body["id"] / "source.mp4"
    assert video_file.exists()
    assert video_file.stat().st_size > 0


@pytest.mark.asyncio
async def test_post_rolls_rejects_non_video_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()

    bad_file = tmp_project_root / "not-video.mp4"
    bad_file.write_bytes(b"not actually a video")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with bad_file.open("rb") as f:
            response = await client.post(
                "/api/rolls",
                files={"video": ("bad.mp4", f, "video/mp4")},
                data={"title": "Bad upload", "date": "2026-04-20"},
            )

    assert response.status_code == 400
    body = response.json()
    assert "detail" in body
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_upload.py -v
```

Expected: either 404 (route not registered) or 422 (method/shape mismatch) or an import error. Any of these is acceptable — what matters is the two tests are red.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_upload.py
git commit -m "test(bjj-app): add POST /api/rolls tests (failing — no impl)"
```

---

### Task 10: Implement `POST /api/rolls`

**Files:**
- Modify: `tools/bjj-app/server/api/rolls.py`

- [ ] **Step 1: Replace `rolls.py` with the expanded version**

Replace the entire contents of `tools/bjj-app/server/api/rolls.py` with:

```python
"""Rolls API — list summaries, create (upload) a new roll."""
from __future__ import annotations

import shutil
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from server.analysis.vault import RollSummary, list_rolls
from server.analysis.video import read_duration
from server.config import Settings, load_settings
from server.db import connect, create_roll


class RollSummaryOut(BaseModel):
    """Compact shape for the home page roll list."""

    id: str
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None

    @classmethod
    def from_vault(cls, r: RollSummary) -> "RollSummaryOut":
        return cls(
            id=r.id,
            title=r.title,
            date=r.date,
            partner=r.partner,
            duration=r.duration,
            result=r.result,
        )


class RollDetailOut(BaseModel):
    """Full roll shape used by POST /api/rolls response and GET /api/rolls/:id."""

    id: str
    title: str
    date: str
    partner: str | None
    duration_s: float | None
    result: str
    video_url: str


router = APIRouter(prefix="/api", tags=["rolls"])


@router.get("/rolls", response_model=list[RollSummaryOut])
def get_rolls(settings: Settings = Depends(load_settings)) -> list[RollSummaryOut]:
    return [RollSummaryOut.from_vault(r) for r in list_rolls(settings.vault_root)]


@router.post(
    "/rolls",
    response_model=RollDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_roll(
    video: UploadFile = File(...),
    title: str = Form(...),
    date: str = Form(...),
    partner: str | None = Form(default=None),
    settings: Settings = Depends(load_settings),
) -> RollDetailOut:
    roll_id = uuid.uuid4().hex
    roll_dir = settings.project_root / "assets" / roll_id
    roll_dir.mkdir(parents=True, exist_ok=False)
    video_path = roll_dir / "source.mp4"

    # Stream to disk so large uploads don't hold memory.
    with video_path.open("wb") as out:
        shutil.copyfileobj(video.file, out)

    # Validate it's a real video before we persist a row.
    try:
        duration_s = read_duration(video_path)
    except (ValueError, FileNotFoundError) as exc:
        # Clean up the bad upload.
        shutil.rmtree(roll_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Uploaded file is not a readable video: {exc}",
        ) from exc

    relative_video_path = f"assets/{roll_id}/source.mp4"
    with connect(settings.db_path) as conn:
        create_roll(
            conn,
            id=roll_id,
            title=title,
            date=date,
            video_path=relative_video_path,
            duration_s=duration_s,
            partner=partner,
            result="unknown",
            created_at=int(time.time()),
        )

    return RollDetailOut(
        id=roll_id,
        title=title,
        date=date,
        partner=partner,
        duration_s=duration_s,
        result="unknown",
        video_url=f"/assets/{roll_id}/source.mp4",
    )
```

- [ ] **Step 2: Run upload tests — must pass**

```bash
pytest tests/backend/test_api_upload.py -v
```

Expected: `2 passed`.

- [ ] **Step 3: Run the full backend suite — must stay green**

```bash
pytest tests/backend -v
```

Expected: `13 passed` (3 vault + 2 original api + 3 video + 3 db + 2 upload). Adjust count if you added/removed tests along the way, but nothing should *fail*.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/rolls.py
git commit -m "feat(bjj-app): add POST /api/rolls multipart upload endpoint"
```

---

### Task 11: Write failing test for `GET /api/rolls/:id`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_get_roll.py`

- [ ] **Step 1: Write the test**

Create `tools/bjj-app/tests/backend/test_api_get_roll.py`:

```python
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_get_roll_returns_detail_after_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Upload first, then fetch detail.
        with short_video_path.open("rb") as f:
            upload = await client.post(
                "/api/rolls",
                files={"video": ("short.mp4", f, "video/mp4")},
                data={"title": "Detail test", "date": "2026-04-20"},
            )
        assert upload.status_code == 201
        roll_id = upload.json()["id"]

        get = await client.get(f"/api/rolls/{roll_id}")

    assert get.status_code == 200
    body = get.json()
    assert body["id"] == roll_id
    assert body["title"] == "Detail test"
    assert body["date"] == "2026-04-20"
    assert body["partner"] is None
    assert 1.8 <= body["duration_s"] <= 2.2
    assert body["video_url"] == f"/assets/{roll_id}/source.mp4"
    assert body["result"] == "unknown"


@pytest.mark.asyncio
async def test_get_roll_returns_404_for_unknown_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/rolls/nonexistent-id")

    assert response.status_code == 404
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_get_roll.py -v
```

Expected: 404 on both (the route doesn't exist yet). The first test fails on the follow-up `get` call.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_get_roll.py
git commit -m "test(bjj-app): add GET /api/rolls/:id tests (failing — no impl)"
```

---

### Task 12: Implement `GET /api/rolls/:id`

**Files:**
- Modify: `tools/bjj-app/server/api/rolls.py`

- [ ] **Step 1: Append the GET-by-id route**

Add the following at the end of `tools/bjj-app/server/api/rolls.py`:

```python


@router.get("/rolls/{roll_id}", response_model=RollDetailOut)
def get_roll_detail(
    roll_id: str,
    settings: Settings = Depends(load_settings),
) -> RollDetailOut:
    from server.db import get_roll as db_get_roll  # local import to avoid top-level cycle

    with connect(settings.db_path) as conn:
        row = db_get_roll(conn, roll_id)

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found")

    return RollDetailOut(
        id=row["id"],
        title=row["title"],
        date=row["date"],
        partner=row["partner"],
        duration_s=row["duration_s"],
        result=row["result"],
        video_url=f"/{row['video_path']}",
    )
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_api_get_roll.py -v
```

Expected: `2 passed`.

- [ ] **Step 3: Run the full backend suite**

```bash
pytest tests/backend -v
```

Expected: all previously-passing tests still pass; new 2 also pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/rolls.py
git commit -m "feat(bjj-app): add GET /api/rolls/:id detail endpoint"
```

---

### Task 13: Mount `/assets/` static files route

**Files:**
- Modify: `tools/bjj-app/server/main.py`

For the review page's `<video>` to load the uploaded file, the browser must be able to fetch it at the `video_url` we return. Mount the project's `assets/` dir. StaticFiles handles Range requests for seeking.

- [ ] **Step 1: Replace `main.py`**

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

    # Serve uploaded videos at /assets/<id>/source.mp4. Created on demand —
    # only mount if the dir exists so dev-fresh installs don't 500 on startup.
    assets_dir = settings.project_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/assets",
        StaticFiles(directory=assets_dir, check_dir=False),
        name="assets",
    )

    # Serve the built SvelteKit SPA when the build dir exists (production mode).
    # Must be mounted LAST so /api/* and /assets/* are matched first.
    if settings.frontend_build_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=settings.frontend_build_dir, html=True),
            name="frontend",
        )

    return app


app = create_app()
```

- [ ] **Step 2: Add a test that verifies video is served**

Append to `tools/bjj-app/tests/backend/test_api_get_roll.py`:

```python


@pytest.mark.asyncio
async def test_uploaded_video_is_served_at_video_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with short_video_path.open("rb") as f:
            upload = await client.post(
                "/api/rolls",
                files={"video": ("short.mp4", f, "video/mp4")},
                data={"title": "Served", "date": "2026-04-20"},
            )
        roll_id = upload.json()["id"]
        video_url = upload.json()["video_url"]

        response = await client.get(video_url)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/")
    assert int(response.headers.get("content-length", "0")) > 0
```

- [ ] **Step 3: Run tests — full suite must pass**

```bash
pytest tests/backend -v
```

Expected: all green, including the new served-video test.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/main.py tools/bjj-app/tests/backend/test_api_get_roll.py
git commit -m "feat(bjj-app): mount /assets for uploaded video serving"
```

---

### Task 14: Frontend — add RollDetail type and API client methods

**Files:**
- Modify: `tools/bjj-app/web/src/lib/types.ts`
- Modify: `tools/bjj-app/web/src/lib/api.ts`

- [ ] **Step 1: Update `types.ts`**

Replace the entire contents of `tools/bjj-app/web/src/lib/types.ts` with:

```typescript
export type RollSummary = {
  id: string;
  title: string;
  date: string;
  partner: string | null;
  duration: string | null;
  result: string | null;
};

export type RollDetail = {
  id: string;
  title: string;
  date: string;
  partner: string | null;
  duration_s: number | null;
  result: string;
  video_url: string;
};

export type CreateRollInput = {
  title: string;
  date: string;
  partner?: string;
  video: File;
};
```

- [ ] **Step 2: Update `api.ts`**

Replace the entire contents of `tools/bjj-app/web/src/lib/api.ts` with:

```typescript
import type { CreateRollInput, RollDetail, RollSummary } from './types';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.headers ?? {})
    }
  });
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function listRolls(): Promise<RollSummary[]> {
  return request<RollSummary[]>('/api/rolls');
}

export function getRoll(id: string): Promise<RollDetail> {
  return request<RollDetail>(`/api/rolls/${encodeURIComponent(id)}`);
}

export function createRoll(input: CreateRollInput): Promise<RollDetail> {
  const form = new FormData();
  form.append('title', input.title);
  form.append('date', input.date);
  if (input.partner) form.append('partner', input.partner);
  form.append('video', input.video);

  return request<RollDetail>('/api/rolls', {
    method: 'POST',
    body: form
  });
}
```

- [ ] **Step 3: Frontend tests from M1 should still pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: `2 passed` (the existing home page tests).

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/
git commit -m "feat(bjj-app): add RollDetail, createRoll, getRoll api client"
```

---

### Task 15: Frontend — write failing test for `/new` upload form

**Files:**
- Create: `tools/bjj-app/web/tests/new.test.ts`

- [ ] **Step 1: Write the test**

Create `tools/bjj-app/web/tests/new.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Page from '../src/routes/new/+page.svelte';

// vi.mock factories are hoisted, so any variables they reference must also be
// hoisted via vi.hoisted. Otherwise mockGoto would be `undefined` at mock time.
const { mockGoto } = vi.hoisted(() => ({ mockGoto: vi.fn() }));

vi.mock('$app/navigation', () => ({
  goto: mockGoto
}));

describe('New Roll page', () => {
  beforeEach(() => {
    mockGoto.mockReset();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        statusText: 'Created',
        json: async () => ({
          id: 'new-roll-id',
          title: 'Uploaded',
          date: '2026-04-20',
          partner: null,
          duration_s: 2.0,
          result: 'unknown',
          video_url: '/assets/new-roll-id/source.mp4'
        })
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows the upload form', () => {
    render(Page);
    expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/date/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/partner/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/video file/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload/i })).toBeInTheDocument();
  });

  it('posts multipart form-data and redirects to the review page on success', async () => {
    const user = userEvent.setup();
    render(Page);

    await user.type(screen.getByLabelText(/title/i), 'My roll');
    // Date input has a default today-value; the test just asserts it gets sent.
    await user.type(screen.getByLabelText(/partner/i), 'Anthony');

    const file = new File(['fake video bytes'], 'roll.mp4', { type: 'video/mp4' });
    const fileInput = screen.getByLabelText(/video file/i) as HTMLInputElement;
    await user.upload(fileInput, file);

    await user.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/rolls',
        expect.objectContaining({ method: 'POST' })
      );
    });

    await waitFor(() => {
      expect(mockGoto).toHaveBeenCalledWith('/review/new-roll-id');
    });
  });

  it('shows an error when the upload fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        json: async () => ({ detail: 'Not a video' })
      })
    );
    const user = userEvent.setup();
    render(Page);

    await user.type(screen.getByLabelText(/title/i), 'Bad');
    const file = new File(['x'], 'x.mp4', { type: 'video/mp4' });
    await user.upload(screen.getByLabelText(/video file/i) as HTMLInputElement, file);
    await user.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => {
      expect(screen.getByText(/upload failed/i)).toBeInTheDocument();
    });
    expect(mockGoto).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Install `@testing-library/user-event`**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm install --save-dev @testing-library/user-event@^14.5.0
```

- [ ] **Step 3: Run — must fail**

```bash
npm test
```

Expected: the 3 new-page tests fail (they hit the M1 placeholder page, which has no form inputs); the 2 home-page tests still pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/new.test.ts tools/bjj-app/web/package.json tools/bjj-app/web/package-lock.json
git commit -m "test(bjj-app): add /new upload form tests (failing — placeholder only)"
```

---

### Task 16: Frontend — implement the `/new` upload form

**Files:**
- Replace: `tools/bjj-app/web/src/routes/new/+page.svelte`

- [ ] **Step 1: Replace the placeholder with the real form**

Replace the entire contents of `tools/bjj-app/web/src/routes/new/+page.svelte` with:

```svelte
<script lang="ts">
  import { goto } from '$app/navigation';
  import { createRoll, ApiError } from '$lib/api';

  const today = new Date().toISOString().slice(0, 10);

  let title = $state('');
  let date = $state(today);
  let partner = $state('');
  let file = $state<File | null>(null);
  let submitting = $state(false);
  let error = $state<string | null>(null);

  function onFileChange(event: Event) {
    const input = event.target as HTMLInputElement;
    file = input.files?.[0] ?? null;
  }

  async function onSubmit(event: Event) {
    event.preventDefault();
    if (!file || submitting) return;
    submitting = true;
    error = null;
    try {
      const roll = await createRoll({
        title: title || `Roll ${date}`,
        date,
        partner: partner || undefined,
        video: file
      });
      await goto(`/review/${encodeURIComponent(roll.id)}`);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      error = `Upload failed: ${msg}`;
      submitting = false;
    }
  }
</script>

<section class="space-y-6 max-w-xl">
  <h1 class="text-2xl font-semibold tracking-tight">New Roll</h1>

  <form class="space-y-5" onsubmit={onSubmit}>
    <label class="block space-y-1">
      <span class="text-sm text-white/70">Title</span>
      <input
        type="text"
        placeholder={`Roll ${date}`}
        bind:value={title}
        class="w-full rounded-md bg-white/5 border border-white/10 px-3 py-2 text-sm focus:outline-none focus:border-blue-400/50"
      />
    </label>

    <label class="block space-y-1">
      <span class="text-sm text-white/70">Date</span>
      <input
        type="date"
        bind:value={date}
        required
        class="w-full rounded-md bg-white/5 border border-white/10 px-3 py-2 text-sm focus:outline-none focus:border-blue-400/50"
      />
    </label>

    <label class="block space-y-1">
      <span class="text-sm text-white/70">Partner</span>
      <input
        type="text"
        placeholder="e.g. Anthony"
        bind:value={partner}
        class="w-full rounded-md bg-white/5 border border-white/10 px-3 py-2 text-sm focus:outline-none focus:border-blue-400/50"
      />
    </label>

    <label class="block space-y-1">
      <span class="text-sm text-white/70">Video file</span>
      <input
        type="file"
        accept="video/*"
        onchange={onFileChange}
        required
        class="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-white/10 file:bg-white/5 file:px-3 file:py-1.5 file:text-white/80 hover:file:bg-white/10"
      />
    </label>

    {#if error}
      <div class="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
        {error}
      </div>
    {/if}

    <button
      type="submit"
      disabled={!file || submitting}
      class="rounded-md bg-blue-500/20 border border-blue-400/40 text-blue-100 px-4 py-2 text-sm font-medium hover:bg-blue-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
    >
      {submitting ? 'Uploading…' : 'Upload'}
    </button>
  </form>
</section>
```

- [ ] **Step 2: Run frontend tests — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: `5 passed` (2 home + 3 new).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/new/+page.svelte
git commit -m "feat(bjj-app): implement /new upload form"
```

---

### Task 17: Frontend — write failing test for `/review/[id]`

**Files:**
- Create: `tools/bjj-app/web/tests/review.test.ts`

- [ ] **Step 1: Write the test**

Create `tools/bjj-app/web/tests/review.test.ts`:

```typescript
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Page from '../src/routes/review/[id]/+page.svelte';

const sampleDetail = {
  id: 'abc123',
  title: 'Roll vs Anthony',
  date: '2026-04-20',
  partner: 'Anthony',
  duration_s: 143.2,
  result: 'unknown',
  video_url: '/assets/abc123/source.mp4'
};

// Minimal readable-store shape — avoids importing svelte/store inside a hoisted factory.
vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: { params: { id: string } }) => void) => {
      run({ params: { id: 'abc123' } });
      return () => {};
    }
  }
}));

describe('Review page', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => sampleDetail
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('fetches the roll detail and renders metadata', async () => {
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Roll vs Anthony')).toBeInTheDocument();
    });

    expect(screen.getByText('Anthony')).toBeInTheDocument();
    expect(screen.getByText('2026-04-20')).toBeInTheDocument();
    // Duration rendered as M:SS.
    expect(screen.getByText('2:23')).toBeInTheDocument();
  });

  it('renders a <video> element pointing at the returned video_url', async () => {
    render(Page);

    await waitFor(() => {
      const video = document.querySelector('video');
      expect(video).not.toBeNull();
      expect(video?.querySelector('source')?.getAttribute('src')).toBe(
        '/assets/abc123/source.mp4'
      );
    });
  });

  it('renders a placeholder timeline and a disabled Analyse button', async () => {
    render(Page);

    await waitFor(() => {
      expect(screen.getByText(/timeline populates after analysis/i)).toBeInTheDocument();
    });

    const button = screen.getByRole('button', { name: /analyse/i });
    expect(button).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run — must fail (route doesn't exist)**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: the 3 review tests fail with an import error (the `[id]/+page.svelte` file doesn't exist yet).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/review.test.ts
git commit -m "test(bjj-app): add /review/[id] page tests (failing — no impl)"
```

---

### Task 18: Frontend — implement `/review/[id]`

**Files:**
- Create: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`
- Create: `tools/bjj-app/web/src/routes/review/[id]/+page.ts` (route config — disables prerendering for dynamic segments under the static adapter)

- [ ] **Step 1: Write the route config**

Create `tools/bjj-app/web/src/routes/review/[id]/+page.ts`:

```typescript
// Dynamic id — must NOT prerender. Static adapter falls back to index.html for SPA routing.
export const prerender = false;
export const ssr = false;
```

- [ ] **Step 2: Write the review page**

Create `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { getRoll, ApiError } from '$lib/api';
  import type { RollDetail } from '$lib/types';

  let roll = $state<RollDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  onMount(async () => {
    const id = $page.params.id;
    try {
      roll = await getRoll(id);
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      loading = false;
    }
  });

  function formatDuration(seconds: number | null | undefined): string {
    if (!seconds) return '—';
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }
</script>

{#if loading}
  <p class="text-white/50 text-sm">Loading roll…</p>
{:else if error || !roll}
  <div class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
    <strong>Couldn't load roll:</strong>
    {error ?? 'Unknown error'}
  </div>
{:else}
  <section class="space-y-5">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold tracking-tight">{roll.title}</h1>
        <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-white/55">
          <span>{roll.date}</span>
          {#if roll.partner}<span>{roll.partner}</span>{/if}
          <span>{formatDuration(roll.duration_s)}</span>
        </div>
      </div>
      <div class="flex gap-2">
        <button
          type="button"
          disabled
          title="Pose pre-pass arrives in M2b"
          class="rounded-md px-3 py-1.5 text-xs font-medium bg-white/5 border border-white/10 text-white/50 cursor-not-allowed"
        >
          Analyse
        </button>
      </div>
    </header>

    <div class="rounded-lg overflow-hidden border border-white/8 bg-black">
      <video controls preload="metadata" class="w-full aspect-video bg-black">
        <source src={roll.video_url} type="video/mp4" />
        Your browser can't play this video file.
      </video>
    </div>

    <div class="rounded-lg border border-white/10 bg-white/[0.02] p-6 text-center">
      <p class="text-sm text-white/60">Timeline populates after analysis.</p>
      <p class="mt-1 text-xs text-white/35">
        Pose pre-pass + Claude Opus 4.7 moment analysis arrive in upcoming milestones.
      </p>
    </div>
  </section>
{/if}
```

- [ ] **Step 3: Run frontend tests — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: `8 passed` (2 home + 3 new + 3 review).

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/review/
git commit -m "feat(bjj-app): implement /review/[id] page (video + empty timeline)"
```

---

### Task 19: End-to-end smoke test (real video, real server)

**Files:** none — this is a manual verification step.

- [ ] **Step 1: Start dev mode**

In one terminal:

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
./scripts/dev.sh
```

- [ ] **Step 2: Upload `assets/test_roll.mp4` via the UI**

Open `http://127.0.0.1:5173/new` in your browser.

- Title: `Smoke test upload`
- Date: today
- Partner: (leave blank)
- Video file: `/Users/greigbradley/Desktop/BJJ_Analysis/assets/test_roll.mp4`

Click **Upload**.

Expected: you get redirected to `/review/<uuid>` and see the test roll's video playing (scrubbable with native controls). Title and date render. Analyse button is disabled.

- [ ] **Step 3: Verify the DB + filesystem**

In a new terminal:

```bash
ls /Users/greigbradley/Desktop/BJJ_Analysis/assets/ | head -20
```

Expected: a new UUID-named directory alongside the existing ones (e.g., `a1b2c3d4...`). Inside it: `source.mp4`.

```bash
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT id, title, date, duration_s FROM rolls ORDER BY created_at DESC LIMIT 1;"
```

Expected: one row matching your upload.

- [ ] **Step 4: Verify cross-navigation**

- Click the app logo / `/` — home page does NOT yet show uploaded rolls (M1 reads from the vault's `Roll Log/` folder, not from SQLite; the list-from-SQLite merger is a post-M2b cleanup). This is expected for now — note it but don't fix in M2a.
- Click browser back, then directly visit `/review/<your-roll-id>` — page still loads the uploaded roll from the API.

- [ ] **Step 5: Stop dev server**

Ctrl-C in the dev-server terminal.

- [ ] **Step 6: Clean up the smoke-test upload (optional)**

```bash
# Replace <roll-id> with the id you uploaded
rm -rf /Users/greigbradley/Desktop/BJJ_Analysis/assets/<roll-id>
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "DELETE FROM rolls WHERE id='<roll-id>';"
```

---

### Task 20: Update README with M2a status

**Files:**
- Modify: `tools/bjj-app/README.md`

- [ ] **Step 1: Update the README**

Replace the entire contents of `tools/bjj-app/README.md` with:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/README.md
git commit -m "docs(bjj-app): document M2a (upload + review skeleton)"
```

---

## Completion criteria for M2a

All of the following must be true:

1. `pytest tests/backend -v` → all green (≥13 tests).
2. `npm test` (in `web/`) → all green (≥8 tests).
3. Dev mode runs; uploading a video at `/new` redirects to `/review/<id>`.
4. Review page plays the uploaded video via the `<video>` element (seekable).
5. The "Analyse" button is rendered but disabled with a tooltip pointing at M2b.
6. New rolls land at `assets/<id>/source.mp4` and have rows in `bjj-app.db`.
7. Previously-passing M1 tests still pass.

---

## Out of scope (M2b will cover)

| Deliverable | Why deferred |
|---|---|
| Frame extraction | Needed for pose pre-pass; drives Task 1 of M2b. |
| MediaPipe integration | Large install; belongs in the milestone that actually uses it. |
| Pose delta scoring + moment flagging | Requires MediaPipe. |
| `POST /api/rolls/:id/analyse` with SSE | Only useful once we have moments to stream. |
| Timeline UI populated with chips | Placeholder here; real component in M2b. |
| Home page showing uploaded rolls alongside vault rolls | Design question ("merge view" vs "uploaded only tab") — revisit when we have ≥3 uploaded rolls to look at. |
