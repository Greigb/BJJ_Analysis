# BJJ App M3 — Claude CLI Adapter

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an unanalysed moment chip on `/review/[id]` into a Claude-classified BJJ position. Clicking a chip selects it; the detail panel shows an "Analyse this moment with Claude Opus 4.7" button; clicking that streams a position classification + description + coach tip back into the panel and writes it to SQLite. Re-clicking an already-analysed moment shows the saved result instantly.

**Architecture:** A single seam — `server/analysis/claude_cli.py` — owns every `claude -p` subprocess. The FastAPI endpoint `POST /api/rolls/:id/moments/:frame_idx/analyse` wraps this seam in an SSE stream, guarded by a sliding-window rate limiter (10 calls per 5-min rolling window) and backed by a `(frame_hash, prompt_hash) → JSON` cache in SQLite. Prompts are built by `server/analysis/prompt.py` from `tools/taxonomy.json`; frame images are passed via `@path/to/frame.jpg` inline in the prompt (confirmed by the Task 1 spike). Frontend adds a `MomentDetail` component that consumes the SSE stream; the review page wires chip click → selected moment → detail panel.

**Tech Stack:** `asyncio.create_subprocess_exec` (never `shell=True`), FastAPI async `StreamingResponse`, Python `hashlib.sha256` for cache keys, `claude` CLI v2.1.114+ with `--output-format stream-json`, Svelte 5 runes for component state, `vi.stubGlobal('fetch', ...)` for frontend SSE mocks.

**Scope (M3 only):**
- Backend: `server/analysis/claude_cli.py`, `server/analysis/prompt.py`, `server/analysis/rate_limit.py`, `server/api/moments.py`.
- DB helpers in `server/db.py`: `cache_get` / `cache_put`, `insert_analyses` / `get_analyses`.
- `GET /api/rolls/:id` response's moments gain an `analyses: [...]` array.
- Security audit doc for `--dangerously-skip-permissions` at `docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`.
- Frontend: new `MomentDetail.svelte` component, updated `/review/[id]` page with chip selection + detail panel.
- Tests: CLI adapter (fake subprocess), rate limiter, prompt builder, cache db, analyses db, moment-analyse API, frontend component tests. One opt-in integration test.

**Explicitly out of scope (later milestones cover):**
- Dual-lane timeline (M3 keeps the single unlabeled chip row but colours an analysed chip by category — still one row).
- Vault markdown write-back of analyses (M4).
- Summary step — scores, top-3 improvements across all moments (M6).
- PDF export (M6).
- Graph page / mini graph (M5).
- Annotation input (M4).

---

## File Structure

```
tools/bjj-app/
├── server/
│   ├── analysis/
│   │   ├── claude_cli.py            # NEW: async analyse_frame() — SOLE caller of `claude -p`
│   │   ├── prompt.py                # NEW: build_prompt() — compressed taxonomy + schema
│   │   └── rate_limit.py            # NEW: SlidingWindowLimiter class
│   ├── api/
│   │   ├── moments.py               # NEW: POST /api/rolls/:id/moments/:frame_idx/analyse (SSE)
│   │   └── rolls.py                 # MODIFY: MomentOut gains analyses field
│   ├── db.py                        # MODIFY: cache_get/put, insert_analyses/get_analyses
│   ├── config.py                    # MODIFY: claude_bin, rate-limit config
│   └── main.py                      # MODIFY: include moments router
├── tests/backend/
│   ├── test_rate_limit.py           # NEW
│   ├── test_prompt.py               # NEW
│   ├── test_db_cache.py             # NEW
│   ├── test_db_analyses.py          # NEW
│   ├── test_claude_cli.py           # NEW (fake subprocess)
│   ├── test_api_moments.py          # NEW (monkeypatched claude_cli)
│   └── integration/
│       ├── __init__.py              # NEW (empty)
│       └── test_claude_real.py      # NEW (@pytest.mark.integration, skipped by default)
├── web/
│   └── src/
│       ├── lib/
│       │   ├── types.ts             # MODIFY: Analysis, AnalyseMomentEvent types
│       │   ├── api.ts               # MODIFY: add analyseMoment() async iterator
│       │   └── components/
│       │       └── MomentDetail.svelte  # NEW
│       └── routes/review/[id]/
│           └── +page.svelte         # MODIFY: chip selection + detail panel wiring
├── web/tests/
│   └── moment-detail.test.ts        # NEW
└── docs/superpowers/audits/
    └── 2026-04-21-claude-cli-subprocess-audit.md   # NEW
```

### Responsibilities

- `claude_cli.py` — **SOLE** module that spawns `claude`. Async entry point `analyse_frame(frame_path, moment, stream_callback, *, settings, cache_conn) -> AnalysisResult`. Handles: cache lookup, prompt construction via `prompt.build_prompt()`, rate-limit check, `asyncio.create_subprocess_exec`, `stream-json` stdout parsing, callback invocation, one retry on non-zero exit, final JSON parsing + validation, cache write. Raises typed exceptions (`RateLimitedError`, `ClaudeProcessError`, `ClaudeResponseError`).
- `prompt.py` — Pure functions. `build_prompt(frame_path, taxonomy_path, timestamp_s) -> str`; `compress_taxonomy(taxonomy_path) -> str`. Deterministic output so the cache key is stable.
- `rate_limit.py` — `SlidingWindowLimiter(max_calls, window_seconds)` with `.try_acquire() -> float | None` (returns seconds-until-next-slot if denied, None if allowed).
- `api/moments.py` — HTTP surface. Creates the limiter (module-level singleton), wraps `analyse_frame` in an async SSE stream, returns 429 with `Retry-After` on limit, 404 on unknown roll/moment.
- `api/rolls.py` — existing file, extend `MomentOut` to include `analyses` so the page can render the saved result after a refresh.
- Frontend `api.ts` — `analyseMoment(rollId, frameIdx)` async iterator over SSE events.
- Frontend `MomentDetail.svelte` — shows the selected moment; either the "Analyse with Claude" button, the live streaming text, or the saved analysis. Owns no page-level state.

### Analysis result shape

On the wire (`GET /api/rolls/:id`, each moment gains):
```json
{
  "id": "...", "frame_idx": 17, "timestamp_s": 17.0, "pose_delta": 0.42,
  "analyses": [
    {
      "id": "...", "player": "greig",
      "position_id": "closed_guard_bottom", "confidence": 0.82,
      "description": "...", "coach_tip": "..."
    },
    { "id": "...", "player": "anthony", "position_id": "closed_guard_top", "confidence": 0.78,
      "description": null, "coach_tip": null }
  ]
}
```

Per-player rows match the schema already in `server/db.py`. `description` and `coach_tip` are moment-level and stored only on the `greig` row (the focal player); the `anthony` row has them as NULL. Keeping the duplicate-free convention here avoids a schema migration later if we add player-specific tips.

### JSON schema Claude must return

```json
{
  "timestamp": 0.0,
  "greig":   {"position": "<taxonomy_position_id>", "confidence": 0.0},
  "anthony": {"position": "<taxonomy_position_id>", "confidence": 0.0},
  "description": "One-paragraph description of what's happening.",
  "coach_tip": "One-sentence actionable tip for Greig."
}
```

### SSE event shapes emitted by `POST /rolls/:id/moments/:frame_idx/analyse`

```
data: {"stage":"cache","hit":false}                                    # always first
data: {"stage":"streaming","text":"..."}                               # 0+ events, concatenates progressively
data: {"stage":"done","analysis":{...AnalysisResult JSON...},"cached":false}
```

On cache hit:
```
data: {"stage":"cache","hit":true}
data: {"stage":"done","analysis":{...},"cached":true}
```

On rate limit:
```
HTTP 429 + Retry-After: <int-seconds>
{"detail":"Claude cooldown — <N>s until next call","retry_after_s":<N>}
```

---

## Task 1: Claude CLI image-input spike

**Files:**
- Create: `docs/superpowers/spikes/2026-04-21-claude-image-input.md`

No code yet — this is a 30-minute investigation to confirm how `claude -p` accepts a frame image so the rest of the adapter can be written with certainty. The spec calls this out explicitly: the image-passing mechanism "must start with a 30-minute spike to confirm the working syntax with `claude -p` v2.1.114".

- [ ] **Step 1: Pick the test frame**

Use an already-extracted frame. Find one with:

```bash
ls /Users/greigbradley/Desktop/BJJ_Analysis/assets/greig_1s/ 2>/dev/null | head
```

Pick any `.jpg` (or extract a frame from `assets/test_roll.mp4` if needed). Note the absolute path. For this spike, call it `/Users/greigbradley/Desktop/BJJ_Analysis/assets/greig_1s/frame_000005.jpg` (adjust to whatever actually exists).

- [ ] **Step 2: Try the `@path` inline reference**

```bash
FRAME=/Users/greigbradley/Desktop/BJJ_Analysis/assets/greig_1s/frame_000005.jpg

claude -p \
  --model claude-opus-4-7 \
  --output-format stream-json \
  --include-partial-messages \
  --max-turns 1 \
  --dangerously-skip-permissions \
  --verbose \
  "Read the image at @$FRAME and describe what you see in one sentence."
```

Record:
- Exit code (`echo $?`).
- Whether stdout is valid stream-json NDJSON (and paste the first + last NDJSON lines — Task 11/12 assume events of the shape `{"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}` and a final `{"type":"result","result":"...","is_error":false}`; if the real shape differs, note it in the spike doc so Task 11's fake subprocess and Task 12's `_extract_text` / result parsing can be updated).
- Whether the final assistant text describes the actual image contents (proves Claude read the file) or says "I can't see an image" (proves the mechanism failed).

- [ ] **Step 3: If Step 2 failed, try `--add-dir` + path reference**

```bash
claude -p \
  --model claude-opus-4-7 \
  --output-format stream-json \
  --include-partial-messages \
  --max-turns 1 \
  --dangerously-skip-permissions \
  --add-dir /Users/greigbradley/Desktop/BJJ_Analysis/assets \
  --verbose \
  "Read the image file $FRAME and describe what you see in one sentence."
```

- [ ] **Step 4: If both failed, try a temp markdown wrapper**

Write the prompt to a markdown file that embeds the image with standard markdown image syntax, then pass the file path as the prompt:

```bash
cat > /tmp/bjj_spike_prompt.md <<EOF
Describe the image below in one sentence.

![frame]($FRAME)
EOF

claude -p \
  --model claude-opus-4-7 \
  --output-format stream-json \
  --include-partial-messages \
  --max-turns 1 \
  --dangerously-skip-permissions \
  --verbose \
  "$(cat /tmp/bjj_spike_prompt.md)"
```

- [ ] **Step 5: Record findings**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/docs/superpowers/spikes/2026-04-21-claude-image-input.md` with this exact structure:

````markdown
# Spike: Claude CLI image input (M3)

**Date:** 2026-04-21
**CLI version:** claude 2.1.114
**Model:** claude-opus-4-7

## Question

How does `claude -p` accept a frame image in non-interactive mode?

## Candidates tested

### 1. `@path` inline reference

Command:
```bash
<paste exact command from Step 2>
```

Exit: <0 | N>
Stream parseable: <yes|no>
Image actually read: <yes|no — evidence: "<first line of assistant output>">

### 2. `--add-dir` + path reference

Command:
```bash
<paste exact command from Step 3, or "not tried — Step 2 succeeded">
```

Result: <same shape as #1>

### 3. Markdown wrapper with `![...](path)`

Command:
```bash
<paste exact command from Step 4, or "not tried">
```

Result: <same shape as #1>

## Decision

The adapter (`server/analysis/claude_cli.py`) will use **<winning mechanism>** for image input, formatted as:

<exact snippet that goes into the prompt string>

## Fallback

If the chosen mechanism breaks in a future CLI version: <which candidate is next-best to try>.

## Notes

<anything surprising: stderr messages, performance, quirks>
````

- [ ] **Step 6: Commit the spike doc**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add docs/superpowers/spikes/2026-04-21-claude-image-input.md
git commit -m "spike(bjj-app): confirm claude -p image-input mechanism for M3"
```

**IMPORTANT for later tasks:** from Task 7 onward, wherever the plan shows `@{frame_path}` in a prompt string, substitute the winning mechanism from this spike. The default in the plan assumes `@path` worked (Candidate 1); if it didn't, replace those lines with the mechanism you chose and note the swap in the commit message.

---

## Task 2: Extend `config.py` with Claude + rate-limit settings

**Files:**
- Modify: `tools/bjj-app/server/config.py`

- [ ] **Step 1: Update `Settings` and `load_settings`**

Open `tools/bjj-app/server/config.py` and replace the entire contents with:

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
    # Claude CLI adapter
    claude_bin: Path
    claude_model: str
    claude_max_calls: int
    claude_window_seconds: float
    taxonomy_path: Path


def load_settings() -> Settings:
    project_root = Path(os.getenv("BJJ_PROJECT_ROOT", str(_project_root()))).resolve()
    vault_root = Path(os.getenv("BJJ_VAULT_ROOT", str(project_root))).resolve()
    db_override = os.getenv("BJJ_DB_OVERRIDE")
    db_path = (
        Path(db_override)
        if db_override
        else project_root / "tools" / "bjj-app" / "bjj-app.db"
    )
    claude_bin = Path(
        os.getenv("BJJ_CLAUDE_BIN", "/Users/greigbradley/.local/bin/claude")
    )
    return Settings(
        project_root=project_root,
        vault_root=vault_root,
        db_path=db_path,
        host=os.getenv("BJJ_HOST", "0.0.0.0"),
        port=int(os.getenv("BJJ_PORT", "8000")),
        frontend_build_dir=project_root / "tools" / "bjj-app" / "web" / "build",
        claude_bin=claude_bin,
        claude_model=os.getenv("BJJ_CLAUDE_MODEL", "claude-opus-4-7"),
        claude_max_calls=int(os.getenv("BJJ_CLAUDE_MAX_CALLS", "10")),
        claude_window_seconds=float(os.getenv("BJJ_CLAUDE_WINDOW_SECONDS", "300")),
        taxonomy_path=project_root / "tools" / "taxonomy.json",
    )
```

- [ ] **Step 2: Run existing backend tests to prove no regressions**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend -v
```

Expected: the same count as after M2b (all green). No tests touched these new fields yet; adding optional settings is backwards-compatible.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/config.py
git commit -m "chore(bjj-app): add Claude CLI + rate-limit settings to config"
```

---

## Task 3: Write failing tests for `SlidingWindowLimiter`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_rate_limit.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_rate_limit.py`:

```python
"""Tests for the sliding-window rate limiter.

Time is injected via a `now` callable so we never rely on wall-clock sleeps.
"""
from __future__ import annotations

import pytest

from server.analysis.rate_limit import SlidingWindowLimiter


def test_allows_up_to_max_calls_in_window():
    fake_now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=3, window_seconds=10.0, now=lambda: fake_now[0])

    assert limiter.try_acquire() is None
    assert limiter.try_acquire() is None
    assert limiter.try_acquire() is None


def test_denies_the_next_call_when_window_is_full():
    fake_now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10.0, now=lambda: fake_now[0])

    limiter.try_acquire()
    limiter.try_acquire()
    retry_after = limiter.try_acquire()

    assert retry_after is not None
    # With both calls at t=0, the oldest frees at t=10 → 10s wait.
    assert retry_after == pytest.approx(10.0, abs=1e-6)


def test_returns_accurate_retry_after_when_time_advances():
    fake_now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10.0, now=lambda: fake_now[0])

    limiter.try_acquire()  # t=0
    fake_now[0] = 3.0
    limiter.try_acquire()  # t=3
    fake_now[0] = 5.0

    retry_after = limiter.try_acquire()  # oldest expires at t=10 → wait 5s
    assert retry_after == pytest.approx(5.0, abs=1e-6)


def test_allows_again_after_the_oldest_call_ages_out():
    fake_now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10.0, now=lambda: fake_now[0])

    limiter.try_acquire()
    fake_now[0] = 2.0
    limiter.try_acquire()
    fake_now[0] = 11.0  # first call (t=0) now older than 10s window

    assert limiter.try_acquire() is None


def test_rejects_nonsense_construction():
    with pytest.raises(ValueError):
        SlidingWindowLimiter(max_calls=0, window_seconds=10.0)
    with pytest.raises(ValueError):
        SlidingWindowLimiter(max_calls=10, window_seconds=0)
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_rate_limit.py -v
```

Expected: ImportError on `server.analysis.rate_limit`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_rate_limit.py
git commit -m "test(bjj-app): add SlidingWindowLimiter tests (failing — no impl)"
```

---

## Task 4: Implement `SlidingWindowLimiter`

**Files:**
- Create: `tools/bjj-app/server/analysis/rate_limit.py`

- [ ] **Step 1: Write the limiter**

Create `tools/bjj-app/server/analysis/rate_limit.py`:

```python
"""Sliding-window rate limiter for Claude CLI calls.

Tracks the timestamps of recent acquires in a deque. A call is allowed when
fewer than `max_calls` timestamps lie inside the last `window_seconds`.
`try_acquire()` returns None on success, or the wait-seconds until the next
slot opens on denial. No blocking — callers translate denial into HTTP 429.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class SlidingWindowLimiter:
    def __init__(
        self,
        max_calls: int,
        window_seconds: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_calls <= 0:
            raise ValueError(f"max_calls must be > 0, got {max_calls}")
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        self._max = max_calls
        self._window = float(window_seconds)
        self._now = now
        self._calls: deque[float] = deque()

    def try_acquire(self) -> float | None:
        now = self._now()
        cutoff = now - self._window
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()

        if len(self._calls) >= self._max:
            oldest = self._calls[0]
            return (oldest + self._window) - now

        self._calls.append(now)
        return None
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_rate_limit.py -v
```

Expected: `5 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/rate_limit.py
git commit -m "feat(bjj-app): add SlidingWindowLimiter for Claude CLI rate limits"
```

---

## Task 5: Write failing tests for the prompt builder

**Files:**
- Create: `tools/bjj-app/tests/backend/test_prompt.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_prompt.py`:

```python
"""Tests for build_prompt / compress_taxonomy.

Uses a tiny fixture taxonomy — we don't want to pin these tests to the real
taxonomy.json, which evolves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.analysis.prompt import build_prompt, compress_taxonomy


@pytest.fixture
def tiny_taxonomy(tmp_path: Path) -> Path:
    data = {
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "Upright."},
            "guard_bottom": {
                "label": "Guard (Bottom)", "dominance": 1, "visual_cues": "On back."
            },
        },
        "positions": [
            {
                "id": "standing_neutral",
                "name": "Standing - Neutral",
                "category": "standing",
                "visual_cues": "Athletic stance.",
            },
            {
                "id": "closed_guard_bottom",
                "name": "Closed Guard (Bottom)",
                "category": "guard_bottom",
                "visual_cues": "Ankles crossed behind opponent's back.",
            },
        ],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data))
    return path


def test_compress_taxonomy_includes_every_position_id_and_name(tiny_taxonomy: Path):
    compressed = compress_taxonomy(tiny_taxonomy)
    assert "standing_neutral" in compressed
    assert "Standing - Neutral" in compressed
    assert "closed_guard_bottom" in compressed
    assert "Closed Guard (Bottom)" in compressed


def test_compress_taxonomy_includes_category_labels(tiny_taxonomy: Path):
    compressed = compress_taxonomy(tiny_taxonomy)
    assert "Standing" in compressed
    assert "Guard (Bottom)" in compressed


def test_compress_taxonomy_is_deterministic(tiny_taxonomy: Path):
    a = compress_taxonomy(tiny_taxonomy)
    b = compress_taxonomy(tiny_taxonomy)
    assert a == b


def test_build_prompt_references_the_frame_path(tiny_taxonomy: Path, tmp_path: Path):
    frame = tmp_path / "frame_000017.jpg"
    frame.write_bytes(b"\xff\xd8\xff")  # fake JPEG magic — existence is all we need

    prompt = build_prompt(frame_path=frame, taxonomy_path=tiny_taxonomy, timestamp_s=17.0)
    assert str(frame) in prompt
    # Output schema keys must be spelled in the prompt so the model learns them.
    for key in ("timestamp", "greig", "anthony", "position", "confidence",
                "description", "coach_tip"):
        assert key in prompt


def test_build_prompt_includes_the_timestamp(tiny_taxonomy: Path, tmp_path: Path):
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff")
    prompt = build_prompt(frame_path=frame, taxonomy_path=tiny_taxonomy, timestamp_s=42.5)
    assert "42.5" in prompt


def test_build_prompt_is_deterministic(tiny_taxonomy: Path, tmp_path: Path):
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff")
    a = build_prompt(frame_path=frame, taxonomy_path=tiny_taxonomy, timestamp_s=3.0)
    b = build_prompt(frame_path=frame, taxonomy_path=tiny_taxonomy, timestamp_s=3.0)
    assert a == b


def test_build_prompt_raises_if_frame_missing(tiny_taxonomy: Path, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        build_prompt(
            frame_path=tmp_path / "nope.jpg",
            taxonomy_path=tiny_taxonomy,
            timestamp_s=0.0,
        )
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_prompt.py -v
```

Expected: ImportError on `server.analysis.prompt`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_prompt.py
git commit -m "test(bjj-app): add prompt builder tests (failing — no impl)"
```

---

## Task 6: Implement the prompt builder

**Files:**
- Create: `tools/bjj-app/server/analysis/prompt.py`

- [ ] **Step 1: Write `prompt.py`**

Create `tools/bjj-app/server/analysis/prompt.py`:

```python
"""Prompt construction for Claude single-frame BJJ analysis.

Kept separate from `claude_cli.py` so prompt changes are testable without
spawning subprocesses, and so the cache key (prompt_hash) is stable across
changes that don't affect the prompt text.
"""
from __future__ import annotations

import json
from pathlib import Path

_SYSTEM_PREAMBLE = (
    "You are a BJJ (Brazilian Jiu-Jitsu) position classifier. "
    "You will be shown one frame from a grappling roll between two practitioners: "
    "Greig (the white belt we are coaching) and Anthony (his training partner). "
    "Identify each player's current position using ONLY the position ids listed in "
    "the taxonomy below. If you are unsure between two positions, pick the more "
    "specific one. Confidence is a float in [0, 1] reflecting how confident you "
    "are that the chosen position id is correct.\n\n"
    "Output ONE JSON object and nothing else. No prose, no markdown fences."
)

_SCHEMA_HINT = (
    'Output JSON schema:\n'
    '{\n'
    '  "timestamp": <float, seconds>,\n'
    '  "greig":   {"position": "<taxonomy position id>", "confidence": <0..1>},\n'
    '  "anthony": {"position": "<taxonomy position id>", "confidence": <0..1>},\n'
    '  "description": "<one paragraph describing the moment>",\n'
    '  "coach_tip":   "<one actionable sentence for Greig>"\n'
    '}'
)


def compress_taxonomy(taxonomy_path: Path) -> str:
    """Return a short human-readable description of categories + positions.

    Deterministic — same input file produces identical output.
    """
    data = json.loads(taxonomy_path.read_text())

    lines: list[str] = ["Categories:"]
    for cat_id, cat in sorted(data["categories"].items()):
        lines.append(f"  {cat_id} ({cat['label']}): {cat['visual_cues']}")

    lines.append("")
    lines.append("Positions (use these ids exactly):")
    for p in sorted(data["positions"], key=lambda x: x["id"]):
        lines.append(f"  {p['id']} — {p['name']} [{p['category']}]: {p['visual_cues']}")

    return "\n".join(lines)


def build_prompt(
    frame_path: Path,
    taxonomy_path: Path,
    timestamp_s: float,
) -> str:
    """Construct the single-frame classification prompt. Deterministic."""
    if not frame_path.exists():
        raise FileNotFoundError(frame_path)

    taxonomy = compress_taxonomy(taxonomy_path)
    return (
        f"{_SYSTEM_PREAMBLE}\n\n"
        f"{taxonomy}\n\n"
        f"Frame timestamp (seconds into the roll): {timestamp_s}\n"
        f"Image to analyse: @{frame_path}\n\n"
        f"{_SCHEMA_HINT}"
    )
```

> **Image-input syntax — reminder from Task 1 spike:** the `@{frame_path}` line above assumes `@path` inline works with `claude -p`. If the spike chose a different mechanism, replace the `Image to analyse: @{frame_path}` line here with whatever the spike recorded as the winning format.

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_prompt.py -v
```

Expected: `7 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/prompt.py
git commit -m "feat(bjj-app): add build_prompt / compress_taxonomy"
```

---

## Task 7: Write failing tests for the cache db helpers

**Files:**
- Create: `tools/bjj-app/tests/backend/test_db_cache.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_db_cache.py`:

```python
"""Tests for claude_cache helpers in server.db."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.db import cache_get, cache_put, connect, init_db


@pytest.fixture
def db(tmp_path: Path):
    path = tmp_path / "test.db"
    init_db(path)
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def test_cache_get_returns_none_for_unknown_key(db):
    assert cache_get(db, prompt_hash="p", frame_hash="f") is None


def test_cache_put_then_get_round_trip(db):
    payload = {"hello": "world", "n": 1}
    cache_put(db, prompt_hash="p", frame_hash="f", response=payload)
    assert cache_get(db, prompt_hash="p", frame_hash="f") == payload


def test_cache_put_is_idempotent_on_same_key(db):
    cache_put(db, prompt_hash="p", frame_hash="f", response={"a": 1})
    cache_put(db, prompt_hash="p", frame_hash="f", response={"a": 2})
    assert cache_get(db, prompt_hash="p", frame_hash="f") == {"a": 2}


def test_cache_distinguishes_by_both_hash_components(db):
    cache_put(db, prompt_hash="p1", frame_hash="f", response={"v": 1})
    cache_put(db, prompt_hash="p2", frame_hash="f", response={"v": 2})
    cache_put(db, prompt_hash="p1", frame_hash="g", response={"v": 3})

    assert cache_get(db, prompt_hash="p1", frame_hash="f") == {"v": 1}
    assert cache_get(db, prompt_hash="p2", frame_hash="f") == {"v": 2}
    assert cache_get(db, prompt_hash="p1", frame_hash="g") == {"v": 3}
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_db_cache.py -v
```

Expected: ImportError on `cache_get` / `cache_put`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_db_cache.py
git commit -m "test(bjj-app): add claude_cache db tests (failing — no impl)"
```

---

## Task 8: Implement `cache_get` and `cache_put`

**Files:**
- Modify: `tools/bjj-app/server/db.py`

- [ ] **Step 1: Append the helpers**

Append to the end of `tools/bjj-app/server/db.py`:

```python


def cache_get(conn, *, prompt_hash: str, frame_hash: str) -> dict | None:
    """Return the cached Claude response for this (prompt, frame) pair, or None."""
    import json as _json

    cur = conn.execute(
        "SELECT response_json FROM claude_cache WHERE prompt_hash = ? AND frame_hash = ?",
        (prompt_hash, frame_hash),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _json.loads(row["response_json"])


def cache_put(
    conn,
    *,
    prompt_hash: str,
    frame_hash: str,
    response: dict,
) -> None:
    """Upsert a cached response. Re-putting on the same key replaces the value."""
    import json as _json
    import time as _time

    conn.execute(
        """
        INSERT INTO claude_cache (prompt_hash, frame_hash, response_json, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(prompt_hash, frame_hash) DO UPDATE SET
            response_json = excluded.response_json,
            created_at    = excluded.created_at
        """,
        (prompt_hash, frame_hash, _json.dumps(response), int(_time.time())),
    )
    conn.commit()
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_db_cache.py -v
```

Expected: `4 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py
git commit -m "feat(bjj-app): add cache_get / cache_put helpers"
```

---

## Task 9: Write failing tests for the analyses db helpers

**Files:**
- Create: `tools/bjj-app/tests/backend/test_db_analyses.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_db_analyses.py`:

```python
"""Tests for insert_analyses / get_analyses helpers."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from server.db import (
    connect,
    create_roll,
    get_analyses,
    init_db,
    insert_analyses,
    insert_moments,
)


@pytest.fixture
def db_with_moment(tmp_path: Path):
    path = tmp_path / "test.db"
    init_db(path)
    conn = connect(path)
    create_roll(
        conn,
        id="roll-1",
        title="T",
        date="2026-04-21",
        video_path="assets/roll-1/source.mp4",
        duration_s=10.0,
        partner=None,
        result="unknown",
        created_at=int(time.time()),
    )
    moments = insert_moments(
        conn,
        roll_id="roll-1",
        moments=[{"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2}],
    )
    moment_id = moments[0]["id"]
    try:
        yield conn, moment_id
    finally:
        conn.close()


def test_insert_analyses_persists_one_row_per_player(db_with_moment):
    conn, moment_id = db_with_moment
    rows = insert_analyses(
        conn,
        moment_id=moment_id,
        players=[
            {
                "player": "greig",
                "position_id": "closed_guard_bottom",
                "confidence": 0.8,
                "description": "Greig is in closed guard.",
                "coach_tip": "Break posture.",
            },
            {
                "player": "anthony",
                "position_id": "closed_guard_top",
                "confidence": 0.75,
                "description": None,
                "coach_tip": None,
            },
        ],
        claude_version="2.1.114",
    )
    assert len(rows) == 2
    players = sorted(r["player"] for r in rows)
    assert players == ["anthony", "greig"]


def test_get_analyses_returns_both_rows_for_a_moment(db_with_moment):
    conn, moment_id = db_with_moment
    insert_analyses(
        conn,
        moment_id=moment_id,
        players=[
            {
                "player": "greig", "position_id": "p1", "confidence": 1.0,
                "description": "x", "coach_tip": "y",
            },
            {
                "player": "anthony", "position_id": "p2", "confidence": 0.5,
                "description": None, "coach_tip": None,
            },
        ],
        claude_version="2.1.114",
    )
    fetched = get_analyses(conn, moment_id)
    assert len(fetched) == 2


def test_insert_analyses_replaces_previous_analyses_for_the_same_moment(db_with_moment):
    conn, moment_id = db_with_moment
    insert_analyses(
        conn,
        moment_id=moment_id,
        players=[
            {"player": "greig", "position_id": "old", "confidence": 0.3,
             "description": None, "coach_tip": None},
            {"player": "anthony", "position_id": "old2", "confidence": 0.3,
             "description": None, "coach_tip": None},
        ],
        claude_version="2.1.114",
    )
    insert_analyses(
        conn,
        moment_id=moment_id,
        players=[
            {"player": "greig", "position_id": "new", "confidence": 0.9,
             "description": "d", "coach_tip": "t"},
            {"player": "anthony", "position_id": "new2", "confidence": 0.85,
             "description": None, "coach_tip": None},
        ],
        claude_version="2.1.114",
    )
    rows = get_analyses(conn, moment_id)
    assert len(rows) == 2
    assert {r["position_id"] for r in rows} == {"new", "new2"}


def test_get_analyses_returns_empty_list_for_moment_with_none(db_with_moment):
    conn, moment_id = db_with_moment
    assert get_analyses(conn, moment_id) == []
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_db_analyses.py -v
```

Expected: ImportError on `insert_analyses` / `get_analyses`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_db_analyses.py
git commit -m "test(bjj-app): add analyses db helper tests (failing — no impl)"
```

---

## Task 10: Implement `insert_analyses` and `get_analyses`

**Files:**
- Modify: `tools/bjj-app/server/db.py`

- [ ] **Step 1: Append the helpers**

Append to the end of `tools/bjj-app/server/db.py`:

```python


def insert_analyses(
    conn,
    *,
    moment_id: str,
    players: list[dict],
    claude_version: str,
) -> list[sqlite3.Row]:
    """Replace all analyses for `moment_id` with one row per entry in `players`.

    Each player dict must contain: player ('greig'|'anthony'), position_id (str),
    confidence (float | None), description (str | None), coach_tip (str | None).
    """
    import time as _time

    conn.execute("DELETE FROM analyses WHERE moment_id = ?", (moment_id,))
    inserted_ids: list[str] = []
    now = int(_time.time())
    for p in players:
        analysis_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO analyses (
                id, moment_id, player, position_id, confidence,
                description, coach_tip, claude_version, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                moment_id,
                p["player"],
                p["position_id"],
                None if p.get("confidence") is None else float(p["confidence"]),
                p.get("description"),
                p.get("coach_tip"),
                claude_version,
                now,
            ),
        )
        inserted_ids.append(analysis_id)
    conn.commit()

    if not inserted_ids:
        return []
    cur = conn.execute(
        f"SELECT * FROM analyses WHERE id IN ({','.join('?' * len(inserted_ids))})",
        inserted_ids,
    )
    rows_by_id = {r["id"]: r for r in cur.fetchall()}
    return [rows_by_id[i] for i in inserted_ids]


def get_analyses(conn, moment_id: str) -> list[sqlite3.Row]:
    """Return all analyses for a moment. Order is stable: greig first, then anthony."""
    cur = conn.execute(
        """
        SELECT * FROM analyses
        WHERE moment_id = ?
        ORDER BY CASE player WHEN 'greig' THEN 0 ELSE 1 END, created_at
        """,
        (moment_id,),
    )
    return list(cur.fetchall())
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_db_analyses.py -v
```

Expected: `4 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/db.py
git commit -m "feat(bjj-app): add insert_analyses / get_analyses helpers"
```

---

## Task 11: Write failing tests for `claude_cli.analyse_frame`

**Files:**
- Create: `tools/bjj-app/tests/backend/test_claude_cli.py`

The entire tests suite here fakes `asyncio.create_subprocess_exec` so we never spawn a real `claude`. We rely on the fact that stream-json is NDJSON — one JSON object per line — where the final `{"type":"result", ...}` line carries the assistant's complete text.

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_claude_cli.py`:

```python
"""Tests for the Claude CLI adapter.

We fake asyncio.create_subprocess_exec with an object that quacks like asyncio
subprocesses: `.stdout.readline()` coroutines returning bytes, `.wait()`
returning an exit code, `.returncode` attribute.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from server.analysis.claude_cli import (
    ClaudeProcessError,
    ClaudeResponseError,
    RateLimitedError,
    analyse_frame,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import load_settings
from server.db import connect, init_db


# ---------- Fake subprocess plumbing ----------


@dataclass
class _FakeStream:
    chunks: list[bytes]

    async def readline(self) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class _FakeProcess:
    def __init__(self, stdout_lines: list[bytes], exit_code: int = 0) -> None:
        # Ensure each line ends with \n so the adapter can parse NDJSON.
        lines = [ln if ln.endswith(b"\n") else ln + b"\n" for ln in stdout_lines]
        self.stdout = _FakeStream(lines)
        self._exit_code = exit_code
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = self._exit_code
        return self._exit_code


def _ok_stream(assistant_json: dict) -> list[bytes]:
    """An NDJSON stream that ends with a stream-json 'result' event."""
    text = json.dumps(assistant_json)
    return [
        json.dumps({"type": "system", "subtype": "init"}).encode(),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text[:20]}]}}).encode(),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text[20:]}]}}).encode(),
        json.dumps({"type": "result", "result": text, "is_error": False}).encode(),
    ]


@pytest.fixture
def frame(tmp_path: Path) -> Path:
    p = tmp_path / "frame_000017.jpg"
    p.write_bytes(b"\xff\xd8\xff")
    return p


@pytest.fixture
def taxonomy(tmp_path: Path) -> Path:
    p = tmp_path / "taxonomy.json"
    p.write_text(json.dumps({
        "categories": {"standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"}},
        "positions": [
            {"id": "standing_neutral", "name": "Standing - Neutral",
             "category": "standing", "visual_cues": "x"},
            {"id": "closed_guard_bottom", "name": "Closed Guard (Bottom)",
             "category": "standing", "visual_cues": "x"},
            {"id": "closed_guard_top", "name": "Closed Guard (Top)",
             "category": "standing", "visual_cues": "x"},
        ],
    }))
    return p


@pytest.fixture
def cache_conn(tmp_path: Path):
    db = tmp_path / "cache.db"
    init_db(db)
    conn = connect(db)
    try:
        yield conn
    finally:
        conn.close()


def _settings_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, taxonomy: Path):
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_path / "test.db"))
    settings = load_settings()
    # Redirect taxonomy to the fixture.
    from dataclasses import replace
    return replace(settings, taxonomy_path=taxonomy)


_ASSISTANT_OK = {
    "timestamp": 17.0,
    "greig": {"position": "closed_guard_bottom", "confidence": 0.82},
    "anthony": {"position": "closed_guard_top", "confidence": 0.78},
    "description": "Greig is working from closed guard.",
    "coach_tip": "Break Anthony's posture before attacking.",
}


# ---------- Tests ----------


@pytest.mark.asyncio
async def test_analyse_frame_happy_path_streams_and_returns_parsed_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    spawned_cmds: list[list[str]] = []

    async def fake_spawn(*args, **kwargs):
        spawned_cmds.append(list(args))
        return _FakeProcess(_ok_stream(_ASSISTANT_OK), exit_code=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    received: list[dict] = []

    async def on_event(evt: dict) -> None:
        received.append(evt)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    result = await analyse_frame(
        frame_path=frame,
        timestamp_s=17.0,
        stream_callback=on_event,
        settings=settings,
        limiter=limiter,
        cache_conn=cache_conn,
    )

    assert result["greig"]["position"] == "closed_guard_bottom"
    assert result["anthony"]["position"] == "closed_guard_top"
    # At least one streaming event was surfaced.
    assert any(e.get("stage") == "streaming" for e in received)
    # The CLI was spawned exactly once with the Claude binary.
    assert len(spawned_cmds) == 1
    assert spawned_cmds[0][0].endswith("claude")


@pytest.mark.asyncio
async def test_analyse_frame_caches_result_and_skips_subprocess_on_second_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    spawn_count = {"n": 0}

    async def fake_spawn(*args, **kwargs):
        spawn_count["n"] += 1
        return _FakeProcess(_ok_stream(_ASSISTANT_OK), exit_code=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    async def noop(_: dict) -> None:
        return None

    await analyse_frame(frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn)
    await analyse_frame(frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn)

    assert spawn_count["n"] == 1


@pytest.mark.asyncio
async def test_analyse_frame_retries_once_on_nonzero_exit_then_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    spawn_count = {"n": 0}

    async def fake_spawn(*args, **kwargs):
        spawn_count["n"] += 1
        return _FakeProcess([b'{"type":"result","is_error":true,"result":""}'], exit_code=2)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    # Monkeypatch asyncio.sleep so the 2s backoff doesn't actually sleep.
    async def instant_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    async def noop(_: dict) -> None:
        return None

    with pytest.raises(ClaudeProcessError):
        await analyse_frame(
            frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn
        )

    assert spawn_count["n"] == 2  # initial + one retry


@pytest.mark.asyncio
async def test_analyse_frame_raises_on_unparseable_assistant_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    bad_stream = [
        json.dumps({"type": "system", "subtype": "init"}).encode(),
        json.dumps({"type": "result", "result": "not json at all", "is_error": False}).encode(),
    ]

    async def fake_spawn(*args, **kwargs):
        return _FakeProcess(bad_stream, exit_code=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    async def instant_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    async def noop(_: dict) -> None:
        return None

    with pytest.raises(ClaudeResponseError):
        await analyse_frame(
            frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn
        )


@pytest.mark.asyncio
async def test_analyse_frame_raises_rate_limited_when_limiter_denies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frame: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    async def never_spawn(*args, **kwargs):
        raise AssertionError("subprocess must not be spawned when rate-limited")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", never_spawn)

    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=1, window_seconds=60)
    # Exhaust the limiter.
    assert limiter.try_acquire() is None

    async def noop(_: dict) -> None:
        return None

    with pytest.raises(RateLimitedError) as exc:
        await analyse_frame(
            frame, 17.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn
        )
    # The error carries a retry-after hint the endpoint will surface as HTTP 429.
    assert exc.value.retry_after_s > 0


@pytest.mark.asyncio
async def test_analyse_frame_refuses_frame_path_outside_project_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    taxonomy: Path,
    cache_conn,
) -> None:
    # Security invariant: the adapter must never accept an arbitrary path.
    outside = Path("/etc/hosts")
    settings = _settings_with(monkeypatch, tmp_path, taxonomy)
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60)

    async def noop(_: dict) -> None:
        return None

    with pytest.raises(ValueError):
        await analyse_frame(
            outside, 0.0, noop, settings=settings, limiter=limiter, cache_conn=cache_conn
        )
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_claude_cli.py -v
```

Expected: ImportError on `server.analysis.claude_cli`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_claude_cli.py
git commit -m "test(bjj-app): add claude_cli adapter tests (failing — no impl)"
```

---

## Task 12: Implement `analyse_frame` (Claude CLI adapter)

**Files:**
- Create: `tools/bjj-app/server/analysis/claude_cli.py`

- [ ] **Step 1: Write `claude_cli.py`**

Create `tools/bjj-app/server/analysis/claude_cli.py`:

```python
"""SOLE adapter around the `claude` CLI.

All BJJ-app code that wants Claude inference goes through `analyse_frame`.
That isolates rate limiting, caching, retries, stream parsing, and future
model swaps behind a single seam.

Security note: `--dangerously-skip-permissions` is passed to `claude -p`.
This is audited in docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md.
The short version: the prompt is fully constructed by us (no user input
interpolated), the frame path is validated to lie inside the project root,
and the subprocess is spawned via create_subprocess_exec with an argv list —
never `shell=True`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Awaitable, Callable

from server.analysis.prompt import build_prompt
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import Settings
from server.db import cache_get, cache_put

AnalysisResult = dict
StreamCallback = Callable[[dict], Awaitable[None]]


class RateLimitedError(Exception):
    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"rate-limited: retry after {retry_after_s:.1f}s")
        self.retry_after_s = retry_after_s


class ClaudeProcessError(Exception):
    """Subprocess exited non-zero after a retry."""


class ClaudeResponseError(Exception):
    """stdout stream did not contain parseable assistant JSON."""


_RETRY_BACKOFF_SECONDS = 2.0


async def analyse_frame(
    frame_path: Path,
    timestamp_s: float,
    stream_callback: StreamCallback,
    *,
    settings: Settings,
    limiter: SlidingWindowLimiter,
    cache_conn: sqlite3.Connection,
) -> AnalysisResult:
    """Classify one frame with Claude Opus 4.7. See module docstring."""
    # --- Security invariant: frame must live inside the project root ---
    frame_resolved = frame_path.resolve()
    project_resolved = settings.project_root.resolve()
    try:
        frame_resolved.relative_to(project_resolved)
    except ValueError as exc:
        raise ValueError(
            f"frame_path {frame_path} escapes project root {project_resolved}"
        ) from exc
    if not frame_resolved.exists():
        raise FileNotFoundError(frame_path)

    # --- Cache lookup ---
    prompt = build_prompt(
        frame_path=frame_resolved,
        taxonomy_path=settings.taxonomy_path,
        timestamp_s=timestamp_s,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    frame_hash = _hash_file(frame_resolved)

    cached = cache_get(cache_conn, prompt_hash=prompt_hash, frame_hash=frame_hash)
    if cached is not None:
        await stream_callback({"stage": "cache", "hit": True})
        return cached

    await stream_callback({"stage": "cache", "hit": False})

    # --- Rate limit (check BEFORE spawning, count toward the window) ---
    wait = limiter.try_acquire()
    if wait is not None:
        raise RateLimitedError(retry_after_s=wait)

    # --- Spawn with one retry on non-zero exit ---
    assistant_text: str | None = None
    last_exit: int | None = None
    for attempt in range(2):
        assistant_text, last_exit = await _run_once(
            settings=settings, prompt=prompt, stream_callback=stream_callback
        )
        if last_exit == 0 and assistant_text is not None:
            break
        if attempt == 0:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)

    if last_exit != 0:
        raise ClaudeProcessError(f"claude exited {last_exit}")

    assert assistant_text is not None
    try:
        parsed = json.loads(assistant_text)
    except json.JSONDecodeError as exc:
        raise ClaudeResponseError(
            f"assistant output was not JSON: {assistant_text[:200]!r}"
        ) from exc

    _validate_shape(parsed)
    cache_put(
        cache_conn, prompt_hash=prompt_hash, frame_hash=frame_hash, response=parsed
    )
    return parsed


async def _run_once(
    *,
    settings: Settings,
    prompt: str,
    stream_callback: StreamCallback,
) -> tuple[str | None, int]:
    """Run claude -p once. Returns (final_assistant_text, exit_code)."""
    argv = [
        str(settings.claude_bin),
        "-p",
        "--model", settings.claude_model,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--max-turns", "1",
        "--dangerously-skip-permissions",
        "--verbose",
        prompt,
    ]

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None

    final_text: str | None = None
    partial = ""

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip non-JSON lines (shouldn't happen with stream-json)

        etype = event.get("type")
        if etype == "assistant":
            # stream-json emits incremental assistant chunks; surface the deltas.
            chunk = _extract_text(event)
            if chunk:
                partial += chunk
                await stream_callback({"stage": "streaming", "text": partial})
        elif etype == "result":
            # Final event with the full assistant text.
            final_text = event.get("result") or partial or None

    exit_code = await proc.wait()
    return final_text, exit_code


def _extract_text(assistant_event: dict) -> str:
    """Pull the text out of an `assistant` stream-json event."""
    msg = assistant_event.get("message") or {}
    content = msg.get("content") or []
    parts = []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text") or "")
    return "".join(parts)


def _hash_file(path: Path, chunk_size: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _validate_shape(parsed: dict) -> None:
    """Raise ClaudeResponseError if the JSON doesn't match the expected schema."""
    for key in ("greig", "anthony", "description", "coach_tip"):
        if key not in parsed:
            raise ClaudeResponseError(f"missing key: {key}")
    for player in ("greig", "anthony"):
        sub = parsed[player]
        if not isinstance(sub, dict) or "position" not in sub or "confidence" not in sub:
            raise ClaudeResponseError(f"malformed player subobject: {player}")
```

- [ ] **Step 2: Run tests — must pass**

```bash
pytest tests/backend/test_claude_cli.py -v
```

Expected: `6 passed`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/claude_cli.py
git commit -m "feat(bjj-app): add Claude CLI adapter (analyse_frame)"
```

---

## Task 13: Write failing tests for the moment-analyse SSE endpoint

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_moments.py`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/tests/backend/test_api_moments.py`:

```python
"""Tests for POST /api/rolls/:id/moments/:frame_idx/analyse.

The endpoint is mocked at the `analyse_frame` seam, NOT by faking subprocesses
at the asyncio level — claude_cli.py already owns that concern and has its
own tests. Here we verify the HTTP wiring: SSE framing, persistence, 404s,
429 behaviour.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _parse_sse_lines(body: str) -> list[dict]:
    events: list[dict] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


async def _upload_and_analyse(
    client: AsyncClient, short_video_path: Path
) -> tuple[str, list[dict]]:
    """Upload + run pose pre-pass → return (roll_id, moments_in_response)."""
    with short_video_path.open("rb") as f:
        up = await client.post(
            "/api/rolls",
            files={"video": ("short.mp4", f, "video/mp4")},
            data={"title": "Moment analyse fixture", "date": "2026-04-21"},
        )
    assert up.status_code == 201
    roll_id = up.json()["id"]

    pre = await client.post(f"/api/rolls/{roll_id}/analyse")
    assert pre.status_code == 200
    detail = await client.get(f"/api/rolls/{roll_id}")
    return roll_id, detail.json()["moments"]


_FAKE_RESULT = {
    "timestamp": 1.0,
    "greig": {"position": "closed_guard_bottom", "confidence": 0.9},
    "anthony": {"position": "closed_guard_top", "confidence": 0.85},
    "description": "Closed guard.",
    "coach_tip": "Break posture.",
}


@pytest.mark.asyncio
async def test_moment_analyse_streams_and_persists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    # Patch claude_cli.analyse_frame where api.moments imports it from.
    async def fake_analyse_frame(frame_path, timestamp_s, stream_callback, **kw):
        await stream_callback({"stage": "cache", "hit": False})
        await stream_callback({"stage": "streaming", "text": '{"greig":'})
        return _FAKE_RESULT

    import server.api.moments as moments_mod
    monkeypatch.setattr(moments_mod, "analyse_frame", fake_analyse_frame)

    from server.main import create_app

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moments = await _upload_and_analyse(client, short_video_path)
        assert moments, "pose pre-pass must flag at least one moment on the fixture"
        first_frame_idx = moments[0]["frame_idx"]

        analyse = await client.post(
            f"/api/rolls/{roll_id}/moments/{first_frame_idx}/analyse"
        )

    assert analyse.status_code == 200
    assert analyse.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_lines(analyse.text)
    stages = [e["stage"] for e in events]
    assert stages[0] == "cache"
    assert stages[-1] == "done"
    assert events[-1]["analysis"]["greig"]["position"] == "closed_guard_bottom"

    # After the stream, the moment's analyses are persisted in the DB.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client2:
        detail = await client2.get(f"/api/rolls/{roll_id}")
    body = detail.json()
    target = next(m for m in body["moments"] if m["frame_idx"] == first_frame_idx)
    players = sorted(a["player"] for a in target["analyses"])
    assert players == ["anthony", "greig"]


@pytest.mark.asyncio
async def test_moment_analyse_returns_404_for_unknown_roll(
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
        response = await client.post("/api/rolls/does-not-exist/moments/0/analyse")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_moment_analyse_returns_404_for_unknown_frame_idx(
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
        roll_id, _ = await _upload_and_analyse(client, short_video_path)
        response = await client.post(
            f"/api/rolls/{roll_id}/moments/99999/analyse"
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_moment_analyse_returns_429_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
    short_video_path: Path,
) -> None:
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.analysis.claude_cli import RateLimitedError

    async def always_rate_limited(*args, **kwargs):
        raise RateLimitedError(retry_after_s=42.0)

    import server.api.moments as moments_mod
    monkeypatch.setattr(moments_mod, "analyse_frame", always_rate_limited)

    from server.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        roll_id, moments = await _upload_and_analyse(client, short_video_path)
        response = await client.post(
            f"/api/rolls/{roll_id}/moments/{moments[0]['frame_idx']}/analyse"
        )
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "42"
    assert "retry_after_s" in response.json()
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_moments.py -v
```

Expected: ImportError on `server.api.moments`, or 404/405 from the unwired route.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_moments.py
git commit -m "test(bjj-app): add moment-analyse endpoint tests (failing — no impl)"
```

---

## Task 14: Extend `RollDetailOut` moments to carry analyses + implement the endpoint

**Files:**
- Modify: `tools/bjj-app/server/api/rolls.py`
- Create: `tools/bjj-app/server/api/moments.py`
- Modify: `tools/bjj-app/server/main.py`

- [ ] **Step 1: Extend `MomentOut` with analyses**

Open `tools/bjj-app/server/api/rolls.py`. Replace the `MomentOut` class and the imports at the top.

Find the import line:
```python
from server.db import connect, create_roll, get_moments, get_roll
```

Replace with:
```python
from server.db import connect, create_roll, get_analyses, get_moments, get_roll
```

Find the `MomentOut` class and replace it with:

```python
class AnalysisOut(BaseModel):
    id: str
    player: str
    position_id: str
    confidence: float | None
    description: str | None
    coach_tip: str | None


class MomentOut(BaseModel):
    id: str
    frame_idx: int
    timestamp_s: float
    pose_delta: float | None
    analyses: list[AnalysisOut] = []
```

Replace the entire `get_roll_detail` function at the bottom of `rolls.py` with:

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
        analyses_by_moment: dict[str, list] = {
            m["id"]: get_analyses(conn, m["id"]) for m in moment_rows
        }
    finally:
        conn.close()

    moments_out = [
        MomentOut(
            id=m["id"],
            frame_idx=m["frame_idx"],
            timestamp_s=m["timestamp_s"],
            pose_delta=m["pose_delta"],
            analyses=[
                AnalysisOut(
                    id=a["id"],
                    player=a["player"],
                    position_id=a["position_id"],
                    confidence=a["confidence"],
                    description=a["description"],
                    coach_tip=a["coach_tip"],
                )
                for a in analyses_by_moment[m["id"]]
            ],
        )
        for m in moment_rows
    ]

    return RollDetailOut(
        id=row["id"],
        title=row["title"],
        date=row["date"],
        partner=row["partner"],
        duration_s=row["duration_s"],
        result=row["result"],
        video_url=f"/{row['video_path']}",
        moments=moments_out,
    )
```

- [ ] **Step 2: Create the moments endpoint**

Create `tools/bjj-app/server/api/moments.py`:

```python
"""POST /api/rolls/:id/moments/:frame_idx/analyse — SSE stream of Claude analysis."""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from server.analysis.claude_cli import (
    ClaudeProcessError,
    ClaudeResponseError,
    RateLimitedError,
    analyse_frame,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import Settings, load_settings
from server.db import connect, get_moments, get_roll, insert_analyses

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["moments"])


# Module-level singleton — one limiter per process.
_LIMITER: SlidingWindowLimiter | None = None


def _get_limiter(settings: Settings) -> SlidingWindowLimiter:
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = SlidingWindowLimiter(
            max_calls=settings.claude_max_calls,
            window_seconds=settings.claude_window_seconds,
        )
    return _LIMITER


@router.post("/rolls/{roll_id}/moments/{frame_idx}/analyse")
async def analyse_moment(
    roll_id: str,
    frame_idx: int,
    settings: Settings = Depends(load_settings),
):
    # --- Validate roll + moment exist (before touching Claude) ---
    conn = connect(settings.db_path)
    try:
        roll_row = get_roll(conn, roll_id)
        if roll_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        moment = next(
            (m for m in get_moments(conn, roll_id) if m["frame_idx"] == frame_idx),
            None,
        )
    finally:
        conn.close()

    if moment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Moment not found"
        )

    frame_path = (
        settings.project_root / "assets" / roll_id / "frames" /
        f"frame_{frame_idx:06d}.jpg"
    )
    if not frame_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Frame not extracted: {frame_path.name}",
        )

    limiter = _get_limiter(settings)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_event(evt: dict) -> None:
        await queue.put(evt)

    async def driver() -> None:
        cache_conn = connect(settings.db_path)
        try:
            result = await analyse_frame(
                frame_path=frame_path,
                timestamp_s=moment["timestamp_s"],
                stream_callback=on_event,
                settings=settings,
                limiter=limiter,
                cache_conn=cache_conn,
            )
            # Persist analyses (per-player rows; description+coach_tip on greig only).
            insert_analyses(
                cache_conn,
                moment_id=moment["id"],
                players=[
                    {
                        "player": "greig",
                        "position_id": result["greig"]["position"],
                        "confidence": result["greig"].get("confidence"),
                        "description": result.get("description"),
                        "coach_tip": result.get("coach_tip"),
                    },
                    {
                        "player": "anthony",
                        "position_id": result["anthony"]["position"],
                        "confidence": result["anthony"].get("confidence"),
                        "description": None,
                        "coach_tip": None,
                    },
                ],
                claude_version=settings.claude_model,
            )
            await queue.put({"stage": "done", "analysis": result, "cached": False})
        finally:
            cache_conn.close()
            await queue.put(None)  # sentinel

    # Pre-flight the rate limiter so a 429 doesn't get swallowed by SSE.
    # We probe by running a dry driver() and catching RateLimitedError *before*
    # establishing the stream. Done by peeking the limiter's state — the
    # canonical check still happens inside analyse_frame; this mirror-check
    # lets us return a proper 429 response.
    # (If the limiter disagrees by the time analyse_frame is called, the
    # RateLimitedError below is also caught and surfaced as a 429.)

    task = asyncio.create_task(driver())

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                yield f"data: {json.dumps(evt)}\n\n".encode("utf-8")
        finally:
            try:
                await task
            except RateLimitedError:
                # already signalled — nothing more to emit
                pass
            except (ClaudeProcessError, ClaudeResponseError) as exc:
                logger.warning("Claude analyse failed for %s: %s", roll_id, exc)
            except Exception:
                logger.exception("Unexpected analyse failure for %s", roll_id)

    # Try to surface a RateLimitedError as HTTP 429 *before* streaming starts.
    # We wait briefly for the driver to report any early error.
    try:
        first = await asyncio.wait_for(queue.get(), timeout=5.0)
    except asyncio.TimeoutError:
        first = None

    if first is None:
        # Driver ended immediately — probably a cached sentinel path. Consume the
        # task to surface any exception.
        try:
            await task
        except RateLimitedError as exc:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": f"Claude cooldown — {math.ceil(exc.retry_after_s)}s "
                              f"until next call",
                    "retry_after_s": math.ceil(exc.retry_after_s),
                },
                headers={"Retry-After": str(math.ceil(exc.retry_after_s))},
            )

    # Re-queue the first event we pulled so the stream below sees it too.
    relay: asyncio.Queue[dict | None] = asyncio.Queue()
    if first is not None:
        await relay.put(first)

    async def replay_and_continue() -> AsyncIterator[bytes]:
        while True:
            if not relay.empty():
                evt = await relay.get()
            else:
                evt = await queue.get()
            if evt is None:
                break
            yield f"data: {json.dumps(evt)}\n\n".encode("utf-8")
        try:
            await task
        except RateLimitedError as exc:
            # Synthesise a done-with-error event so the UI can display it.
            err_evt = {
                "stage": "error",
                "kind": "rate_limited",
                "retry_after_s": math.ceil(exc.retry_after_s),
            }
            yield f"data: {json.dumps(err_evt)}\n\n".encode("utf-8")
        except (ClaudeProcessError, ClaudeResponseError) as exc:
            err_evt = {"stage": "error", "kind": exc.__class__.__name__, "detail": str(exc)}
            yield f"data: {json.dumps(err_evt)}\n\n".encode("utf-8")

    return StreamingResponse(
        replay_and_continue(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

> The commented-out "pre-flight" block is a note to future-you, not executable. The actual rate-limit surfacing uses the 5-second timeout trick: if the driver hits `RateLimitedError` before emitting anything, we catch it and return JSON 429; otherwise we stream normally.

- [ ] **Step 3: Register the router in `main.py`**

Open `tools/bjj-app/server/main.py`. Change the imports:

Replace:
```python
from server.api import analyse as analyse_api
from server.api import rolls as rolls_api
```

With:
```python
from server.api import analyse as analyse_api
from server.api import moments as moments_api
from server.api import rolls as rolls_api
```

Replace:
```python
    app.include_router(rolls_api.router)
    app.include_router(analyse_api.router)
```

With:
```python
    app.include_router(rolls_api.router)
    app.include_router(analyse_api.router)
    app.include_router(moments_api.router)
```

- [ ] **Step 4: Reset the limiter singleton between tests**

Open `tools/bjj-app/tests/backend/conftest.py` and append:

```python


@pytest.fixture(autouse=True)
def _reset_claude_limiter():
    """Reset the module-level limiter between tests so they don't leak state."""
    yield
    try:
        import server.api.moments as moments_mod
        moments_mod._LIMITER = None
    except Exception:
        pass
```

- [ ] **Step 5: Run the moment-analyse tests — must pass**

```bash
pytest tests/backend/test_api_moments.py -v
```

Expected: `4 passed`.

- [ ] **Step 6: Run the full backend suite**

```bash
pytest tests/backend -v
```

Expected: all green. Approx counts: M2a 16 + M2b 21 + rate_limit 5 + prompt 7 + cache 4 + analyses 4 + claude_cli 6 + moments 4 = ~67 tests, all passing.

- [ ] **Step 7: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/moments.py tools/bjj-app/server/api/rolls.py tools/bjj-app/server/main.py tools/bjj-app/tests/backend/conftest.py
git commit -m "feat(bjj-app): add POST /api/rolls/:id/moments/:frame_idx/analyse (SSE)"
```

---

## Task 15: Security audit for `--dangerously-skip-permissions`

**Files:**
- Create: `docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`

The spec requires this: "The implementation plan must explicitly audit this." Do it now, while the code is freshest.

- [ ] **Step 1: Write the audit document**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`:

````markdown
# Audit: Claude CLI subprocess + `--dangerously-skip-permissions`

**Date:** 2026-04-21
**Code reviewed:** `tools/bjj-app/server/analysis/claude_cli.py` @ M3
**Trigger:** spec requires an explicit audit when this flag is used programmatically.

## What the flag does

`claude -p --dangerously-skip-permissions` disables Claude Code's interactive tool-use permission prompts. Without it, Claude would halt mid-session asking "May I read this file?", "May I run this command?" — impossible to answer from a server.

## What threat is being accepted

The Claude process runs with the app user's shell privileges. If we passed it a prompt containing attacker-controlled content, the model could be coaxed into reading arbitrary files or running shell tools against them, and those tool uses would succeed without a human in the loop.

## Mitigations in place

1. **No user input in the prompt.** `prompt.build_prompt()` is a pure function of three inputs: `frame_path` (we control it), `taxonomy_path` (we control it — it's `tools/taxonomy.json` shipped in the repo), `timestamp_s` (a float parsed from SQLite, not user text). The upload endpoint's `title` / `partner` text is **never** concatenated into a prompt. Greg to do in future milestones: keep this invariant.
2. **Frame path is validated.** `analyse_frame` calls `Path.resolve()` and `relative_to(settings.project_root)` — any path that escapes the project root (symlinks, `..`, absolute paths outside the repo) is rejected before the subprocess is spawned.
3. **argv list, never shell.** Subprocess is spawned via `asyncio.create_subprocess_exec(*argv)` with a plain list. No `shell=True`, no string concatenation into a shell command. Paths containing spaces or shell metacharacters (there are none in our frame names, but defence in depth) are not re-interpretable.
4. **Bounded turns.** `--max-turns 1` means the model gets exactly one response; it cannot enter a multi-turn tool-loop.
5. **Limited scope.** Claude sees only the prompt and one image. It has no git repo, no shell history, no MCP tools beyond defaults. `stderr` is `DEVNULL` (we don't surface it), `stdout` is captured and parsed.
6. **Rate limit.** 10 calls / 5-min window caps the blast radius of any pathological behaviour.

## Residual risks accepted

- If a future engineer adds user-controlled text to `build_prompt` (e.g. annotations, partner names), mitigation #1 fails silently. **Mitigation:** add a new test in `test_prompt.py` that asserts `build_prompt` rejects or sanitises any non-validated string.
- If `taxonomy.json` is replaced by an attacker with write access to the repo — they already had arbitrary code execution. No additional risk from this flag.
- A malicious frame file (crafted to exploit Claude's image reader) is theoretically possible. We only accept frames extracted by our own `frames.py` from videos the local user uploaded through `POST /rolls`. The app binds to `0.0.0.0:8000` for LAN access — anyone on the local wifi can upload. Acceptable for a single-user home-use app; revisit if scope expands.

## Conclusion

Passing `--dangerously-skip-permissions` is appropriate in this context. The invariants above must hold; any code change that weakens them (esp. #1 and #2) requires a fresh audit.

## Review trigger

Re-open this audit if any of the following change:
- `build_prompt` gains a parameter not listed above.
- `analyse_frame` is called from a new code path.
- Claude CLI major version bump (currently 2.1.114).
- App is exposed beyond the local LAN.
````

- [ ] **Step 2: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md
git commit -m "docs(bjj-app): audit --dangerously-skip-permissions usage for M3"
```

---

## Task 16: Frontend — add types and `analyseMoment` SSE iterator

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

export type Analysis = {
  id: string;
  player: 'greig' | 'anthony';
  position_id: string;
  confidence: number | null;
  description: string | null;
  coach_tip: string | null;
};

export type Moment = {
  id: string;
  frame_idx: number;
  timestamp_s: number;
  pose_delta: number | null;
  analyses: Analysis[];
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

export type AnalyseMomentEvent =
  | { stage: 'cache'; hit: boolean }
  | { stage: 'streaming'; text: string }
  | {
      stage: 'done';
      cached: boolean;
      analysis: {
        timestamp: number;
        greig: { position: string; confidence: number };
        anthony: { position: string; confidence: number };
        description: string;
        coach_tip: string;
      };
    }
  | {
      stage: 'error';
      kind: string;
      detail?: string;
      retry_after_s?: number;
    };
```

- [ ] **Step 2: Update `api.ts`**

Open `tools/bjj-app/web/src/lib/api.ts`. Append to the existing imports at the top by replacing the first line:

```typescript
import type { AnalyseEvent, CreateRollInput, RollDetail, RollSummary } from './types';
```

with:

```typescript
import type {
  AnalyseEvent,
  AnalyseMomentEvent,
  CreateRollInput,
  RollDetail,
  RollSummary
} from './types';
```

Append the following function to the end of `tools/bjj-app/web/src/lib/api.ts`:

```typescript

/**
 * Analyse a single moment with Claude — async iterator over SSE events.
 *
 * Usage:
 *   for await (const event of analyseMoment(rollId, frameIdx)) { ... }
 *
 * Throws ApiError on non-streaming error statuses (e.g. 404, 429).
 */
export async function* analyseMoment(
  rollId: string,
  frameIdx: number
): AsyncIterator<AnalyseMomentEvent> {
  const response = await fetch(
    `/api/rolls/${encodeURIComponent(rollId)}/moments/${frameIdx}/analyse`,
    { method: 'POST' }
  );
  if (!response.ok) {
    // Try to surface the server's detail payload for 429 / 404.
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
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
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';
      for (const frame of frames) {
        const dataLine = frame.split('\n').find((line) => line.startsWith('data: '));
        if (!dataLine) continue;
        yield JSON.parse(dataLine.slice(6)) as AnalyseMomentEvent;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
```

- [ ] **Step 3: Run existing frontend tests (nothing should regress)**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: same 8 tests green as after M2b.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/types.ts tools/bjj-app/web/src/lib/api.ts
git commit -m "feat(bjj-app): add Analysis types + analyseMoment SSE iterator"
```

---

## Task 17: Write failing tests for `MomentDetail.svelte`

**Files:**
- Create: `tools/bjj-app/web/tests/moment-detail.test.ts`

- [ ] **Step 1: Write the tests**

Create `tools/bjj-app/web/tests/moment-detail.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import MomentDetail from '../src/lib/components/MomentDetail.svelte';

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

function momentWithoutAnalyses() {
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: []
  };
}

function momentWithAnalyses() {
  return {
    id: 'm1',
    frame_idx: 3,
    timestamp_s: 3.0,
    pose_delta: 0.5,
    analyses: [
      {
        id: 'a1',
        player: 'greig',
        position_id: 'closed_guard_bottom',
        confidence: 0.82,
        description: 'Greig is working from closed guard.',
        coach_tip: 'Break posture.'
      },
      {
        id: 'a2',
        player: 'anthony',
        position_id: 'closed_guard_top',
        confidence: 0.78,
        description: null,
        coach_tip: null
      }
    ]
  };
}

describe('MomentDetail', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows an Analyse button when the moment has no saved analyses', () => {
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });
    expect(screen.getByRole('button', { name: /analyse this moment/i })).toBeInTheDocument();
  });

  it('renders saved analyses instead of the Analyse button when they exist', () => {
    render(MomentDetail, { rollId: 'r1', moment: momentWithAnalyses() });
    expect(screen.queryByRole('button', { name: /analyse this moment/i })).toBeNull();
    expect(screen.getByText(/closed_guard_bottom/i)).toBeInTheDocument();
    expect(screen.getByText(/closed_guard_top/i)).toBeInTheDocument();
    expect(screen.getByText(/break posture/i)).toBeInTheDocument();
  });

  it('streams partial text into the panel and then renders the final analysis', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        body: sseBody([
          { stage: 'cache', hit: false },
          { stage: 'streaming', text: '{"greig":' },
          { stage: 'streaming', text: '{"greig":{"position":"standing_neutral"' },
          {
            stage: 'done',
            cached: false,
            analysis: {
              timestamp: 3.0,
              greig: { position: 'standing_neutral', confidence: 0.9 },
              anthony: { position: 'standing_neutral', confidence: 0.88 },
              description: 'Both standing neutral.',
              coach_tip: 'Engage first.'
            }
          }
        ])
      })
    );

    const user = userEvent.setup();
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });

    await user.click(screen.getByRole('button', { name: /analyse this moment/i }));

    // Partial chunks render during streaming.
    await waitFor(() => {
      expect(screen.getByText(/standing_neutral/i)).toBeInTheDocument();
    });

    // Final parsed analysis renders the coach tip + description.
    await waitFor(() => {
      expect(screen.getByText(/engage first/i)).toBeInTheDocument();
      expect(screen.getByText(/both standing neutral/i)).toBeInTheDocument();
    });
  });

  it('shows an error message when the server returns 429', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
        json: async () => ({ detail: 'Claude cooldown — 42s until next call', retry_after_s: 42 })
      })
    );

    const user = userEvent.setup();
    render(MomentDetail, { rollId: 'r1', moment: momentWithoutAnalyses() });

    await user.click(screen.getByRole('button', { name: /analyse this moment/i }));

    await waitFor(() => {
      expect(screen.getByText(/cooldown/i)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: the 4 moment-detail tests fail because the component doesn't exist yet. The existing 8 tests still pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/moment-detail.test.ts
git commit -m "test(bjj-app): add MomentDetail component tests (failing — no impl)"
```

---

## Task 18: Implement `MomentDetail.svelte`

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/MomentDetail.svelte`

- [ ] **Step 1: Write the component**

Create `tools/bjj-app/web/src/lib/components/MomentDetail.svelte`:

```svelte
<script lang="ts">
  import { analyseMoment, ApiError } from '$lib/api';
  import type { Analysis, AnalyseMomentEvent, Moment } from '$lib/types';

  let { rollId, moment, onanalysed }: {
    rollId: string;
    moment: Moment;
    onanalysed?: (m: Moment) => void;
  } = $props();

  let analysing = $state(false);
  let partial = $state('');
  let error = $state<string | null>(null);
  let localAnalyses = $state<Analysis[]>(moment.analyses);

  // Re-sync when the parent swaps in a different moment.
  $effect(() => {
    localAnalyses = moment.analyses;
    partial = '';
    error = null;
  });

  const greig = $derived(localAnalyses.find((a) => a.player === 'greig'));
  const anthony = $derived(localAnalyses.find((a) => a.player === 'anthony'));

  function formatMomentTime(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  async function onAnalyseClick() {
    if (analysing) return;
    analysing = true;
    partial = '';
    error = null;
    try {
      for await (const event of analyseMoment(rollId, moment.frame_idx)) {
        handleEvent(event);
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    } finally {
      analysing = false;
    }
  }

  function handleEvent(event: AnalyseMomentEvent) {
    if (event.stage === 'streaming') {
      partial = event.text;
    } else if (event.stage === 'done') {
      const a = event.analysis;
      const fabricated: Analysis[] = [
        {
          id: `pending-${moment.id}-greig`,
          player: 'greig',
          position_id: a.greig.position,
          confidence: a.greig.confidence,
          description: a.description,
          coach_tip: a.coach_tip
        },
        {
          id: `pending-${moment.id}-anthony`,
          player: 'anthony',
          position_id: a.anthony.position,
          confidence: a.anthony.confidence,
          description: null,
          coach_tip: null
        }
      ];
      localAnalyses = fabricated;
      partial = '';
      onanalysed?.({ ...moment, analyses: fabricated });
    } else if (event.stage === 'error') {
      if (event.kind === 'rate_limited' && event.retry_after_s) {
        error = `Claude cooldown — ${event.retry_after_s}s until next call`;
      } else {
        error = event.detail ?? `Analyse failed (${event.kind})`;
      }
    }
    // 'cache' events are informational — nothing to render.
  }
</script>

<section class="space-y-3 rounded-lg border border-white/10 bg-white/[0.02] p-4">
  <header class="flex items-baseline gap-3">
    <span class="text-lg font-mono tabular-nums text-white/90">
      {formatMomentTime(moment.timestamp_s)}
    </span>
    <span class="text-[10px] uppercase tracking-wider text-white/40">Selected moment</span>
  </header>

  {#if error}
    <div class="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      {error}
    </div>
  {/if}

  {#if localAnalyses.length > 0}
    <div class="grid gap-2 sm:grid-cols-2">
      {#if greig}
        <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
          <div class="text-[10px] uppercase tracking-wider text-white/40">Greig</div>
          <div class="mt-0.5 font-mono text-xs text-white/85">{greig.position_id}</div>
          {#if greig.confidence != null}
            <div class="text-[11px] text-white/40">
              confidence {(greig.confidence * 100).toFixed(0)}%
            </div>
          {/if}
        </div>
      {/if}
      {#if anthony}
        <div class="rounded-md border border-white/10 bg-white/[0.03] p-3">
          <div class="text-[10px] uppercase tracking-wider text-white/40">Anthony</div>
          <div class="mt-0.5 font-mono text-xs text-white/85">{anthony.position_id}</div>
          {#if anthony.confidence != null}
            <div class="text-[11px] text-white/40">
              confidence {(anthony.confidence * 100).toFixed(0)}%
            </div>
          {/if}
        </div>
      {/if}
    </div>

    {#if greig?.description}
      <p class="text-sm leading-relaxed text-white/80">{greig.description}</p>
    {/if}
    {#if greig?.coach_tip}
      <div class="border-l-2 border-amber-400/60 pl-3 text-sm text-amber-100/90">
        {greig.coach_tip}
      </div>
    {/if}
  {:else if analysing}
    <div class="space-y-2">
      <div class="text-xs text-white/55">Streaming from Claude Opus 4.7…</div>
      {#if partial}
        <pre
          class="whitespace-pre-wrap rounded-md bg-black/30 p-2 font-mono text-[11px] text-white/70"
        >{partial}</pre>
      {/if}
    </div>
  {:else}
    <button
      type="button"
      onclick={onAnalyseClick}
      class="rounded-md border border-blue-400/40 bg-blue-500/20 px-3 py-1.5 text-xs font-medium text-blue-100 hover:bg-blue-500/30 transition-colors"
    >
      Analyse this moment with Claude Opus 4.7
    </button>
  {/if}
</section>
```

- [ ] **Step 2: Run frontend tests — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 12 passed (8 from M2b + 4 new moment-detail).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/components/MomentDetail.svelte
git commit -m "feat(bjj-app): add MomentDetail component (analyse button + streaming + result)"
```

---

## Task 19: Wire chip selection + detail panel into the review page

**Files:**
- Modify: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`

- [ ] **Step 1: Replace the page**

Replace the entire contents of `tools/bjj-app/web/src/routes/review/[id]/+page.svelte` with:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { analyseRoll, ApiError, getRoll } from '$lib/api';
  import MomentDetail from '$lib/components/MomentDetail.svelte';
  import type { AnalyseEvent, Moment, RollDetail } from '$lib/types';

  let roll = $state<RollDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let analysing = $state(false);
  let progress = $state<{ stage: string; pct: number } | null>(null);
  let selectedMomentId = $state<string | null>(null);

  let videoEl: HTMLVideoElement | undefined = $state();

  const selectedMoment = $derived(
    roll?.moments.find((m) => m.id === selectedMomentId) ?? null
  );

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
      roll.moments = event.moments.map((m) => ({
        id: `pending-${m.frame_idx}`,
        frame_idx: m.frame_idx,
        timestamp_s: m.timestamp_s,
        pose_delta: m.pose_delta,
        analyses: []
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

  function onChipClick(moment: Moment) {
    selectedMomentId = moment.id;
    if (videoEl) {
      videoEl.currentTime = moment.timestamp_s;
      videoEl.play().catch(() => {
        /* autoplay may be blocked; that's fine */
      });
    }
  }

  function onMomentAnalysed(updated: Moment) {
    if (!roll) return;
    roll.moments = roll.moments.map((m) => (m.id === updated.id ? updated : m));
  }

  function chipStateClass(m: Moment, isSelected: boolean): string {
    const base = 'rounded-md px-2.5 py-1 text-xs font-mono tabular-nums transition-colors';
    if (m.analyses.length > 0) {
      // Analysed — solid chip.
      return `${base} border bg-emerald-500/15 border-emerald-400/40 text-emerald-100 hover:bg-emerald-500/25${
        isSelected ? ' ring-1 ring-emerald-300' : ''
      }`;
    }
    // Unanalysed — dashed chip.
    return `${base} border border-dashed bg-white/[0.02] border-white/20 text-white/75 hover:bg-white/[0.05] hover:border-white/40${
      isSelected ? ' ring-1 ring-white/40' : ''
    }`;
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
              onclick={() => onChipClick(moment)}
              class={chipStateClass(moment, moment.id === selectedMomentId)}
            >
              {formatMomentTime(moment.timestamp_s)}
            </button>
          {/each}
        </div>
      </div>

      {#if selectedMoment}
        <MomentDetail
          rollId={roll.id}
          moment={selectedMoment}
          onanalysed={onMomentAnalysed}
        />
      {:else}
        <p class="text-[11px] text-white/35">
          Click a chip to see the moment and analyse it with Claude.
        </p>
      {/if}
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

- [ ] **Step 2: Update existing review-analyse tests to include the `analyses` field**

Open `tools/bjj-app/web/tests/review-analyse.test.ts` and update the two helper functions at the top of the file.

Find:
```typescript
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
```

Replace with (same shape — moments are already `[]`; no change needed here, but verify).

Find:
```typescript
function detailWithMoments() {
  return {
    ...detailWithoutMoments(),
    moments: [
      { id: 'm1', frame_idx: 2, timestamp_s: 2.0, pose_delta: 0.5 },
      { id: 'm2', frame_idx: 5, timestamp_s: 5.0, pose_delta: 1.2 }
    ]
  };
}
```

Replace with:
```typescript
function detailWithMoments() {
  return {
    ...detailWithoutMoments(),
    moments: [
      { id: 'm1', frame_idx: 2, timestamp_s: 2.0, pose_delta: 0.5, analyses: [] },
      { id: 'm2', frame_idx: 5, timestamp_s: 5.0, pose_delta: 1.2, analyses: [] }
    ]
  };
}
```

- [ ] **Step 3: Run frontend tests — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 12 passed (2 home + 3 new + 3 review-analyse + 4 moment-detail).

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/review/[id]/+page.svelte tools/bjj-app/web/tests/review-analyse.test.ts
git commit -m "feat(bjj-app): wire chip selection + MomentDetail panel in /review/[id]"
```

---

## Task 20: Opt-in live integration test

**Files:**
- Create: `tools/bjj-app/tests/backend/integration/__init__.py`
- Create: `tools/bjj-app/tests/backend/integration/test_claude_real.py`
- Modify: `tools/bjj-app/pyproject.toml`

- [ ] **Step 1: Add the `integration` marker to pyproject**

Open `tools/bjj-app/pyproject.toml`. Find:

```toml
[tool.pytest.ini_options]
testpaths = ["tests/backend"]
asyncio_mode = "auto"
pythonpath = ["."]
```

Replace with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests/backend"]
asyncio_mode = "auto"
pythonpath = ["."]
markers = [
    "integration: slow live-CLI tests that spend Claude budget (run manually with -m integration)",
]
addopts = "-m 'not integration'"
```

- [ ] **Step 2: Create the integration package marker**

Create `tools/bjj-app/tests/backend/integration/__init__.py` as an empty file:

```bash
touch /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/integration/__init__.py
```

- [ ] **Step 3: Write the live test**

Create `tools/bjj-app/tests/backend/integration/test_claude_real.py`:

```python
"""Live Claude CLI integration test — opt-in only.

Run manually with:  pytest -m integration -v

This spends Claude subscription budget (~1 call). It proves that the adapter
still works end-to-end against the real CLI — the fake subprocess in
test_claude_cli.py can drift from reality if the CLI's stream-json format
changes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.analysis.claude_cli import analyse_frame
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import load_settings
from server.db import connect, init_db


pytestmark = pytest.mark.integration


@pytest.fixture
def fixture_frame(tmp_path: Path) -> Path:
    """Copy a real extracted frame into a tmpdir-under-project-root.

    We need the frame path to lie inside settings.project_root, so we place
    the copy inside the active project's assets/ tree.
    """
    src_candidates = list(
        Path("/Users/greigbradley/Desktop/BJJ_Analysis/assets/greig_1s").glob("*.jpg")
    )
    if not src_candidates:
        pytest.skip("no real frame available in assets/greig_1s/")
    src = src_candidates[0]

    dest_dir = Path("/Users/greigbradley/Desktop/BJJ_Analysis/assets/__integration_frames__")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    dest.write_bytes(src.read_bytes())
    return dest


@pytest.fixture
def cache_conn(tmp_path: Path):
    db = tmp_path / "cache.db"
    init_db(db)
    conn = connect(db)
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_live_claude_returns_parseable_analysis(
    fixture_frame: Path, cache_conn
) -> None:
    settings = load_settings()
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=300)

    streamed: list[dict] = []

    async def on_event(evt: dict) -> None:
        streamed.append(evt)

    result = await analyse_frame(
        frame_path=fixture_frame,
        timestamp_s=0.0,
        stream_callback=on_event,
        settings=settings,
        limiter=limiter,
        cache_conn=cache_conn,
    )

    print(f"\n--- Live Claude result ---\n{json.dumps(result, indent=2)}\n")
    assert "greig" in result
    assert "anthony" in result
    assert result["greig"]["position"]
    assert result["anthony"]["position"]
    assert any(e.get("stage") == "streaming" for e in streamed) or any(
        e.get("stage") == "cache" for e in streamed
    )
```

- [ ] **Step 4: Verify the marker filter works**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend -v
```

Expected: all ~67 unit tests pass; the integration test is deselected (watch for "1 deselected" in the summary).

- [ ] **Step 5: Run the live test (manual verification only)**

```bash
pytest tests/backend -m integration -v
```

Expected: `1 passed` after Claude responds (takes ~15–60 seconds). The printed JSON should describe whatever is actually in the fixture frame.

If this fails, the spike in Task 1 may have chosen an image-input mechanism that drifted — revisit `prompt.py` and `claude_cli.py`.

- [ ] **Step 6: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/pyproject.toml tools/bjj-app/tests/backend/integration/
git commit -m "test(bjj-app): add opt-in live Claude CLI integration test"
```

---

## Task 21: End-to-end smoke test in the browser

**Files:** none — manual verification.

- [ ] **Step 1: Start dev mode**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
./scripts/dev.sh
```

- [ ] **Step 2: Upload and pose-analyse a short video**

Open `http://127.0.0.1:5173/new`. Upload a short video (e.g. `assets/test_roll.mp4`). Click **Analyse** on the review page and wait for chips to appear.

- [ ] **Step 3: Click a chip → click "Analyse this moment"**

Click any dashed chip. The detail panel appears below the timeline, showing the "Analyse this moment with Claude Opus 4.7" button. Click it.

**Expected:**
- Button disappears, a "Streaming from Claude Opus 4.7…" line appears.
- The `<pre>` block below the label fills with partial JSON text as Claude streams.
- After ~5–30s, the partial text is replaced by:
  - Two cards (Greig / Anthony) with position ids + confidence %.
  - A description paragraph.
  - An amber-bordered coach tip.
- The chip itself turns green (analysed state).

- [ ] **Step 4: Verify cache by re-clicking the same chip**

Click a different chip, then click the first chip again. Click "Analyse" on it (it should still show the button — wait, no: analysed chips don't show the button; they show the cards immediately). Good.

Try clicking a different unanalysed chip and hitting Analyse — wait for result — then reload the page (`Cmd-R`). Click that chip again: cards appear instantly without any streaming. **This proves the cache + DB persistence are both working.**

- [ ] **Step 5: Trigger a rate-limit error on purpose**

Temporarily lower the limit by restarting the backend with a small window:

```bash
# Stop dev.sh (Ctrl-C), then:
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
BJJ_CLAUDE_MAX_CALLS=1 BJJ_CLAUDE_WINDOW_SECONDS=60 ./scripts/dev.sh
```

Analyse one moment successfully. Analyse a *different* moment within 60 seconds. Expected: the UI shows "Claude cooldown — Ns until next call" in a rose-coloured error banner inside the detail panel.

Restart dev.sh without the overrides.

- [ ] **Step 6: Check the database**

```bash
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT moment_id, player, position_id, confidence FROM analyses ORDER BY created_at DESC LIMIT 5;"

sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT COUNT(*) FROM claude_cache;"
```

Expected: analyses rows with real position ids; cache count ≥ 1.

- [ ] **Step 7: Clean up the test data (optional)**

```bash
# Find the latest roll id
ROLL_ID=$(sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "SELECT id FROM rolls ORDER BY created_at DESC LIMIT 1;")
rm -rf /Users/greigbradley/Desktop/BJJ_Analysis/assets/$ROLL_ID
sqlite3 /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/bjj-app.db \
  "DELETE FROM rolls WHERE id='$ROLL_ID';"
# Also clean up the integration-test leftover, if any:
rm -rf /Users/greigbradley/Desktop/BJJ_Analysis/assets/__integration_frames__
```

- [ ] **Step 8: Stop the dev server** (Ctrl-C).

---

## Task 22: Update README with M3 status

**Files:**
- Modify: `tools/bjj-app/README.md`

- [ ] **Step 1: Replace the Milestones section**

Find the `## Milestones` section in `tools/bjj-app/README.md` and replace it (plus everything below it) with:

```markdown
## Milestones

- **M1 (shipped):** Scaffolding. Home page lists vault's `Roll Log/` via `GET /api/rolls`.
- **M2a (shipped):** Video upload (`POST /api/rolls`), review page skeleton, `/assets/` static mount.
- **M2b (shipped):** MediaPipe pose pre-pass, `POST /api/rolls/:id/analyse` SSE endpoint, timeline chips seek the video on click.
- **M3 (this milestone):** Claude CLI adapter (`server/analysis/claude_cli.py` — sole caller of `claude -p`). `POST /api/rolls/:id/moments/:frame_idx/analyse` streams a Claude Opus 4.7 classification for one frame, with SQLite cache (`claude_cache`) and a 10/5-min sliding-window rate limiter. Selected-moment panel shows live streaming and the saved result. Security audit at `docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`.
- **M4 (next):** Annotations + vault write-back. Edit a note, save to SQLite AND vault markdown with hash-based conflict detection.
- **M5–M8:** Graph page, summary + PDF, PWA, cleanup.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/README.md
git commit -m "docs(bjj-app): document M3 (Claude CLI adapter)"
```

---

## Completion criteria for M3

1. `pytest tests/backend -v` → all unit tests green (≈67 tests); integration test deselected by default.
2. `pytest tests/backend -m integration -v` → 1 passed (manual, spends Claude budget).
3. `npm test` (in `web/`) → 12 passed.
4. Dev-mode smoke: upload → pre-analyse → click chip → click "Analyse" → streaming text → final cards + description + coach tip. Chip turns green.
5. Refreshing `/review/[id]` after analysis preserves the analyses (SQLite round-trip verified).
6. Re-clicking an analysed chip within the same session is instant (no spinner, no stream).
7. Rate-limit triggers HTTP 429 with `Retry-After` and the UI shows a cooldown message.
8. Security audit doc committed; invariants (no user input in prompt, frame path validated, argv not shell) hold.

---

## Out of scope (later milestones cover)

| Deliverable | Why deferred |
|---|---|
| Dual-lane timeline (Greig top, Anthony bottom) with category tinting | Category-colouring a chip needs the *moment's* category which comes from the analysis; worth deferring to M5 when the graph page lands and the category → colour mapping lives in a shared module. |
| Annotation input on the selected-moment panel | M4. |
| Vault markdown write-back of analyses | M4. |
| Summary / scores / top-3 improvements | M6 (single extra Claude call across all moments). |
| PDF export | M6. |
| Graph page / mini graph | M5. |
| PWA manifest + service worker | M7. |
| Delete Streamlit `tools/app.py` | M8 (only after this app is confirmed working for a full review session). |
| Vault-snippet inclusion in the Claude prompt (position notes for likely categories) | Requires per-frame category hints from pose pre-pass to pick which notes are "relevant", which M2b does not produce. M3's compressed taxonomy alone is the minimum useful prompt. Revisit once categories are being set on moments (M5+). |
