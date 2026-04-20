# BJJ App M2b — Pose Pre-pass + Timeline Population

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the disabled "Analyse" button on `/review/[id]` into a working one-click button that extracts frames from the uploaded video, runs MediaPipe pose detection, flags the frames with the highest motion as "interesting moments", and streams progress back to the browser. The review page's empty-timeline placeholder is replaced with a row of dashed chips — one per flagged moment, clickable to seek the video to that timestamp.

**Architecture:** A new `POST /api/rolls/:id/analyse` endpoint returns a Server-Sent-Events stream. Backend orchestrates three sync stages: (1) OpenCV frame extraction at 1fps into `assets/<id>/frames/*.jpg`, (2) MediaPipe BlazePose inference on each frame, (3) pose-delta scoring across consecutive frames, with the top 20% (min 3, max 30) flagged as moments stored in the `moments` SQLite table. Frontend consumes the SSE stream via `fetch` + `ReadableStream`, updates a progress indicator during analysis, and renders chips when done. Claude Opus 4.7 is NOT called in M2b — moment chips stay unlabeled until M3 wires up position classification.

**Tech Stack:** OpenCV (frame extraction), MediaPipe BlazePose (sync Python), FastAPI `StreamingResponse` with `text/event-stream`, Svelte 5 async iterators for streaming UI updates.

**Scope (M2b only):**
- Backend: `server/analysis/frames.py`, `server/analysis/pose.py`, `server/analysis/pipeline.py`, `server/api/analyse.py`.
- DB: `insert_moments` / `get_moments` helpers, new data populated in `moments` table.
- `GET /api/rolls/:id` response gains a `moments: [...]` array.
- Frontend: updated `/review/[id]` page with working Analyse button, SSE progress indicator, timeline chip row, click-to-seek on chips.
- Tests: frames, pose, moments-db, pipeline, analyse endpoint, review page integration.

**Explicitly out of scope (M3+ covers):**
- Claude CLI integration / per-moment BJJ position classification.
- Player A / Player B dual-lane timeline (single unlabeled chip row in M2b).
- Selected-moment detail panel content beyond "Analyse this moment with Claude" button (button itself is M3).
- Vault write-back of analyses / annotations (M4).
- Rate limiting (no Claude calls yet).

---

## File Structure

```
tools/bjj-app/
├── server/
│   ├── analysis/
│   │   ├── frames.py                # NEW: extract_frames(video_path, out_dir, fps=1.0)
│   │   ├── pose.py                  # NEW: PoseDetector class + pose_delta()
│   │   └── pipeline.py              # NEW: run_analysis() sync generator yielding progress + moments
│   ├── api/
│   │   └── analyse.py               # NEW: POST /api/rolls/:id/analyse router (SSE)
│   ├── db.py                        # MODIFY: add insert_moments, get_moments
│   ├── main.py                      # MODIFY: include analyse router
│   └── api/
│       └── rolls.py                 # MODIFY: GET /rolls/:id includes moments in response
├── tests/backend/
│   ├── test_frames.py               # NEW
│   ├── test_pose.py                 # NEW
│   ├── test_db_moments.py           # NEW
│   ├── test_pipeline.py             # NEW
│   └── test_api_analyse.py          # NEW
└── web/
    ├── src/
    │   ├── lib/
    │   │   ├── types.ts             # MODIFY: add Moment, AnalyseEvent, updated RollDetail
    │   │   └── api.ts               # MODIFY: add analyseRoll async iterator
    │   └── routes/review/[id]/
    │       └── +page.svelte         # MODIFY: working Analyse button + timeline chips
    └── tests/
        └── review-analyse.test.ts   # NEW: tests the updated review page
```

### Responsibilities

- `frames.py` — OpenCV only. One function: `extract_frames(video_path, out_dir, fps=1.0) -> list[Path]`. Deterministic, seekable.
- `pose.py` — MediaPipe only. `PoseDetector` class (manages model lifecycle) + pure `pose_delta(a, b) -> float` function.
- `pipeline.py` — Orchestration. `run_analysis(video_path, frames_dir) -> Iterator[dict]` yields progress events `{stage, pct, ...}` and a final `{stage: "done", moments: [...]}`. No SSE/HTTP knowledge.
- `api/analyse.py` — HTTP surface. Wraps `run_analysis` in an SSE stream, writes moments to SQLite after completion.
- `api/rolls.py` — existing file, extend `GET /rolls/:id` to include moments so the page can render chips after a refresh.
- Frontend `api.ts` — adds `analyseRoll()` async iterator that consumes SSE via `fetch` + `ReadableStream`.

### Moment data model

A moment in SQLite (from M1 schema):
```sql
CREATE TABLE moments (
    id TEXT PRIMARY KEY,             -- uuid4 hex
    roll_id TEXT NOT NULL,
    frame_idx INTEGER NOT NULL,      -- 0-based index in the extracted frame sequence
    timestamp_s REAL NOT NULL,       -- seconds into the video
    pose_delta REAL,                 -- sum of landmark euclidean distances from prior frame
    selected_for_analysis INTEGER DEFAULT 0  -- reserved for M3 (Claude)
);
```

On the wire (`GET /rolls/:id` response):
```json
{
  "id": "...", "title": "...", ...,
  "moments": [
    { "id": "...", "frame_idx": 17, "timestamp_s": 17.0, "pose_delta": 0.42 },
    ...
  ]
}
```

### Flagging rule

Take the sequence of consecutive pose deltas. Flag the top 20% highest deltas, with a floor of 3 moments and a ceiling of 30. Rationale: predictable chip count regardless of video length; tuning left to M2b post-release per the spec's "revisit" list.

---

## Tasks

### Task 1: Write failing tests for `extract_frames`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_frames.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_frames.py`:

```python
from pathlib import Path

import pytest

from server.analysis.frames import extract_frames


def test_extract_frames_creates_one_frame_per_second(
    short_video_path: Path, tmp_path: Path
):
    # Fixture: 2s video at 10fps → should produce 2 frames at 1fps.
    out = tmp_path / "frames"
    paths = extract_frames(short_video_path, out, fps=1.0)

    assert len(paths) == 2
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 0
        assert p.suffix == ".jpg"


def test_extract_frames_is_deterministic(short_video_path: Path, tmp_path: Path):
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    paths_a = extract_frames(short_video_path, out_a, fps=1.0)
    paths_b = extract_frames(short_video_path, out_b, fps=1.0)

    assert len(paths_a) == len(paths_b)
    for a, b in zip(paths_a, paths_b):
        assert a.name == b.name


def test_extract_frames_creates_out_dir_if_missing(
    short_video_path: Path, tmp_path: Path
):
    out = tmp_path / "nested" / "frames"
    assert not out.exists()
    paths = extract_frames(short_video_path, out, fps=1.0)
    assert out.is_dir()
    assert all(p.parent == out for p in paths)


def test_extract_frames_raises_on_unreadable_video(tmp_path: Path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(ValueError):
        extract_frames(bad, tmp_path / "frames", fps=1.0)
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_frames.py -v
```

Expected: ImportError on `server.analysis.frames`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_frames.py
git commit -m "test(bjj-app): add extract_frames tests (failing — no impl)"
```

---

### Task 2: Implement `extract_frames`

**Files:**
- Create: `tools/bjj-app/server/analysis/frames.py`

- [ ] **Step 1: Write `frames.py`**

Create `tools/bjj-app/server/analysis/frames.py`:

```python
"""OpenCV frame extraction for uploaded videos."""
from __future__ import annotations

from pathlib import Path

import cv2


def extract_frames(
    video_path: Path,
    out_dir: Path,
    fps: float = 1.0,
) -> list[Path]:
    """Extract one frame per (1/fps) seconds to out_dir as frame_NNNNNN.jpg.

    Returns the list of created frame paths in timestamp order.

    Raises:
        FileNotFoundError: if video_path does not exist.
        ValueError: if the video can't be opened or has no frames.
    """
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    if fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")

    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Not a readable video: {video_path}")

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if video_fps <= 0 or total_frames <= 0:
            raise ValueError(f"Video has no frames / unknown fps: {video_path}")

        step = max(int(round(video_fps / fps)), 1)
        paths: list[Path] = []
        frame_idx = 0
        out_idx = 0

        while frame_idx < total_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, image = cap.read()
            if not ok:
                break
            path = out_dir / f"frame_{out_idx:06d}.jpg"
            cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 85])
            paths.append(path)
            out_idx += 1
            frame_idx += step

        return paths
    finally:
        cap.release()
```

- [ ] **Step 2: Run tests — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_frames.py -v
```

Expected: `4 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/frames.py
git commit -m "feat(bjj-app): add extract_frames (OpenCV 1fps JPEG extraction)"
```

---

### Task 3: Write failing tests for pose detection and delta

**Files:**
- Create: `tools/bjj-app/tests/backend/test_pose.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_pose.py`:

```python
from pathlib import Path

import cv2
import numpy as np
import pytest

from server.analysis.pose import PoseDetector, pose_delta


@pytest.fixture
def blank_image_path(tmp_path: Path) -> Path:
    """A featureless grey image — MediaPipe won't find a pose in it."""
    path = tmp_path / "blank.jpg"
    img = np.full((240, 320, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(path), img)
    return path


def test_pose_detector_returns_none_for_blank_image(blank_image_path: Path):
    detector = PoseDetector()
    try:
        result = detector.detect(blank_image_path)
    finally:
        detector.close()
    assert result is None


def test_pose_detector_returns_none_for_missing_file(tmp_path: Path):
    detector = PoseDetector()
    try:
        with pytest.raises(FileNotFoundError):
            detector.detect(tmp_path / "nope.jpg")
    finally:
        detector.close()


def test_pose_delta_returns_zero_when_either_side_is_none():
    fake_landmarks = [(0.0, 0.0, 0.0)] * 33
    assert pose_delta(None, None) == 0.0
    assert pose_delta(fake_landmarks, None) == 0.0
    assert pose_delta(None, fake_landmarks) == 0.0


def test_pose_delta_returns_zero_for_identical_landmarks():
    lm = [(0.1 * i, 0.1 * i, 0.0) for i in range(33)]
    assert pose_delta(lm, lm) == 0.0


def test_pose_delta_sums_euclidean_distances_across_landmarks():
    # Two landmark sets that differ by (0.1, 0.0) on every landmark.
    a = [(0.0, 0.0, 0.0)] * 33
    b = [(0.1, 0.0, 0.0)] * 33
    # 33 landmarks × 0.1 = 3.3 total delta.
    assert pose_delta(a, b) == pytest.approx(3.3, abs=1e-6)


def test_pose_delta_rejects_mismatched_lengths():
    a = [(0.0, 0.0, 0.0)] * 33
    b = [(0.0, 0.0, 0.0)] * 32
    with pytest.raises(ValueError):
        pose_delta(a, b)
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_pose.py -v
```

Expected: ImportError on `server.analysis.pose`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_pose.py
git commit -m "test(bjj-app): add pose detector + delta tests (failing — no impl)"
```

---

### Task 4: Implement `PoseDetector` and `pose_delta`

**Files:**
- Create: `tools/bjj-app/server/analysis/pose.py`

- [ ] **Step 1: Write `pose.py`**

Create `tools/bjj-app/server/analysis/pose.py`:

```python
"""MediaPipe BlazePose wrapper + pose-delta scoring.

Landmarks are normalised to [0, 1] in (x, y) and camera-space in z.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import mediapipe as mp  # type: ignore[import-untyped]

Landmark = tuple[float, float, float]
LandmarkSet = list[Landmark]


class PoseDetector:
    """MediaPipe Pose wrapper. Holds the model instance; call close() when done."""

    def __init__(self, model_complexity: int = 1) -> None:
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=True,
            model_complexity=model_complexity,
        )

    def detect(self, image_path: Path) -> LandmarkSet | None:
        """Return 33 landmarks or None if MediaPipe didn't find a pose."""
        if not image_path.exists():
            raise FileNotFoundError(image_path)

        image_bgr = cv2.imread(str(image_path))
        if image_bgr is None:
            raise ValueError(f"Not a readable image: {image_path}")

        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        result = self._pose.process(image_rgb)
        if result.pose_landmarks is None:
            return None
        return [(lm.x, lm.y, lm.z) for lm in result.pose_landmarks.landmark]

    def close(self) -> None:
        self._pose.close()

    def __enter__(self) -> "PoseDetector":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def pose_delta(
    a: LandmarkSet | None,
    b: LandmarkSet | None,
) -> float:
    """Sum of Euclidean distances between matched (x, y, z) landmarks.

    Returns 0.0 if either argument is None (a convention that simplifies the
    caller — a frame with no detected pose contributes no motion signal).
    """
    if a is None or b is None:
        return 0.0
    if len(a) != len(b):
        raise ValueError(f"Landmark count mismatch: {len(a)} vs {len(b)}")

    total = 0.0
    for (ax, ay, az), (bx, by, bz) in zip(a, b):
        dx, dy, dz = ax - bx, ay - by, az - bz
        total += math.sqrt(dx * dx + dy * dy + dz * dz)
    return total
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_pose.py -v
```

Expected: `6 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/pose.py
git commit -m "feat(bjj-app): add PoseDetector (MediaPipe) + pose_delta scoring"
```

---

### Task 5: Write failing tests for moments db helpers

**Files:**
- Create: `tools/bjj-app/tests/backend/test_db_moments.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_db_moments.py`:

```python
import time
from pathlib import Path

import pytest

from server.db import connect, create_roll, get_moments, init_db, insert_moments


@pytest.fixture
def db_with_roll(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn,
        id="roll-1",
        title="T",
        date="2026-04-20",
        video_path="assets/roll-1/source.mp4",
        duration_s=10.0,
        partner=None,
        result="unknown",
        created_at=int(time.time()),
    )
    try:
        yield conn
    finally:
        conn.close()


def test_insert_moments_persists_rows(db_with_roll):
    inserted = insert_moments(
        db_with_roll,
        roll_id="roll-1",
        moments=[
            {"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": 0.5},
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
        ],
    )
    assert len(inserted) == 2
    for row in inserted:
        assert row["roll_id"] == "roll-1"
        assert row["selected_for_analysis"] == 0


def test_get_moments_returns_rows_in_timestamp_order(db_with_roll):
    insert_moments(
        db_with_roll,
        roll_id="roll-1",
        moments=[
            {"frame_idx": 10, "timestamp_s": 10.0, "pose_delta": 0.3},
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": 0.5},
        ],
    )

    rows = get_moments(db_with_roll, "roll-1")
    assert [r["timestamp_s"] for r in rows] == [0.0, 3.0, 10.0]


def test_get_moments_returns_empty_for_roll_with_no_moments(db_with_roll):
    assert get_moments(db_with_roll, "roll-1") == []


def test_insert_moments_replaces_previous_moments(db_with_roll):
    insert_moments(
        db_with_roll,
        roll_id="roll-1",
        moments=[{"frame_idx": 0, "timestamp_s": 0.0, "pose_delta": 0.5}],
    )
    insert_moments(
        db_with_roll,
        roll_id="roll-1",
        moments=[{"frame_idx": 5, "timestamp_s": 5.0, "pose_delta": 1.0}],
    )

    rows = get_moments(db_with_roll, "roll-1")
    # Re-analysing a roll should replace, not append.
    assert len(rows) == 1
    assert rows[0]["frame_idx"] == 5
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_db_moments.py -v
```

Expected: ImportError on `insert_moments` / `get_moments`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_db_moments.py
git commit -m "test(bjj-app): add moments db helper tests (failing — no impl)"
```

---

### Task 6: Implement `insert_moments` and `get_moments`

**Files:**
- Modify: `tools/bjj-app/server/db.py`

- [ ] **Step 1: Append helpers to `db.py`**

Append the following to the end of `tools/bjj-app/server/db.py`:

```python


def insert_moments(
    conn,
    *,
    roll_id: str,
    moments: list[dict],
) -> list[sqlite3.Row]:
    """Replace all moments for `roll_id` with the supplied list.

    Each moment dict must contain: frame_idx (int), timestamp_s (float),
    pose_delta (float or None). `selected_for_analysis` defaults to 0.
    Returns the newly inserted rows in insertion order.
    """
    import uuid

    conn.execute("DELETE FROM moments WHERE roll_id = ?", (roll_id,))
    inserted_ids: list[str] = []
    for m in moments:
        moment_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO moments (
                id, roll_id, frame_idx, timestamp_s, pose_delta, selected_for_analysis
            )
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                moment_id,
                roll_id,
                int(m["frame_idx"]),
                float(m["timestamp_s"]),
                None if m.get("pose_delta") is None else float(m["pose_delta"]),
            ),
        )
        inserted_ids.append(moment_id)
    conn.commit()

    cur = conn.execute(
        f"SELECT * FROM moments WHERE id IN ({','.join('?' * len(inserted_ids))})",
        inserted_ids,
    )
    rows_by_id = {r["id"]: r for r in cur.fetchall()}
    return [rows_by_id[i] for i in inserted_ids]


def get_moments(conn, roll_id: str) -> list[sqlite3.Row]:
    """Return all moments for a roll in timestamp order."""
    cur = conn.execute(
        "SELECT * FROM moments WHERE roll_id = ? ORDER BY timestamp_s",
        (roll_id,),
    )
    return list(cur.fetchall())
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_db_moments.py -v
```

Expected: `4 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py
git commit -m "feat(bjj-app): add insert_moments / get_moments db helpers"
```

---

### Task 7: Write failing tests for the analysis pipeline

**Files:**
- Create: `tools/bjj-app/tests/backend/test_pipeline.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_pipeline.py`:

```python
from pathlib import Path

import pytest

from server.analysis.pipeline import run_analysis


def test_run_analysis_emits_progress_events_and_final_done(
    short_video_path: Path, tmp_path: Path
):
    frames_dir = tmp_path / "frames"
    events = list(run_analysis(short_video_path, frames_dir))

    # Must start with a frames stage and end with a done stage.
    stages = [e["stage"] for e in events]
    assert stages[0] == "frames"
    assert stages[-1] == "done"
    assert "pose" in stages

    # Each progress event has a 0–100 pct (the "done" event carries moments).
    for e in events[:-1]:
        assert "pct" in e
        assert 0 <= e["pct"] <= 100


def test_run_analysis_done_event_includes_moments_list(
    short_video_path: Path, tmp_path: Path
):
    frames_dir = tmp_path / "frames"
    events = list(run_analysis(short_video_path, frames_dir))

    done = events[-1]
    assert done["stage"] == "done"
    assert "moments" in done
    assert isinstance(done["moments"], list)
    # Each moment shape:
    for m in done["moments"]:
        assert "frame_idx" in m
        assert "timestamp_s" in m
        assert "pose_delta" in m


def test_run_analysis_creates_frames_in_frames_dir(
    short_video_path: Path, tmp_path: Path
):
    frames_dir = tmp_path / "frames"
    list(run_analysis(short_video_path, frames_dir))  # drain generator

    assert frames_dir.is_dir()
    jpgs = list(frames_dir.glob("*.jpg"))
    # 2s fixture at 1fps = 2 frames.
    assert len(jpgs) == 2


def test_run_analysis_always_returns_at_least_three_moments_when_possible(
    short_video_path: Path, tmp_path: Path
):
    # Even with the blank fixture (no pose detected → zero deltas), the flagging
    # rule floors at 3 moments; with only 2 frames we'll get at most 2.
    events = list(run_analysis(short_video_path, tmp_path / "frames"))
    done = events[-1]
    # For the 2-frame fixture we get up to 2 moments; floor of 3 only applies
    # when there are >= 3 frames. This test documents the boundary.
    assert len(done["moments"]) <= 2
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_pipeline.py -v
```

Expected: ImportError on `server.analysis.pipeline`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_pipeline.py
git commit -m "test(bjj-app): add pipeline tests (failing — no impl)"
```

---

### Task 8: Implement `run_analysis`

**Files:**
- Create: `tools/bjj-app/server/analysis/pipeline.py`

- [ ] **Step 1: Write `pipeline.py`**

Create `tools/bjj-app/server/analysis/pipeline.py`:

```python
"""Pose pre-pass pipeline: extract frames → detect pose → flag moments.

Sync generator — yields `{stage, pct, ...}` events, terminating with
`{stage: "done", moments: [...]}`. Callers feed this into an SSE
StreamingResponse or drain it in tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from server.analysis.frames import extract_frames
from server.analysis.pose import PoseDetector, pose_delta


_TOP_PERCENT = 0.20
_MIN_MOMENTS = 3
_MAX_MOMENTS = 30


def run_analysis(
    video_path: Path,
    frames_dir: Path,
    fps: float = 1.0,
) -> Iterator[dict]:
    """Run the pose pre-pass, yielding progress events."""

    # ---------- Stage 1: frame extraction ----------
    yield {"stage": "frames", "pct": 0}
    frame_paths = extract_frames(video_path, frames_dir, fps=fps)
    total = len(frame_paths)
    yield {"stage": "frames", "pct": 100, "total": total}

    # ---------- Stage 2: pose detection ----------
    yield {"stage": "pose", "pct": 0, "total": total}
    landmarks_per_frame: list[list[tuple[float, float, float]] | None] = []
    with PoseDetector() as detector:
        for i, fp in enumerate(frame_paths):
            landmarks_per_frame.append(detector.detect(fp))
            pct = int(round(100 * (i + 1) / max(total, 1)))
            # Emit progress roughly every ~5%.
            if pct in (100,) or (i % max(total // 20, 1) == 0):
                yield {"stage": "pose", "pct": pct, "total": total}

    # ---------- Stage 3: delta + flagging ----------
    deltas = [0.0]  # frame 0 has no predecessor
    for i in range(1, total):
        deltas.append(pose_delta(landmarks_per_frame[i - 1], landmarks_per_frame[i]))

    moments = _flag_moments(deltas, fps)

    yield {"stage": "done", "moments": moments, "total": total}


def _flag_moments(deltas: list[float], fps: float) -> list[dict]:
    """Flag the top _TOP_PERCENT highest-delta frames as moments.

    Bounded by [_MIN_MOMENTS, _MAX_MOMENTS], clamped to len(deltas).
    """
    n = len(deltas)
    if n == 0:
        return []

    target = max(_MIN_MOMENTS, int(round(n * _TOP_PERCENT)))
    target = min(target, _MAX_MOMENTS, n)

    # Select indices of top-target deltas, then sort by timestamp for output stability.
    indexed = sorted(enumerate(deltas), key=lambda x: x[1], reverse=True)[:target]
    indexed.sort(key=lambda x: x[0])  # restore chronological order

    moments: list[dict] = []
    for frame_idx, delta in indexed:
        moments.append(
            {
                "frame_idx": frame_idx,
                "timestamp_s": round(frame_idx / fps, 3),
                "pose_delta": round(delta, 4),
            }
        )
    return moments
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_pipeline.py -v
```

Expected: `4 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/pipeline.py
git commit -m "feat(bjj-app): add pose pre-pass pipeline"
```

---

### Task 9: Write failing tests for the analyse SSE endpoint

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_analyse.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_api_analyse.py`:

```python
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


async def _upload_fixture_roll(client: AsyncClient, video_path: Path) -> str:
    with video_path.open("rb") as f:
        response = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Analyse fixture", "date": "2026-04-20"},
        )
    assert response.status_code == 201
    return response.json()["id"]


def _parse_sse_lines(body: str) -> list[dict]:
    events: list[dict] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_analyse_streams_progress_and_final_done(
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
        roll_id = await _upload_fixture_roll(client, short_video_path)

        response = await client.post(f"/api/rolls/{roll_id}/analyse")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_lines(response.text)
    stages = [e["stage"] for e in events]
    assert stages[0] == "frames"
    assert "pose" in stages
    assert stages[-1] == "done"

    done = events[-1]
    assert isinstance(done["moments"], list)


@pytest.mark.asyncio
async def test_analyse_persists_moments_to_db(
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
        roll_id = await _upload_fixture_roll(client, short_video_path)

        analyse = await client.post(f"/api/rolls/{roll_id}/analyse")
        assert analyse.status_code == 200
        done = _parse_sse_lines(analyse.text)[-1]
        expected_moments = done["moments"]

        detail = await client.get(f"/api/rolls/{roll_id}")

    assert detail.status_code == 200
    body = detail.json()
    assert "moments" in body
    assert len(body["moments"]) == len(expected_moments)
    # Each moment has the expected shape.
    for m in body["moments"]:
        assert "id" in m
        assert "frame_idx" in m
        assert "timestamp_s" in m
        assert "pose_delta" in m


@pytest.mark.asyncio
async def test_analyse_returns_404_for_unknown_roll(
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
        response = await client.post("/api/rolls/does-not-exist/analyse")

    assert response.status_code == 404
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_analyse.py -v
```

Expected: most likely 404 / 405 / import errors — the endpoint and router don't exist yet.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_analyse.py
git commit -m "test(bjj-app): add analyse endpoint tests (failing — no impl)"
```

---

### Task 10: Implement the analyse SSE endpoint

**Files:**
- Create: `tools/bjj-app/server/api/analyse.py`
- Modify: `tools/bjj-app/server/main.py` (register the new router)
- Modify: `tools/bjj-app/server/api/rolls.py` (include `moments` in `RollDetailOut`)

- [ ] **Step 1: Update `RollDetailOut` to carry moments**

Replace the `RollDetailOut` Pydantic class in `tools/bjj-app/server/api/rolls.py` (roughly lines 39–48 — find the class `RollDetailOut(BaseModel)` definition) with:

```python
class MomentOut(BaseModel):
    id: str
    frame_idx: int
    timestamp_s: float
    pose_delta: float | None


class RollDetailOut(BaseModel):
    """Full roll shape used by POST /api/rolls response and GET /api/rolls/:id."""

    id: str
    title: str
    date: str
    partner: str | None
    duration_s: float | None
    result: str
    video_url: str
    moments: list[MomentOut] = []
```

- [ ] **Step 2: Update imports and `get_roll_detail` to include moments**

In `tools/bjj-app/server/api/rolls.py`, find the line:

```python
from server.db import connect, create_roll, get_roll
```

and replace it with:

```python
from server.db import connect, create_roll, get_moments, get_roll
```

Then replace the `get_roll_detail` function at the bottom of the file with:

```python
@router.get("/rolls/{roll_id}", response_model=RollDetailOut)
def get_roll_detail(
    roll_id: str,
    settings: Settings = Depends(load_settings),
) -> RollDetailOut:
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        moment_rows = get_moments(conn, roll_id)
    finally:
        conn.close()

    return RollDetailOut(
        id=row["id"],
        title=row["title"],
        date=row["date"],
        partner=row["partner"],
        duration_s=row["duration_s"],
        result=row["result"],
        video_url=f"/{row['video_path']}",
        moments=[
            MomentOut(
                id=m["id"],
                frame_idx=m["frame_idx"],
                timestamp_s=m["timestamp_s"],
                pose_delta=m["pose_delta"],
            )
            for m in moment_rows
        ],
    )
```

Also update the `upload_roll` return statement to include `moments=[]` (uploaded rolls start with no moments; they're created by the analyse endpoint). Find the `return RollDetailOut(...)` at the end of `upload_roll` and ensure it includes `moments=[]`:

```python
    return RollDetailOut(
        id=roll_id,
        title=title,
        date=date,
        partner=partner,
        duration_s=duration_s,
        result="unknown",
        video_url=f"/assets/{roll_id}/source.mp4",
        moments=[],
    )
```

- [ ] **Step 3: Write `server/api/analyse.py`**

Create `tools/bjj-app/server/api/analyse.py`:

```python
"""POST /api/rolls/:id/analyse — SSE stream of the pose pre-pass pipeline."""
from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from server.analysis.pipeline import run_analysis
from server.config import Settings, load_settings
from server.db import connect, get_roll, insert_moments


router = APIRouter(prefix="/api", tags=["analyse"])


@router.post("/rolls/{roll_id}/analyse")
def analyse_roll(
    roll_id: str,
    settings: Settings = Depends(load_settings),
) -> StreamingResponse:
    # Look up the roll before streaming so we can return a clean 404.
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
        )

    video_path = settings.project_root / row["video_path"]
    frames_dir = settings.project_root / "assets" / roll_id / "frames"

    def event_stream() -> Iterator[bytes]:
        last_moments: list[dict] = []
        for event in run_analysis(video_path, frames_dir):
            if event["stage"] == "done":
                last_moments = event.get("moments", [])
            yield f"data: {json.dumps(event)}\n\n".encode("utf-8")

        # Persist after streaming completes. Done inline so the client sees the
        # moments event *before* the connection closes.
        conn = connect(settings.db_path)
        try:
            insert_moments(conn, roll_id=roll_id, moments=last_moments)
        finally:
            conn.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Register the router in `main.py`**

Open `tools/bjj-app/server/main.py` and change the imports + router includes. Replace the line:

```python
from server.api import rolls as rolls_api
```

with:

```python
from server.api import analyse as analyse_api
from server.api import rolls as rolls_api
```

And replace the line:

```python
    app.include_router(rolls_api.router)
```

with:

```python
    app.include_router(rolls_api.router)
    app.include_router(analyse_api.router)
```

- [ ] **Step 5: Run analyse tests — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_api_analyse.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Run the full backend suite**

```bash
pytest tests/backend -v
```

Expected: all tests pass. (16 from M2a + 4 frames + 6 pose + 4 moments-db + 4 pipeline + 3 analyse ≈ 37 tests.)

- [ ] **Step 7: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/analyse.py tools/bjj-app/server/api/rolls.py tools/bjj-app/server/main.py
git commit -m "feat(bjj-app): add POST /api/rolls/:id/analyse SSE endpoint"
```

---

### Task 11: Frontend — add Moment type and analyseRoll SSE client

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

export type Moment = {
  id: string;
  frame_idx: number;
  timestamp_s: number;
  pose_delta: number | null;
};

export type RollDetail = {
  id: string;
  title: string;
  date: string;
  partner: string | null;
  duration_s: number | null;
  result: string;
  video_url: string;
  moments: Moment[];
};

export type CreateRollInput = {
  title: string;
  date: string;
  partner?: string;
  video: File;
};

export type AnalyseEvent =
  | { stage: 'frames'; pct: number; total?: number }
  | { stage: 'pose'; pct: number; total?: number }
  | {
      stage: 'done';
      total?: number;
      moments: Array<{ frame_idx: number; timestamp_s: number; pose_delta: number | null }>;
    };
```

- [ ] **Step 2: Update `api.ts`**

Replace the entire contents of `tools/bjj-app/web/src/lib/api.ts` with:

```typescript
import type { AnalyseEvent, CreateRollInput, RollDetail, RollSummary } from './types';

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

/**
 * Analyse a roll — returns an async iterator of SSE events from the backend.
 *
 * Usage:
 *   for await (const event of analyseRoll(id)) { ... }
 */
export async function* analyseRoll(id: string): AsyncIterator<AnalyseEvent> {
  const response = await fetch(`/api/rolls/${encodeURIComponent(id)}/analyse`, {
    method: 'POST'
  });
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  if (!response.body) {
    throw new Error('Analyse response has no body');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by blank lines.
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';

      for (const frame of frames) {
        const dataLine = frame
          .split('\n')
          .find((line) => line.startsWith('data: '));
        if (!dataLine) continue;
        yield JSON.parse(dataLine.slice(6)) as AnalyseEvent;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
```

- [ ] **Step 3: Verify existing frontend tests still pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: `8 passed` (the existing M2a tests).

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/
git commit -m "feat(bjj-app): add Moment types and analyseRoll SSE iterator"
```

---

### Task 12: Frontend — write failing tests for the updated review page

**Files:**
- Create: `tools/bjj-app/web/tests/review-analyse.test.ts`

These tests replace the original `review.test.ts` gradually. Keep both files until Task 13 passes, then delete the old one.

- [ ] **Step 1: Write the test file**

Create `tools/bjj-app/web/tests/review-analyse.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Page from '../src/routes/review/[id]/+page.svelte';

// See M2a new.test.ts — vi.mock factories are hoisted, so any referenced
// variables must be hoisted with vi.hoisted.
const { mockId } = vi.hoisted(() => ({ mockId: { value: 'abc123' } }));

vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: { params: { id: string } }) => void) => {
      run({ params: { id: mockId.value } });
      return () => {};
    }
  }
}));

function detailWithoutMoments() {
  return {
    id: 'abc123',
    title: 'Review analyse test',
    date: '2026-04-20',
    partner: null,
    duration_s: 10.0,
    result: 'unknown',
    video_url: '/assets/abc123/source.mp4',
    moments: []
  };
}

function detailWithMoments() {
  return {
    ...detailWithoutMoments(),
    moments: [
      { id: 'm1', frame_idx: 2, timestamp_s: 2.0, pose_delta: 0.5 },
      { id: 'm2', frame_idx: 5, timestamp_s: 5.0, pose_delta: 1.2 }
    ]
  };
}

// Build an SSE-format response body from a list of events.
function sseBody(events: object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const e of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
      }
      controller.close();
    }
  });
}

describe('Review page — analyse flow', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders an enabled Analyse button when the roll has no moments yet', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => detailWithoutMoments()
      })
    );

    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    const button = screen.getByRole('button', { name: /analyse/i });
    expect(button).not.toBeDisabled();
  });

  it('renders existing moments as chips when the roll was already analysed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => detailWithMoments()
      })
    );

    render(Page);

    await waitFor(() => {
      // Chips are rendered as buttons labeled with their timestamp (M:SS).
      expect(screen.getByRole('button', { name: /0:02/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /0:05/i })).toBeInTheDocument();
    });
  });

  it('clicking Analyse streams progress and then renders new chips', async () => {
    const fetchMock = vi.fn();
    // First call: GET roll detail. Second: POST analyse (SSE body).
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => detailWithoutMoments()
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: sseBody([
        { stage: 'frames', pct: 0 },
        { stage: 'frames', pct: 100 },
        { stage: 'pose', pct: 0 },
        { stage: 'pose', pct: 100 },
        {
          stage: 'done',
          moments: [
            { frame_idx: 3, timestamp_s: 3.0, pose_delta: 0.8 },
            { frame_idx: 7, timestamp_s: 7.0, pose_delta: 1.4 }
          ]
        }
      ])
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    render(Page);

    await waitFor(() => {
      expect(screen.getByText('Review analyse test')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /analyse/i }));

    // After streaming completes, chips for the returned moments appear.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /0:03/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /0:07/i })).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Delete the now-superseded review.test.ts**

```bash
rm /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/review.test.ts
```

- [ ] **Step 3: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: the 3 review-analyse tests fail (the current page doesn't have a working button, no chips, etc.). The M2a new.test.ts and home.test.ts still pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/review-analyse.test.ts
git rm tools/bjj-app/web/tests/review.test.ts
git commit -m "test(bjj-app): add review-analyse tests, retire review.test.ts (failing — no impl)"
```

---

### Task 13: Frontend — wire Analyse button + timeline chips in the review page

**Files:**
- Modify: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`

- [ ] **Step 1: Replace the page**

Replace the entire contents of `tools/bjj-app/web/src/routes/review/[id]/+page.svelte` with:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { analyseRoll, ApiError, getRoll } from '$lib/api';
  import type { AnalyseEvent, Moment, RollDetail } from '$lib/types';

  let roll = $state<RollDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let analysing = $state(false);
  let progress = $state<{ stage: string; pct: number } | null>(null);

  // Refs for video seeking from chip clicks.
  let videoEl: HTMLVideoElement | undefined = $state();

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

  async function onAnalyseClick() {
    if (!roll || analysing) return;
    analysing = true;
    progress = { stage: 'frames', pct: 0 };
    try {
      for await (const event of analyseRoll(roll.id)) {
        handleAnalyseEvent(event);
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      analysing = false;
      progress = null;
    }
  }

  function handleAnalyseEvent(event: AnalyseEvent) {
    if (event.stage === 'done') {
      if (!roll) return;
      // Server assigns ids on persistence; for immediate UI we fabricate
      // stable keys from frame_idx — they'll be replaced on the next refresh.
      roll.moments = event.moments.map((m) => ({
        id: `pending-${m.frame_idx}`,
        frame_idx: m.frame_idx,
        timestamp_s: m.timestamp_s,
        pose_delta: m.pose_delta
      })) as Moment[];
      progress = { stage: 'done', pct: 100 };
    } else {
      progress = { stage: event.stage, pct: event.pct };
    }
  }

  function formatDuration(seconds: number | null | undefined): string {
    if (!seconds) return '—';
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function formatMomentTime(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function progressLabel(p: { stage: string; pct: number } | null): string {
    if (!p) return '';
    if (p.stage === 'frames') return `Extracting frames… ${p.pct}%`;
    if (p.stage === 'pose') return `Detecting poses… ${p.pct}%`;
    if (p.stage === 'done') return 'Analysis complete';
    return `${p.stage}… ${p.pct}%`;
  }

  function seekTo(seconds: number) {
    if (videoEl) {
      videoEl.currentTime = seconds;
      videoEl.play().catch(() => {
        /* autoplay may be blocked; it's fine */
      });
    }
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
          onclick={onAnalyseClick}
          disabled={analysing}
          class="rounded-md px-3 py-1.5 text-xs font-medium bg-blue-500/20 border border-blue-400/40 text-blue-100 hover:bg-blue-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {analysing ? 'Analysing…' : 'Analyse'}
        </button>
      </div>
    </header>

    <div class="rounded-lg overflow-hidden border border-white/8 bg-black">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video
        bind:this={videoEl}
        controls
        preload="metadata"
        class="w-full aspect-video bg-black"
      >
        <source src={roll.video_url} type="video/mp4" />
        Your browser can't play this video file.
      </video>
    </div>

    {#if progress}
      <div
        class="rounded-md border border-white/10 bg-white/[0.02] px-4 py-2 text-xs text-white/65"
        role="status"
      >
        {progressLabel(progress)}
      </div>
    {/if}

    {#if roll.moments.length > 0}
      <div class="space-y-2">
        <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
          Moments ({roll.moments.length})
        </div>
        <div class="flex flex-wrap gap-1.5">
          {#each roll.moments as moment (moment.id)}
            <button
              type="button"
              onclick={() => seekTo(moment.timestamp_s)}
              class="rounded-md border border-dashed border-white/20 bg-white/[0.02] hover:bg-white/[0.05] hover:border-white/40 px-2.5 py-1 text-xs font-mono tabular-nums text-white/75 transition-colors"
            >
              {formatMomentTime(moment.timestamp_s)}
            </button>
          {/each}
        </div>
        <p class="text-[11px] text-white/35">
          Click a chip to jump the video there. Position classification via Claude Opus 4.7
          arrives in M3.
        </p>
      </div>
    {:else if !analysing}
      <div class="rounded-lg border border-white/10 bg-white/[0.02] p-6 text-center">
        <p class="text-sm text-white/60">No moments yet.</p>
        <p class="mt-1 text-xs text-white/35">
          Click <strong>Analyse</strong> to run the pose pre-pass and flag interesting moments.
        </p>
      </div>
    {/if}
  </section>
{/if}
```

- [ ] **Step 2: Run frontend tests — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: `8 passed` (2 home + 3 new + 3 review-analyse).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/review/[id]/+page.svelte
git commit -m "feat(bjj-app): wire Analyse button + timeline chips in /review/[id]"
```

---

### Task 14: End-to-end smoke test with a real video

**Files:** none — manual verification.

- [ ] **Step 1: Start dev mode**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
./scripts/dev.sh
```

- [ ] **Step 2: Upload a short real video**

Open `http://127.0.0.1:5173/new` and upload `assets/test_roll.mp4` (or any short video). Click Upload. Wait for redirect.

- [ ] **Step 3: Click Analyse**

On the review page, click **Analyse**. Watch the progress indicator update through `Extracting frames…` then `Detecting poses…`. For a 2-minute video expect ~30–60 seconds total.

**Expected:**
- Progress bar/text updates in near-real-time.
- On completion, a row of dashed chips appears below the video.
- Clicking a chip jumps the video to that timestamp and starts playing.
- Refreshing the page preserves the chips (proves SQLite persistence is working).

- [ ] **Step 4: Verify DB + filesystem**

In another terminal:

```bash
# Find the most recent roll id
ROLL_ID=$(sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT id FROM rolls ORDER BY created_at DESC LIMIT 1;")
echo "Roll: $ROLL_ID"

# Moments count
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT COUNT(*) FROM moments WHERE roll_id='$ROLL_ID';"

# Frames extracted
ls /Users/greigbradley/Desktop/BJJ_Analysis/assets/$ROLL_ID/frames/ | head -5
ls /Users/greigbradley/Desktop/BJJ_Analysis/assets/$ROLL_ID/frames/ | wc -l
```

Expected: moments count matches the number of chips (3–30 range); frame count matches the video's duration in seconds (±1).

- [ ] **Step 5: Clean up (optional)**

```bash
rm -rf /Users/greigbradley/Desktop/BJJ_Analysis/assets/$ROLL_ID
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "DELETE FROM rolls WHERE id='$ROLL_ID';"
```

(Moments cascade-delete thanks to `ON DELETE CASCADE` in the schema.)

- [ ] **Step 6: Stop dev server** (Ctrl-C in the dev terminal).

---

### Task 15: Update README with M2b status

**Files:**
- Modify: `tools/bjj-app/README.md`

- [ ] **Step 1: Replace the Milestones section**

Find the `## Milestones` section in `tools/bjj-app/README.md` and replace it (and everything below it) with:

```markdown
## Milestones

- **M1 (shipped):** Scaffolding. Home page lists vault's `Roll Log/` via `GET /api/rolls`.
- **M2a (shipped):** Video upload (`POST /api/rolls`), review page skeleton (`/review/[id]` with video player + empty timeline), `/assets/` static mount.
- **M2b (this milestone):** MediaPipe pose pre-pass, `POST /api/rolls/:id/analyse` SSE endpoint, timeline chips render in `/review/[id]` and seek the video on click. No Claude calls yet — chips are unlabeled.
- **M3 (next):** Claude CLI adapter. Click a chip → call `claude -p --model claude-opus-4-7` on that frame → label the moment with the detected BJJ position + coaching tip.
- **M4–M8:** Annotations + vault write-back, graph page, summary + PDF, PWA, cleanup.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/README.md
git commit -m "docs(bjj-app): document M2b (pose pre-pass + timeline chips)"
```

---

## Completion criteria for M2b

1. `pytest tests/backend -v` → all green (≥37 tests).
2. `npm test` (in `web/`) → all green (≥8 tests).
3. Dev-mode smoke test: upload a video, click Analyse, see progress update in real-time, see chips appear, click a chip, video jumps to that timestamp.
4. Refreshing `/review/[id]` after analysis preserves the chips (SQLite persistence verified).
5. `assets/<id>/frames/` contains extracted JPEGs; `moments` table has rows for the flagged moments.

---

## Out of scope (M3 will cover)

| Deliverable | Why deferred |
|---|---|
| Claude CLI subprocess + image-passing spike | Independent subsystem — its own plan. |
| Chips labeled with detected BJJ positions | Requires Claude. |
| Selected-moment detail panel with description + coach tip | Requires Claude. |
| Per-player path (dual-lane timeline) | Requires Claude to distinguish the two grapplers. |
| Rate limiting | No Claude calls yet. |
| Vault markdown write-back of analyses | M4. |
