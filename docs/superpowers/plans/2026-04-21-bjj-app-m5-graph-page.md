# BJJ App M5 — Graph Page + Mini Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the full `/graph` page (clustered state-space view with both players' paths overlaid, filter chips, side-panel vault notes, and a smoothly-animated timeline scrubber) plus a mini graph widget on `/review/[id]` that shares the same `GraphCluster` component with a `variant="mini"` prop.

**Architecture:** Cytoscape.js (via CDN) renders everything. Three new backend endpoints serve taxonomy data, per-roll path reconstructions, and vault position markdown — all read-only and cached at startup. Frontend decomposes into four small components (`GraphCluster`, `GraphScrubber`, `FilterChips`, `PositionDrawer`) orchestrated by the `/graph` page. Pure functions (`buildTaxonomyGraph`, `buildPathOverlays`, `headPositionAt`) hold the math and get tested in isolation; Cytoscape glue is thin.

**Tech Stack:** Cytoscape.js 3.28 + cytoscape-cose-bilkent 4.1 (compound cluster layout) via CDN. `marked.js` via CDN for markdown rendering in the side drawer. FastAPI for the three new endpoints. Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`) matching existing patterns. No npm dependency additions.

**Scope (M5 only):**
- Backend: `server/analysis/taxonomy.py`, `server/analysis/positions_vault.py`, `server/api/graph.py`. Three GET endpoints.
- `server/main.py` builds taxonomy + positions_index at startup via `app.state`.
- Frontend: `GraphCluster.svelte`, `GraphScrubber.svelte`, `FilterChips.svelte`, `PositionDrawer.svelte`, `/graph/+page.svelte`, plus mini-graph mount on `/review/[id]`.
- Pure utility module `web/src/lib/graph-layout.ts` for the interpolation math + Cytoscape element builders.
- CDN tags in `web/src/app.html`.

**Explicitly out of scope (per spec):**
- Auto-play button on the scrubber (manual drag only).
- Bidirectional video↔graph sync (graph is standalone).
- Wikilink navigation inside the drawer.
- Graph export (PNG/SVG).
- Custom node positioning.
- Listing unpublished (SQLite-only) rolls in the `/graph` dropdown — only published rolls (those with vault markdown) appear.

---

## File Structure

```
tools/bjj-app/
├── server/
│   ├── analysis/
│   │   ├── taxonomy.py                  # NEW: load_taxonomy + TINTS dict
│   │   └── positions_vault.py           # NEW: load_positions_index + get_position
│   ├── api/
│   │   └── graph.py                     # NEW: GET /api/graph, /api/graph/paths/:id, /api/vault/position/:id
│   └── main.py                          # MODIFY: build taxonomy + positions index at startup; register graph_api
├── tests/backend/
│   ├── test_taxonomy.py                 # NEW
│   ├── test_positions_vault.py          # NEW
│   ├── test_api_graph.py                # NEW: /api/graph + /api/vault/position/:id
│   └── test_api_graph_paths.py          # NEW: /api/graph/paths/:roll_id
└── web/
    ├── src/
    │   ├── app.html                     # MODIFY: add cytoscape + cose-bilkent + marked.js CDN <script> tags
    │   ├── lib/
    │   │   ├── api.ts                   # MODIFY: add getGraph, getGraphPaths, getPositionNote
    │   │   ├── types.ts                 # MODIFY: add GraphCategory, GraphNode, GraphEdge, GraphTaxonomy, GraphPaths, PathPoint, PositionNote, GraphFilter
    │   │   ├── graph-layout.ts          # NEW: pure helpers (buildTaxonomy Cytoscape elements, buildPathOverlays, headPositionAt, lerp)
    │   │   └── components/
    │   │       ├── FilterChips.svelte             # NEW
    │   │       ├── GraphScrubber.svelte           # NEW
    │   │       ├── PositionDrawer.svelte          # NEW
    │   │       └── GraphCluster.svelte            # NEW: the Cytoscape host
    │   └── routes/
    │       ├── graph/+page.svelte                 # NEW: /graph full page
    │       └── review/[id]/+page.svelte           # MODIFY: mount <GraphCluster variant="mini"> under MomentDetail
    └── tests/
        ├── graph-layout.test.ts                   # NEW (pure-function unit tests)
        ├── filter-chips.test.ts                   # NEW
        ├── graph-scrubber.test.ts                 # NEW
        ├── position-drawer.test.ts                # NEW
        ├── graph-cluster.test.ts                  # NEW
        ├── graph-page.test.ts                     # NEW
        └── review-analyse.test.ts                 # MODIFY: mini graph mounts when moment selected
```

### Responsibilities

- **`taxonomy.py`** — Pure reader. `load_taxonomy(path) -> dict` reads `tools/taxonomy.json`, attaches the hardcoded `TINTS` palette to categories, returns a frozen shape. Raises if the file is missing or malformed.
- **`positions_vault.py`** — `load_positions_index(vault_root) -> dict[str, PositionNote]`. Scans `Positions/*.md`, parses frontmatter, builds `{position_id: {name, markdown, vault_path}}`. Positions without `position_id` in frontmatter are silently skipped. `get_position(index, position_id) -> PositionNote | None`.
- **`api/graph.py`** — Thin HTTP shell. Three routes: `/graph`, `/graph/paths/:roll_id`, `/vault/position/:position_id`. Each reads from `app.state.taxonomy` or `app.state.positions_index` (built at startup) + SQLite for per-roll paths.
- **`graph-layout.ts`** — Pure functions, no DOM access. Tests run in vitest without needing Cytoscape:
  - `buildCytoscapeElements(taxonomy, paths?)`: returns `{nodes, edges}` in Cytoscape's `elements` format.
  - `headPositionAt(path, scrubTimeS, nodeLookup)`: returns `{x, y} | null` — the interpolated head marker coordinate.
  - `lerp(a, b, t)` — utility.
- **`GraphCluster.svelte`** — Cytoscape host. Takes `variant: 'full' | 'mini'`, `taxonomy`, `paths?`, `scrubTimeS?`, `filter?`, `onnodeclick?`. Emits node clicks. Reactively updates via `$effect` when `scrubTimeS` or `filter` change.
- **`GraphScrubber.svelte`** — Range input + "Open in review" link. Takes `scrubTimeS`, `durationS`, `rollId`, `onscrubchange`.
- **`FilterChips.svelte`** — Chip row with "All" + per-category + per-player. Takes `categories`, `activeFilter`, `onfilterchange`.
- **`PositionDrawer.svelte`** — Right-side drawer modal. Takes `open`, `positionNote: PositionNote | null`, `onclose`. Renders markdown via `marked` (CDN global).

### Wire types

```typescript
type GraphCategory = { id: string; label: string; dominance: number; tint: string };
type GraphNode    = { id: string; name: string; category: string };
type GraphEdge    = { from: string; to: string };
type GraphTaxonomy = { categories: GraphCategory[]; positions: GraphNode[]; transitions: GraphEdge[] };

type PathPoint   = { timestamp_s: number; position_id: string; moment_id: string };
type GraphPaths  = {
  duration_s: number | null;
  paths: { greig: PathPoint[]; anthony: PathPoint[] };
};

type PositionNote = {
  position_id: string;
  name: string;
  markdown: string;
  vault_path: string;
};

type GraphFilter =
  | { kind: 'all' }
  | { kind: 'category'; id: string }
  | { kind: 'player'; who: 'greig' | 'anthony' };
```

---

## Task 1: Taxonomy module — failing tests

**Files:**
- Create: `tools/bjj-app/tests/backend/test_taxonomy.py`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_taxonomy.py`:

```python
"""Tests for taxonomy loading + tint attachment."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.analysis.taxonomy import TINTS, load_taxonomy


@pytest.fixture
def tiny_taxonomy(tmp_path: Path) -> Path:
    data = {
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing - Neutral",
             "category": "standing", "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "Closed Guard (Bottom)",
             "category": "guard_bottom", "visual_cues": "b"},
        ],
        "valid_transitions": [
            ["standing_neutral", "closed_guard_bottom"],
            ["closed_guard_bottom", "standing_neutral"],
        ],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data))
    return path


def test_tints_cover_all_canonical_categories():
    # The real taxonomy has 7 canonical categories — each must have a tint.
    expected = {
        "standing", "guard_bottom", "guard_top", "dominant_top",
        "inferior_bottom", "leg_entanglement", "scramble",
    }
    assert expected.issubset(set(TINTS.keys()))


def test_load_taxonomy_returns_categories_positions_transitions(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    assert set(tax.keys()) == {"categories", "positions", "transitions"}


def test_load_taxonomy_attaches_tint_to_each_category(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    for cat in tax["categories"]:
        assert "tint" in cat
        assert isinstance(cat["tint"], str)
        assert cat["tint"].startswith("#")


def test_load_taxonomy_category_shape(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    standing = next(c for c in tax["categories"] if c["id"] == "standing")
    assert standing["label"] == "Standing"
    assert standing["dominance"] == 0


def test_load_taxonomy_positions_shape(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    sn = next(p for p in tax["positions"] if p["id"] == "standing_neutral")
    assert sn["name"] == "Standing - Neutral"
    assert sn["category"] == "standing"


def test_load_taxonomy_transitions_shape(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    assert {"from": "standing_neutral", "to": "closed_guard_bottom"} in tax["transitions"]
    assert {"from": "closed_guard_bottom", "to": "standing_neutral"} in tax["transitions"]


def test_load_taxonomy_raises_when_file_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_taxonomy(tmp_path / "nope.json")


def test_load_taxonomy_real_file_has_44_positions_and_7_categories():
    # Integration: against the real tools/taxonomy.json shipped in the repo.
    real = Path(__file__).parent.parent.parent.parent / "taxonomy.json"
    if not real.exists():
        pytest.skip("real taxonomy.json not present at expected path")
    tax = load_taxonomy(real)
    assert len(tax["positions"]) == 44
    assert len(tax["categories"]) == 7
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_taxonomy.py -v
```

Expected: ImportError on `server.analysis.taxonomy`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_taxonomy.py
git commit -m "test(bjj-app): add taxonomy loader tests (failing — no impl)"
```

---

## Task 2: Taxonomy module — implementation

**Files:**
- Create: `tools/bjj-app/server/analysis/taxonomy.py`

- [ ] **Step 1: Write `taxonomy.py`**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/analysis/taxonomy.py`:

```python
"""Taxonomy loader for the BJJ Graph page.

Parses `tools/taxonomy.json` and exposes a frontend-ready shape with
category tints attached. Shipped once at app startup; no runtime IO.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class Category(TypedDict):
    id: str
    label: str
    dominance: int
    tint: str


class Position(TypedDict):
    id: str
    name: str
    category: str


class Transition(TypedDict):
    from_: str  # serialised as "from" in JSON
    to: str


class Taxonomy(TypedDict):
    categories: list[Category]
    positions: list[Position]
    transitions: list[dict]  # {"from": str, "to": str}


TINTS: dict[str, str] = {
    "standing":          "#e6f2ff",  # pale blue
    "guard_bottom":      "#e6f7e6",  # pale green
    "guard_top":         "#fff5e6",  # pale orange
    "dominant_top":      "#ffe6e6",  # pale red
    "inferior_bottom":   "#f0e6ff",  # pale purple
    "leg_entanglement":  "#fff9cc",  # pale yellow
    "scramble":          "#eeeeee",  # pale grey
}
_FALLBACK_TINT = "#dddddd"


def load_taxonomy(path: Path) -> Taxonomy:
    """Load and shape the taxonomy for the graph API.

    Adds a `tint` field to each category by keying into TINTS (or a fallback).
    Converts `valid_transitions` from [from, to] pairs into {"from","to"} objects.
    Raises FileNotFoundError if path doesn't exist.
    """
    raw = json.loads(path.read_text())

    categories: list[Category] = [
        {
            "id": cat_id,
            "label": cat["label"],
            "dominance": int(cat.get("dominance", 0)),
            "tint": TINTS.get(cat_id, _FALLBACK_TINT),
        }
        for cat_id, cat in raw["categories"].items()
    ]

    positions: list[Position] = [
        {"id": p["id"], "name": p["name"], "category": p["category"]}
        for p in raw["positions"]
    ]

    transitions = [{"from": f, "to": t} for f, t in raw["valid_transitions"]]

    return {
        "categories": categories,
        "positions": positions,
        "transitions": transitions,
    }
```

- [ ] **Step 2: Run — must pass**

```bash
pytest tests/backend/test_taxonomy.py -v
```

Expected: 8 passed.

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/taxonomy.py
git commit -m "feat(bjj-app): add taxonomy loader with category tints"
```

---

## Task 3: Positions-vault index — failing tests

**Files:**
- Create: `tools/bjj-app/tests/backend/test_positions_vault.py`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_positions_vault.py`:

```python
"""Tests for the Positions/ vault index."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.analysis.positions_vault import get_position, load_positions_index


def _write_position(root: Path, filename: str, frontmatter_lines: list[str], body: str) -> None:
    pos_dir = root / "Positions"
    pos_dir.mkdir(exist_ok=True)
    text = "---\n" + "\n".join(frontmatter_lines) + "\n---\n\n" + body
    (pos_dir / filename).write_text(text)


def test_load_positions_index_returns_empty_when_positions_dir_missing(tmp_path: Path):
    assert load_positions_index(tmp_path) == {}


def test_load_positions_index_includes_position_with_position_id_frontmatter(tmp_path: Path):
    _write_position(
        tmp_path,
        "Closed Guard (Bottom).md",
        ['category: "Guard (Bottom)"', "position_id: closed_guard_bottom"],
        "# Closed Guard (Bottom)\n\nBody text.\n",
    )
    idx = load_positions_index(tmp_path)
    assert "closed_guard_bottom" in idx
    entry = idx["closed_guard_bottom"]
    assert entry["name"] == "Closed Guard (Bottom)"
    assert "Body text." in entry["markdown"]
    assert entry["vault_path"] == "Positions/Closed Guard (Bottom).md"


def test_load_positions_index_skips_position_without_position_id(tmp_path: Path):
    _write_position(
        tmp_path,
        "Nameless.md",
        ['category: "Other"'],
        "# Nameless\n",
    )
    assert load_positions_index(tmp_path) == {}


def test_load_positions_index_name_falls_back_to_first_h1(tmp_path: Path):
    _write_position(
        tmp_path,
        "fallback.md",
        ["position_id: abc"],
        "# My Cool Position\n\nDetails.\n",
    )
    idx = load_positions_index(tmp_path)
    assert idx["abc"]["name"] == "My Cool Position"


def test_load_positions_index_name_falls_back_to_stem_if_no_h1(tmp_path: Path):
    _write_position(tmp_path, "stem-name.md", ["position_id: abc"], "No header.\n")
    idx = load_positions_index(tmp_path)
    assert idx["abc"]["name"] == "stem-name"


def test_get_position_returns_entry_for_known_id(tmp_path: Path):
    _write_position(
        tmp_path,
        "A.md",
        ["position_id: a"],
        "# A\nbody",
    )
    idx = load_positions_index(tmp_path)
    entry = get_position(idx, "a")
    assert entry is not None
    assert entry["position_id"] == "a"


def test_get_position_returns_none_for_unknown_id(tmp_path: Path):
    idx: dict = {}
    assert get_position(idx, "nope") is None


def test_load_positions_index_markdown_body_includes_frontmatter_removed(tmp_path: Path):
    _write_position(
        tmp_path,
        "body.md",
        ["position_id: b"],
        "# B\n\nSecond line.\n",
    )
    idx = load_positions_index(tmp_path)
    md = idx["b"]["markdown"]
    # frontmatter delimiters should not be present in the markdown body
    assert md.strip().startswith("# B")
    assert "---" not in md.split("\n")[0]
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_positions_vault.py -v
```

Expected: ImportError on `server.analysis.positions_vault`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_positions_vault.py
git commit -m "test(bjj-app): add positions vault index tests (failing — no impl)"
```

---

## Task 4: Positions-vault index — implementation

**Files:**
- Create: `tools/bjj-app/server/analysis/positions_vault.py`

- [ ] **Step 1: Write `positions_vault.py`**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/analysis/positions_vault.py`:

```python
"""Index of Positions/*.md vault files keyed by position_id from frontmatter.

Built once at app startup in main.create_app(). Looked up by the /api/vault/position/:id
endpoint to serve the side-drawer markdown.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

import frontmatter

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class PositionNote(TypedDict):
    position_id: str
    name: str
    markdown: str
    vault_path: str  # relative to vault root


def load_positions_index(vault_root: Path) -> dict[str, PositionNote]:
    """Scan vault_root/Positions/*.md and return an index keyed by position_id.

    Positions without a `position_id` field in frontmatter are silently skipped.
    Missing `Positions/` directory returns an empty dict.
    """
    positions_dir = vault_root / "Positions"
    if not positions_dir.is_dir():
        return {}

    index: dict[str, PositionNote] = {}
    for md_path in sorted(positions_dir.glob("*.md")):
        post = frontmatter.load(md_path)
        position_id = post.metadata.get("position_id")
        if not position_id:
            continue

        name = _extract_name(post.content, fallback=md_path.stem)
        index[str(position_id)] = PositionNote(
            position_id=str(position_id),
            name=name,
            markdown=post.content,
            vault_path=f"Positions/{md_path.name}",
        )
    return index


def get_position(
    index: dict[str, PositionNote], position_id: str
) -> PositionNote | None:
    """Return the indexed entry for position_id, or None."""
    return index.get(position_id)


def _extract_name(content: str, *, fallback: str) -> str:
    m = _H1_RE.search(content)
    return m.group(1) if m else fallback
```

- [ ] **Step 2: Run — must pass**

```bash
pytest tests/backend/test_positions_vault.py -v
```

Expected: 8 passed.

Full suite sanity:
```bash
pytest tests/backend -v
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/analysis/positions_vault.py
git commit -m "feat(bjj-app): add Positions/*.md vault index"
```

---

## Task 5: Wire taxonomy + positions_index into `main.create_app`

**Files:**
- Modify: `tools/bjj-app/server/main.py`

No new tests — existing tests verify no regressions.

- [ ] **Step 1: Update `main.py`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/main.py`.

At the top of the file, add imports alongside the existing ones:
```python
from server.analysis.positions_vault import load_positions_index
from server.analysis.taxonomy import load_taxonomy
```

Inside `create_app()`, just after `init_db(settings.db_path)` and before the `FastAPI()` instantiation, add:
```python
    taxonomy_path = settings.project_root / "tools" / "taxonomy.json"
    taxonomy = load_taxonomy(taxonomy_path)
    positions_index = load_positions_index(settings.vault_root)
```

After `app = FastAPI(...)` is created, attach these to app.state:
```python
    app.state.taxonomy = taxonomy
    app.state.positions_index = positions_index
```

(Place the `app.state` assignments after `app = FastAPI(...)` but before `app.add_middleware(...)` or router includes.)

- [ ] **Step 2: Run full suite — no regressions**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend -v
```

Expected: all existing tests still pass. The new startup code loads real data but doesn't change any existing endpoint shape.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/main.py
git commit -m "feat(bjj-app): build taxonomy + positions index at app startup"
```

---

## Task 6: Graph API — failing tests

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_graph.py`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_api_graph.py`:

```python
"""Tests for GET /api/graph and GET /api/vault/position/:id."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _write_positions_vault(root: Path) -> None:
    pos_dir = root / "Positions"
    pos_dir.mkdir(exist_ok=True)
    (pos_dir / "Closed Guard (Bottom).md").write_text(
        "---\n"
        'category: "Guard (Bottom)"\n'
        "position_id: closed_guard_bottom\n"
        "---\n\n"
        "# Closed Guard (Bottom)\n\nBody.\n"
    )


def _write_minimal_taxonomy(root: Path) -> None:
    # The taxonomy is normally at `<project_root>/tools/taxonomy.json`.
    # For tests with BJJ_PROJECT_ROOT pointed at a tmp dir, place a minimal
    # copy at <tmp>/tools/taxonomy.json.
    import json
    tax_dir = root / "tools"
    tax_dir.mkdir(exist_ok=True)
    (tax_dir / "taxonomy.json").write_text(json.dumps({
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing", "category": "standing",
             "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "Closed Guard (Bottom)",
             "category": "guard_bottom", "visual_cues": "b"},
        ],
        "valid_transitions": [["standing_neutral", "closed_guard_bottom"]],
    }))


@pytest.mark.asyncio
async def test_get_graph_returns_taxonomy_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _write_minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"categories", "positions", "transitions"}
    assert len(body["positions"]) == 2
    assert body["transitions"] == [{"from": "standing_neutral", "to": "closed_guard_bottom"}]
    # Every category has a tint
    for cat in body["categories"]:
        assert cat["tint"].startswith("#")


@pytest.mark.asyncio
async def test_get_vault_position_returns_markdown_for_known_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _write_minimal_taxonomy(tmp_project_root)
    _write_positions_vault(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/vault/position/closed_guard_bottom")

    assert response.status_code == 200
    body = response.json()
    assert body["position_id"] == "closed_guard_bottom"
    assert body["name"] == "Closed Guard (Bottom)"
    assert "Body." in body["markdown"]
    assert body["vault_path"] == "Positions/Closed Guard (Bottom).md"


@pytest.mark.asyncio
async def test_get_vault_position_returns_404_for_unknown_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _write_minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/vault/position/no_such_position")

    assert response.status_code == 404
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_graph.py -v
```

Expected: 3 tests fail — routes not yet registered (404 from FastAPI's own not-found for each).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_graph.py
git commit -m "test(bjj-app): add graph + vault position API tests (failing — no impl)"
```

---

## Task 7: Graph API — implementation (GET /api/graph + GET /api/vault/position/:id)

**Files:**
- Create: `tools/bjj-app/server/api/graph.py`
- Modify: `tools/bjj-app/server/main.py`

- [ ] **Step 1: Create `server/api/graph.py`**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/api/graph.py`:

```python
"""Graph API — taxonomy skeleton, per-roll path arrays, vault position markdown."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/graph")
def get_graph(request: Request) -> dict:
    """Return the cached taxonomy (categories + positions + transitions + tints)."""
    return request.app.state.taxonomy


@router.get("/vault/position/{position_id}")
def get_vault_position(position_id: str, request: Request) -> dict:
    """Return markdown for a position's vault note. 404 if no matching file."""
    from server.analysis.positions_vault import get_position

    entry = get_position(request.app.state.positions_index, position_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No vault note for this position",
        )
    return dict(entry)
```

- [ ] **Step 2: Register the router in `main.py`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/main.py`.

Add to the import block:
```python
from server.api import graph as graph_api
```

Add to the `app.include_router(...)` calls near the end of `create_app`:
```python
    app.include_router(graph_api.router)
```

- [ ] **Step 3: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app
source .venv/bin/activate
pytest tests/backend/test_api_graph.py -v
```

Expected: 3 passed.

Full suite:
```bash
pytest tests/backend -v
```

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/graph.py tools/bjj-app/server/main.py
git commit -m "feat(bjj-app): add GET /api/graph and GET /api/vault/position/:id"
```

---

## Task 8: Paths endpoint — failing tests

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_graph_paths.py`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/tests/backend/test_api_graph_paths.py`:

```python
"""Tests for GET /api/graph/paths/:roll_id."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def _write_minimal_taxonomy(root: Path) -> None:
    tax_dir = root / "tools"
    tax_dir.mkdir(exist_ok=True)
    (tax_dir / "taxonomy.json").write_text(json.dumps({
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing", "category": "standing", "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "CG Bottom", "category": "guard_bottom", "visual_cues": "b"},
            {"id": "closed_guard_top", "name": "CG Top", "category": "guard_bottom", "visual_cues": "c"},
            {"id": "half_guard_bottom", "name": "HG Bottom", "category": "guard_bottom", "visual_cues": "d"},
            {"id": "half_guard_top", "name": "HG Top", "category": "guard_bottom", "visual_cues": "e"},
        ],
        "valid_transitions": [],
    }))


def _seed_roll_with_analyses(db_path: Path) -> tuple[str, str, str]:
    """Insert a roll with 2 moments, analyses for both players on both moments.
    Returns (roll_id, moment1_id, moment2_id)."""
    from server.db import (
        connect,
        create_roll,
        init_db,
        insert_analyses,
        insert_moments,
    )

    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn, id="roll-1", title="T", date="2026-04-21",
        video_path="assets/roll-1/source.mp4", duration_s=45.0,
        partner="Anthony", result="unknown", created_at=int(time.time()),
    )
    moments = insert_moments(
        conn, roll_id="roll-1",
        moments=[
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 12, "timestamp_s": 12.0, "pose_delta": 0.9},
        ],
    )
    insert_analyses(
        conn, moment_id=moments[0]["id"],
        players=[
            {"player": "greig", "position_id": "closed_guard_bottom", "confidence": 0.9,
             "description": "d", "coach_tip": "t"},
            {"player": "anthony", "position_id": "closed_guard_top", "confidence": 0.88,
             "description": None, "coach_tip": None},
        ],
        claude_version="test",
    )
    insert_analyses(
        conn, moment_id=moments[1]["id"],
        players=[
            {"player": "greig", "position_id": "half_guard_bottom", "confidence": 0.82,
             "description": "d", "coach_tip": "t"},
            {"player": "anthony", "position_id": "half_guard_top", "confidence": 0.8,
             "description": None, "coach_tip": None},
        ],
        claude_version="test",
    )
    conn.close()
    return "roll-1", moments[0]["id"], moments[1]["id"]


@pytest.mark.asyncio
async def test_get_graph_paths_returns_sorted_sequences(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _write_minimal_taxonomy(tmp_project_root)
    db_path = tmp_project_root / "test.db"
    _seed_roll_with_analyses(db_path)

    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(db_path))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph/paths/roll-1")

    assert response.status_code == 200
    body = response.json()
    assert body["duration_s"] == 45.0
    greig = body["paths"]["greig"]
    anthony = body["paths"]["anthony"]
    assert [p["position_id"] for p in greig] == ["closed_guard_bottom", "half_guard_bottom"]
    assert [p["position_id"] for p in anthony] == ["closed_guard_top", "half_guard_top"]
    # Must be sorted by timestamp_s
    assert greig[0]["timestamp_s"] == 3.0
    assert greig[1]["timestamp_s"] == 12.0


@pytest.mark.asyncio
async def test_get_graph_paths_returns_empty_when_no_analyses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    import time as _time

    _write_minimal_taxonomy(tmp_project_root)
    db_path = tmp_project_root / "test.db"
    from server.db import connect, create_roll, init_db

    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn, id="roll-empty", title="T", date="2026-04-21",
        video_path="assets/roll-empty/source.mp4", duration_s=30.0,
        partner=None, result="unknown", created_at=int(_time.time()),
    )
    conn.close()

    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(db_path))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph/paths/roll-empty")

    assert response.status_code == 200
    body = response.json()
    assert body["paths"]["greig"] == []
    assert body["paths"]["anthony"] == []


@pytest.mark.asyncio
async def test_get_graph_paths_returns_404_for_unknown_roll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_project_root: Path,
) -> None:
    _write_minimal_taxonomy(tmp_project_root)
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_project_root))
    monkeypatch.setenv("BJJ_DB_OVERRIDE", str(tmp_project_root / "test.db"))

    from server.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph/paths/no-such-roll")

    assert response.status_code == 404
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/backend/test_api_graph_paths.py -v
```

Expected: 3 tests fail (route not registered).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/tests/backend/test_api_graph_paths.py
git commit -m "test(bjj-app): add graph paths API tests (failing — no impl)"
```

---

## Task 9: Paths endpoint — implementation

**Files:**
- Modify: `tools/bjj-app/server/api/graph.py`

- [ ] **Step 1: Append the endpoint to `graph.py`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/server/api/graph.py`. Add imports at the top, alongside the existing ones:

```python
from server.config import Settings, load_settings
from server.db import connect, get_analyses, get_moments, get_roll
from fastapi import Depends
```

Append the new endpoint function at the end of the file:

```python


@router.get("/graph/paths/{roll_id}")
def get_graph_paths(
    roll_id: str,
    settings: Settings = Depends(load_settings),
) -> dict:
    """Return per-roll sparse paths for both players."""
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )

        moment_rows = get_moments(conn, roll_id)
        greig: list[dict] = []
        anthony: list[dict] = []
        for m in moment_rows:
            for a in get_analyses(conn, m["id"]):
                entry = {
                    "timestamp_s": m["timestamp_s"],
                    "position_id": a["position_id"],
                    "moment_id": m["id"],
                }
                if a["player"] == "greig":
                    greig.append(entry)
                elif a["player"] == "anthony":
                    anthony.append(entry)

        return {
            "duration_s": row["duration_s"],
            "paths": {"greig": greig, "anthony": anthony},
        }
    finally:
        conn.close()
```

- [ ] **Step 2: Run — must pass**

```bash
pytest tests/backend/test_api_graph_paths.py -v
```

Expected: 3 passed.

Full suite:
```bash
pytest tests/backend -v
```

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/server/api/graph.py
git commit -m "feat(bjj-app): add GET /api/graph/paths/:roll_id"
```

---

## Task 10: Add Cytoscape + marked.js CDN scripts to `app.html`

**Files:**
- Modify: `tools/bjj-app/web/src/app.html`

No new tests — verified by subsequent component tests and manual smoke.

- [ ] **Step 1: Inspect the current `app.html`**

```bash
cat /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/app.html
```

This is SvelteKit's shell HTML. Locate the `<head>` section. Add these three lines inside `<head>` (before `%sveltekit.head%`):

```html
<script src="https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
<script src="https://unpkg.com/cytoscape-cose-bilkent@4.1.0/cytoscape-cose-bilkent.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked@11.1.1/marked.min.js"></script>
```

- [ ] **Step 2: Verify the frontend still builds + tests pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 24 passed (no regressions from M4). The CDN scripts don't affect vitest/jsdom.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/app.html
git commit -m "chore(bjj-app): add Cytoscape + cose-bilkent + marked CDN scripts"
```

---

## Task 11: Frontend types + api.ts

**Files:**
- Modify: `tools/bjj-app/web/src/lib/types.ts`
- Modify: `tools/bjj-app/web/src/lib/api.ts`

- [ ] **Step 1: Update `types.ts`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/types.ts`. APPEND at the end of the file:

```typescript

// ---------- M5: Graph page types ----------

export type GraphCategory = {
  id: string;
  label: string;
  dominance: number;
  tint: string;
};

export type GraphNode = {
  id: string;
  name: string;
  category: string;
};

export type GraphEdge = {
  from: string;
  to: string;
};

export type GraphTaxonomy = {
  categories: GraphCategory[];
  positions: GraphNode[];
  transitions: GraphEdge[];
};

export type PathPoint = {
  timestamp_s: number;
  position_id: string;
  moment_id: string;
};

export type GraphPaths = {
  duration_s: number | null;
  paths: {
    greig: PathPoint[];
    anthony: PathPoint[];
  };
};

export type PositionNote = {
  position_id: string;
  name: string;
  markdown: string;
  vault_path: string;
};

export type GraphFilter =
  | { kind: 'all' }
  | { kind: 'category'; id: string }
  | { kind: 'player'; who: 'greig' | 'anthony' };
```

- [ ] **Step 2: Update `api.ts`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/api.ts`.

Change the first import line to include the new types. Find:
```typescript
import type {
  AnalyseEvent,
  AnalyseMomentEvent,
  Annotation,
  CreateRollInput,
  PublishConflict,
  PublishSuccess,
  RollDetail,
  RollSummary
} from './types';
```

Replace with:
```typescript
import type {
  AnalyseEvent,
  AnalyseMomentEvent,
  Annotation,
  CreateRollInput,
  GraphPaths,
  GraphTaxonomy,
  PositionNote,
  PublishConflict,
  PublishSuccess,
  RollDetail,
  RollSummary
} from './types';
```

APPEND at the end of `api.ts`:

```typescript

export function getGraph(): Promise<GraphTaxonomy> {
  return request<GraphTaxonomy>('/api/graph');
}

export function getGraphPaths(rollId: string): Promise<GraphPaths> {
  return request<GraphPaths>(`/api/graph/paths/${encodeURIComponent(rollId)}`);
}

export async function getPositionNote(positionId: string): Promise<PositionNote | null> {
  const response = await fetch(
    `/api/vault/position/${encodeURIComponent(positionId)}`,
    { headers: { Accept: 'application/json' } }
  );
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as PositionNote;
}
```

- [ ] **Step 3: Run existing frontend tests — no regressions**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 24 passed.

- [ ] **Step 4: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/types.ts tools/bjj-app/web/src/lib/api.ts
git commit -m "feat(bjj-app): add M5 graph types + API client"
```

---

## Task 12: Pure graph-layout utilities — failing tests

**Files:**
- Create: `tools/bjj-app/web/tests/graph-layout.test.ts`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/graph-layout.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';

import {
  buildCytoscapeElements,
  headPositionAt,
  lerp
} from '../src/lib/graph-layout';
import type { GraphPaths, GraphTaxonomy, PathPoint } from '../src/lib/types';

const tinyTaxonomy: GraphTaxonomy = {
  categories: [
    { id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' },
    { id: 'guard_bottom', label: 'Guard (Bottom)', dominance: 1, tint: '#e6f7e6' }
  ],
  positions: [
    { id: 'standing_neutral', name: 'Standing', category: 'standing' },
    { id: 'closed_guard_bottom', name: 'CG Bottom', category: 'guard_bottom' },
    { id: 'half_guard_bottom', name: 'HG Bottom', category: 'guard_bottom' }
  ],
  transitions: [{ from: 'standing_neutral', to: 'closed_guard_bottom' }]
};

const emptyPaths: GraphPaths = {
  duration_s: 60,
  paths: { greig: [], anthony: [] }
};

function path(points: Array<[number, string]>): PathPoint[] {
  return points.map(([t, id], i) => ({
    timestamp_s: t,
    position_id: id,
    moment_id: `m-${i}`
  }));
}

describe('lerp', () => {
  it('returns a at t=0', () => {
    expect(lerp(10, 20, 0)).toBe(10);
  });
  it('returns b at t=1', () => {
    expect(lerp(10, 20, 1)).toBe(20);
  });
  it('interpolates midpoint at t=0.5', () => {
    expect(lerp(10, 20, 0.5)).toBe(15);
  });
});

describe('buildCytoscapeElements', () => {
  it('emits compound parent nodes per category', () => {
    const { nodes } = buildCytoscapeElements(tinyTaxonomy, emptyPaths);
    const compoundNodes = nodes.filter((n) => n.data.isCategory === true);
    expect(compoundNodes.map((n) => n.data.id).sort()).toEqual([
      'cat:guard_bottom',
      'cat:standing'
    ]);
  });

  it('emits a position node for every taxonomy position with the correct parent', () => {
    const { nodes } = buildCytoscapeElements(tinyTaxonomy, emptyPaths);
    const posNodes = nodes.filter((n) => n.data.isCategory !== true);
    expect(posNodes.length).toBe(3);
    const cg = posNodes.find((n) => n.data.id === 'closed_guard_bottom')!;
    expect(cg.data.parent).toBe('cat:guard_bottom');
    expect(cg.data.label).toBe('CG Bottom');
  });

  it('emits taxonomy edges with a "taxonomy" class', () => {
    const { edges } = buildCytoscapeElements(tinyTaxonomy, emptyPaths);
    const taxEdges = edges.filter((e) => e.classes === 'taxonomy');
    expect(taxEdges.length).toBe(1);
    expect(taxEdges[0].data.source).toBe('standing_neutral');
    expect(taxEdges[0].data.target).toBe('closed_guard_bottom');
  });

  it('emits path overlay edges for each consecutive pair of analysed moments', () => {
    const paths: GraphPaths = {
      duration_s: 60,
      paths: {
        greig: path([
          [3, 'standing_neutral'],
          [10, 'closed_guard_bottom'],
          [30, 'half_guard_bottom']
        ]),
        anthony: []
      }
    };
    const { edges } = buildCytoscapeElements(tinyTaxonomy, paths);
    const overlay = edges.filter((e) => e.classes === 'path-greig');
    expect(overlay.length).toBe(2);
    expect(overlay[0].data.source).toBe('standing_neutral');
    expect(overlay[0].data.target).toBe('closed_guard_bottom');
    expect(overlay[1].data.source).toBe('closed_guard_bottom');
    expect(overlay[1].data.target).toBe('half_guard_bottom');
  });

  it('does not emit overlay edges for a path with fewer than 2 points', () => {
    const paths: GraphPaths = {
      duration_s: 60,
      paths: {
        greig: path([[3, 'standing_neutral']]),
        anthony: []
      }
    };
    const { edges } = buildCytoscapeElements(tinyTaxonomy, paths);
    const overlay = edges.filter(
      (e) => e.classes === 'path-greig' || e.classes === 'path-anthony'
    );
    expect(overlay.length).toBe(0);
  });
});

describe('headPositionAt', () => {
  const nodeLookup = new Map([
    ['standing_neutral', { x: 0, y: 0 }],
    ['closed_guard_bottom', { x: 100, y: 0 }],
    ['half_guard_bottom', { x: 100, y: 100 }]
  ]);

  it('returns null when path is empty', () => {
    expect(headPositionAt([], 5, nodeLookup)).toBeNull();
  });

  it('returns null when scrub time is before the first path point', () => {
    const p = path([[10, 'standing_neutral'], [20, 'closed_guard_bottom']]);
    expect(headPositionAt(p, 5, nodeLookup)).toBeNull();
  });

  it('returns the last node position when scrub time is after the last point', () => {
    const p = path([[10, 'standing_neutral'], [20, 'closed_guard_bottom']]);
    const pos = headPositionAt(p, 30, nodeLookup);
    expect(pos).toEqual({ x: 100, y: 0 });
  });

  it('returns the exact node position at a point timestamp', () => {
    const p = path([[10, 'standing_neutral'], [20, 'closed_guard_bottom']]);
    expect(headPositionAt(p, 10, nodeLookup)).toEqual({ x: 0, y: 0 });
  });

  it('interpolates linearly between consecutive points', () => {
    const p = path([[10, 'standing_neutral'], [20, 'closed_guard_bottom']]);
    const pos = headPositionAt(p, 15, nodeLookup);
    // Halfway between (0,0) and (100,0) at t=0.5 → (50, 0).
    expect(pos).toEqual({ x: 50, y: 0 });
  });

  it('interpolates on the correct segment when given multiple points', () => {
    const p = path([
      [0, 'standing_neutral'],
      [10, 'closed_guard_bottom'],
      [20, 'half_guard_bottom']
    ]);
    // At t=15 we should be halfway on the CG->HG edge: (100,0) -> (100,100) → (100,50).
    const pos = headPositionAt(p, 15, nodeLookup);
    expect(pos).toEqual({ x: 100, y: 50 });
  });

  it('returns null when a referenced node is missing from the lookup', () => {
    const p = path([[10, 'unknown_id'], [20, 'closed_guard_bottom']]);
    expect(headPositionAt(p, 15, nodeLookup)).toBeNull();
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: collection error / import failure on `../src/lib/graph-layout`.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/graph-layout.test.ts
git commit -m "test(bjj-app): add graph-layout utility tests (failing — no impl)"
```

---

## Task 13: Pure graph-layout utilities — implementation

**Files:**
- Create: `tools/bjj-app/web/src/lib/graph-layout.ts`

- [ ] **Step 1: Write `graph-layout.ts`**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/graph-layout.ts`:

```typescript
/**
 * Pure helpers for the graph page — no DOM access, no Cytoscape import.
 * Tested in isolation; consumed by GraphCluster.svelte for Cytoscape integration.
 */
import type { GraphPaths, GraphTaxonomy, PathPoint } from './types';

export type Point2D = { x: number; y: number };

export type CyNode = {
  data: {
    id: string;
    parent?: string;
    label?: string;
    tint?: string;
    isCategory?: boolean;
  };
};

export type CyEdge = {
  data: { id: string; source: string; target: string };
  classes?: string;
};

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/**
 * Build Cytoscape-shaped nodes + edges from the taxonomy and (optionally) per-roll paths.
 *
 * Output shape:
 *   - One compound parent node per category, id `cat:<category_id>`, data.isCategory=true, data.tint=<hex>.
 *   - One position node per taxonomy position, parented by `cat:<category>`, data.label=<name>.
 *   - One edge per taxonomy transition, class `taxonomy`.
 *   - For each non-empty player path: one overlay edge per consecutive pair, class `path-greig` or `path-anthony`.
 */
export function buildCytoscapeElements(
  taxonomy: GraphTaxonomy,
  paths: GraphPaths
): { nodes: CyNode[]; edges: CyEdge[] } {
  const nodes: CyNode[] = [];
  const edges: CyEdge[] = [];

  for (const cat of taxonomy.categories) {
    nodes.push({
      data: {
        id: `cat:${cat.id}`,
        label: cat.label,
        tint: cat.tint,
        isCategory: true
      }
    });
  }

  for (const pos of taxonomy.positions) {
    nodes.push({
      data: {
        id: pos.id,
        parent: `cat:${pos.category}`,
        label: pos.name
      }
    });
  }

  for (const tr of taxonomy.transitions) {
    edges.push({
      data: {
        id: `tax:${tr.from}->${tr.to}`,
        source: tr.from,
        target: tr.to
      },
      classes: 'taxonomy'
    });
  }

  for (const [who, points] of [
    ['greig', paths.paths.greig],
    ['anthony', paths.paths.anthony]
  ] as const) {
    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1];
      const curr = points[i];
      edges.push({
        data: {
          id: `path:${who}:${prev.moment_id}->${curr.moment_id}`,
          source: prev.position_id,
          target: curr.position_id
        },
        classes: `path-${who}`
      });
    }
  }

  return { nodes, edges };
}

/**
 * Compute the position of a player's path-head marker at `scrubTimeS`.
 *
 * Returns null when:
 *  - path is empty, OR
 *  - scrubTimeS is before the first analysed point, OR
 *  - a referenced position_id isn't in nodeLookup (missing node).
 *
 * Otherwise linearly interpolates between the two bracketing path points,
 * or rests on the last point if scrubTimeS is past the final timestamp.
 */
export function headPositionAt(
  path: PathPoint[],
  scrubTimeS: number,
  nodeLookup: Map<string, Point2D>
): Point2D | null {
  if (path.length === 0) return null;
  if (scrubTimeS < path[0].timestamp_s) return null;

  // Find the last point where timestamp_s <= scrubTimeS.
  let prevIdx = 0;
  for (let i = 0; i < path.length; i++) {
    if (path[i].timestamp_s <= scrubTimeS) {
      prevIdx = i;
    } else {
      break;
    }
  }

  const prev = path[prevIdx];
  const next = path[prevIdx + 1];

  const prevPos = nodeLookup.get(prev.position_id);
  if (prevPos === undefined) return null;

  if (next === undefined) {
    return { x: prevPos.x, y: prevPos.y };
  }

  const nextPos = nodeLookup.get(next.position_id);
  if (nextPos === undefined) return null;

  const span = next.timestamp_s - prev.timestamp_s;
  const t = span === 0 ? 0 : (scrubTimeS - prev.timestamp_s) / span;
  return {
    x: lerp(prevPos.x, nextPos.x, t),
    y: lerp(prevPos.y, nextPos.y, t)
  };
}
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 17 new tests pass (lerp×3 + buildCytoscapeElements×5 + headPositionAt×7, =15... plus a couple of my counts are approximate; the expectation is that ALL new tests pass and total frontend count grows by ~15 — total around 39 passed).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/graph-layout.ts
git commit -m "feat(bjj-app): add pure graph-layout helpers (Cytoscape elements + head interpolation)"
```

---

## Task 14: FilterChips component — failing tests

**Files:**
- Create: `tools/bjj-app/web/tests/filter-chips.test.ts`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/filter-chips.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import FilterChips from '../src/lib/components/FilterChips.svelte';
import type { GraphCategory } from '../src/lib/types';

const categories: GraphCategory[] = [
  { id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' },
  { id: 'guard_bottom', label: 'Guard (Bottom)', dominance: 1, tint: '#e6f7e6' }
];

describe('FilterChips', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders an "All" chip plus one chip per category plus two player chips', () => {
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'all' },
      onfilterchange: vi.fn()
    });
    expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^standing$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /guard \(bottom\)/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^greig$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^anthony$/i })).toBeInTheDocument();
  });

  it('calls onfilterchange with category filter when a category chip is clicked', async () => {
    const onfilterchange = vi.fn();
    const user = userEvent.setup();
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'all' },
      onfilterchange
    });
    await user.click(screen.getByRole('button', { name: /^standing$/i }));
    expect(onfilterchange).toHaveBeenCalledWith({ kind: 'category', id: 'standing' });
  });

  it('calls onfilterchange with player filter when a player chip is clicked', async () => {
    const onfilterchange = vi.fn();
    const user = userEvent.setup();
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'all' },
      onfilterchange
    });
    await user.click(screen.getByRole('button', { name: /^greig$/i }));
    expect(onfilterchange).toHaveBeenCalledWith({ kind: 'player', who: 'greig' });
  });

  it('calls onfilterchange with {kind:"all"} when "All" is clicked', async () => {
    const onfilterchange = vi.fn();
    const user = userEvent.setup();
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'category', id: 'standing' },
      onfilterchange
    });
    await user.click(screen.getByRole('button', { name: /^all$/i }));
    expect(onfilterchange).toHaveBeenCalledWith({ kind: 'all' });
  });

  it('marks the active chip with aria-pressed=true', () => {
    render(FilterChips, {
      categories,
      activeFilter: { kind: 'category', id: 'standing' },
      onfilterchange: vi.fn()
    });
    const chip = screen.getByRole('button', { name: /^standing$/i });
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    const allChip = screen.getByRole('button', { name: /^all$/i });
    expect(allChip).toHaveAttribute('aria-pressed', 'false');
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 5 new tests fail (component not found).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/filter-chips.test.ts
git commit -m "test(bjj-app): add FilterChips tests (failing — no impl)"
```

---

## Task 15: FilterChips component — implementation

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/FilterChips.svelte`

- [ ] **Step 1: Write the component**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/components/FilterChips.svelte`:

```svelte
<script lang="ts">
  import type { GraphCategory, GraphFilter } from '$lib/types';

  let {
    categories,
    activeFilter,
    onfilterchange
  }: {
    categories: GraphCategory[];
    activeFilter: GraphFilter;
    onfilterchange: (filter: GraphFilter) => void;
  } = $props();

  function isActive(kind: GraphFilter['kind'], key?: string): boolean {
    if (activeFilter.kind !== kind) return false;
    if (kind === 'category') return activeFilter.kind === 'category' && activeFilter.id === key;
    if (kind === 'player') return activeFilter.kind === 'player' && activeFilter.who === key;
    return true;
  }
</script>

<div class="flex flex-wrap items-center gap-1.5">
  <button
    type="button"
    aria-pressed={activeFilter.kind === 'all'}
    onclick={() => onfilterchange({ kind: 'all' })}
    class="rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors
           {activeFilter.kind === 'all'
             ? 'bg-white/10 border-white/30 text-white'
             : 'border-white/15 text-white/55 hover:bg-white/5'}"
  >
    All
  </button>

  {#each categories as cat (cat.id)}
    <button
      type="button"
      aria-pressed={isActive('category', cat.id)}
      onclick={() => onfilterchange({ kind: 'category', id: cat.id })}
      style:--chip-tint={cat.tint}
      class="rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors
             {isActive('category', cat.id)
               ? 'bg-[var(--chip-tint)] text-black border-transparent'
               : 'border-white/15 text-white/55 hover:bg-white/5'}"
    >
      {cat.label}
    </button>
  {/each}

  <span class="mx-1 h-4 w-px bg-white/15"></span>

  <button
    type="button"
    aria-pressed={isActive('player', 'greig')}
    onclick={() => onfilterchange({ kind: 'player', who: 'greig' })}
    class="rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors
           {isActive('player', 'greig')
             ? 'bg-white/20 border-white/40 text-white'
             : 'border-white/15 text-white/55 hover:bg-white/5'}"
  >
    Greig
  </button>
  <button
    type="button"
    aria-pressed={isActive('player', 'anthony')}
    onclick={() => onfilterchange({ kind: 'player', who: 'anthony' })}
    class="rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors
           {isActive('player', 'anthony')
             ? 'bg-rose-500/30 border-rose-400/50 text-rose-100'
             : 'border-white/15 text-white/55 hover:bg-white/5'}"
  >
    Anthony
  </button>
</div>
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 5 new passing, total ~44 (depending on earlier counts).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/components/FilterChips.svelte
git commit -m "feat(bjj-app): add FilterChips component"
```

---

## Task 16: GraphScrubber component — failing tests

**Files:**
- Create: `tools/bjj-app/web/tests/graph-scrubber.test.ts`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/graph-scrubber.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import GraphScrubber from '../src/lib/components/GraphScrubber.svelte';

describe('GraphScrubber', () => {
  it('renders a range slider with max = durationS', () => {
    render(GraphScrubber, {
      scrubTimeS: 0,
      durationS: 225,
      rollId: 'abc',
      onscrubchange: vi.fn()
    });
    const slider = screen.getByRole('slider');
    expect(slider).toHaveAttribute('max', '225');
    expect((slider as HTMLInputElement).value).toBe('0');
  });

  it('calls onscrubchange with new numeric value when slider moves', async () => {
    const onscrubchange = vi.fn();
    render(GraphScrubber, {
      scrubTimeS: 0,
      durationS: 100,
      rollId: 'abc',
      onscrubchange
    });
    const slider = screen.getByRole('slider') as HTMLInputElement;
    // Simulate input value change + input event.
    slider.value = '42';
    slider.dispatchEvent(new Event('input', { bubbles: true }));
    expect(onscrubchange).toHaveBeenCalledWith(42);
  });

  it('renders the "Open in review" link with roll + t query params', () => {
    render(GraphScrubber, {
      scrubTimeS: 42,
      durationS: 100,
      rollId: 'abc',
      onscrubchange: vi.fn()
    });
    const link = screen.getByRole('link', { name: /open in review/i });
    expect(link).toHaveAttribute('href', '/review/abc?t=42');
  });

  it('renders the mm:ss time display for scrubTimeS', () => {
    render(GraphScrubber, {
      scrubTimeS: 125,
      durationS: 300,
      rollId: 'abc',
      onscrubchange: vi.fn()
    });
    expect(screen.getByText(/2:05/)).toBeInTheDocument();
    expect(screen.getByText(/5:00/)).toBeInTheDocument();
  });

  it('disables the slider when rollId is empty or durationS is 0', () => {
    render(GraphScrubber, {
      scrubTimeS: 0,
      durationS: 0,
      rollId: '',
      onscrubchange: vi.fn()
    });
    const slider = screen.getByRole('slider');
    expect(slider).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 5 new tests fail.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/graph-scrubber.test.ts
git commit -m "test(bjj-app): add GraphScrubber tests (failing — no impl)"
```

---

## Task 17: GraphScrubber component — implementation

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/GraphScrubber.svelte`

- [ ] **Step 1: Write the component**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/components/GraphScrubber.svelte`:

```svelte
<script lang="ts">
  let {
    scrubTimeS,
    durationS,
    rollId,
    onscrubchange
  }: {
    scrubTimeS: number;
    durationS: number;
    rollId: string;
    onscrubchange: (t: number) => void;
  } = $props();

  const disabled = $derived(!rollId || durationS <= 0);

  function formatMmSs(seconds: number): string {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function onInput(e: Event) {
    const target = e.target as HTMLInputElement;
    const n = Number(target.value);
    if (!Number.isNaN(n)) {
      onscrubchange(n);
    }
  }

  const reviewHref = $derived(
    rollId ? `/review/${encodeURIComponent(rollId)}?t=${Math.floor(scrubTimeS)}` : '#'
  );
</script>

<div class="flex items-center gap-3 rounded-md border border-white/10 bg-white/[0.02] px-4 py-2">
  <span class="w-12 text-right font-mono text-xs tabular-nums text-white/70">
    {formatMmSs(scrubTimeS)}
  </span>

  <input
    type="range"
    min="0"
    max={durationS}
    step="0.1"
    value={scrubTimeS}
    oninput={onInput}
    disabled={disabled}
    class="flex-1 h-1.5 rounded-full bg-white/10 accent-amber-400 disabled:opacity-40"
  />

  <span class="w-12 font-mono text-xs tabular-nums text-white/50">
    {formatMmSs(durationS)}
  </span>

  <a
    href={reviewHref}
    aria-disabled={disabled}
    class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1 text-[11px] font-medium text-white/80 hover:bg-white/[0.08] {disabled ? 'pointer-events-none opacity-40' : ''}"
  >
    Open in review →
  </a>
</div>
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: GraphScrubber 5 tests pass; no regressions.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/components/GraphScrubber.svelte
git commit -m "feat(bjj-app): add GraphScrubber component"
```

---

## Task 18: PositionDrawer component — failing tests

**Files:**
- Create: `tools/bjj-app/web/tests/position-drawer.test.ts`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/position-drawer.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import PositionDrawer from '../src/lib/components/PositionDrawer.svelte';
import type { PositionNote } from '../src/lib/types';

const sampleNote: PositionNote = {
  position_id: 'closed_guard_bottom',
  name: 'Closed Guard (Bottom)',
  markdown: '# Closed Guard (Bottom)\n\nBody text.\n',
  vault_path: 'Positions/Closed Guard (Bottom).md'
};

// marked.js is loaded via CDN in production (app.html). In tests, stub it
// globally so the drawer can call it.
function stubMarked(result = '<h1>Closed Guard (Bottom)</h1><p>Body text.</p>') {
  // @ts-expect-error global stub
  globalThis.marked = { parse: vi.fn(() => result) };
}

describe('PositionDrawer', () => {
  afterEach(() => {
    // @ts-expect-error cleanup
    delete globalThis.marked;
    vi.restoreAllMocks();
  });

  it('renders nothing when open is false', () => {
    stubMarked();
    render(PositionDrawer, { open: false, positionNote: sampleNote, onclose: vi.fn() });
    expect(screen.queryByText(/closed guard/i)).toBeNull();
  });

  it('renders markdown when open with a note', () => {
    stubMarked();
    render(PositionDrawer, { open: true, positionNote: sampleNote, onclose: vi.fn() });
    expect(screen.getByText(/closed guard \(bottom\)/i)).toBeInTheDocument();
    expect(screen.getByText(/body text/i)).toBeInTheDocument();
  });

  it('renders fallback text when open with a null note', () => {
    stubMarked();
    render(PositionDrawer, { open: true, positionNote: null, onclose: vi.fn() });
    expect(screen.getByText(/no vault note for this position/i)).toBeInTheDocument();
  });

  it('calls onclose when the close button is clicked', async () => {
    stubMarked();
    const onclose = vi.fn();
    const user = userEvent.setup();
    render(PositionDrawer, { open: true, positionNote: sampleNote, onclose });
    await user.click(screen.getByRole('button', { name: /close/i }));
    expect(onclose).toHaveBeenCalledTimes(1);
  });

  it('calls onclose on Escape key', async () => {
    stubMarked();
    const onclose = vi.fn();
    const user = userEvent.setup();
    render(PositionDrawer, { open: true, positionNote: sampleNote, onclose });
    await user.keyboard('{Escape}');
    expect(onclose).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 5 new tests fail (component not found).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/position-drawer.test.ts
git commit -m "test(bjj-app): add PositionDrawer tests (failing — no impl)"
```

---

## Task 19: PositionDrawer component — implementation

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/PositionDrawer.svelte`

- [ ] **Step 1: Write the component**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/components/PositionDrawer.svelte`:

```svelte
<script lang="ts">
  import type { PositionNote } from '$lib/types';

  let {
    open,
    positionNote,
    onclose
  }: {
    open: boolean;
    positionNote: PositionNote | null;
    onclose: () => void;
  } = $props();

  // marked is loaded as a global from a CDN <script> in app.html.
  // In tests we stub it on globalThis; in dev/prod it's real.
  function renderMarkdown(md: string): string {
    // @ts-expect-error marked is a global
    const marked = globalThis.marked;
    if (marked && typeof marked.parse === 'function') {
      return marked.parse(md);
    }
    // Fallback: escape + wrap in <pre> so nothing breaks if marked didn't load.
    const escaped = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `<pre>${escaped}</pre>`;
  }

  const rendered = $derived(positionNote ? renderMarkdown(positionNote.markdown) : '');

  function onKeydown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      onclose();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
  <aside
    role="dialog"
    aria-modal="true"
    aria-label="Position details"
    class="fixed right-0 top-0 z-40 h-full w-full max-w-[400px] overflow-y-auto border-l border-white/10 bg-black/90 backdrop-blur-md shadow-lg"
  >
    <header class="flex items-center justify-between gap-2 border-b border-white/10 p-4">
      <h2 class="text-sm font-semibold text-white/95">
        {positionNote ? positionNote.name : 'Position'}
      </h2>
      <button
        type="button"
        onclick={onclose}
        aria-label="Close"
        class="rounded-md border border-white/15 bg-white/[0.04] px-2 py-1 text-xs text-white/75 hover:bg-white/[0.08]"
      >
        Close
      </button>
    </header>

    <div class="prose prose-invert max-w-none p-4 text-sm text-white/80">
      {#if positionNote}
        {@html rendered}
      {:else}
        <p class="text-white/55">No vault note for this position yet.</p>
      {/if}
    </div>
  </aside>
{/if}
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 5 new passing.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/components/PositionDrawer.svelte
git commit -m "feat(bjj-app): add PositionDrawer component"
```

---

## Task 20: GraphCluster component — failing tests

**Files:**
- Create: `tools/bjj-app/web/tests/graph-cluster.test.ts`

GraphCluster is the Cytoscape-hosting component. We test its wiring (correct props passed, correct Cytoscape element calls made, node-click fires callback) rather than actual rendering. Cytoscape is stubbed on globalThis.

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/graph-cluster.test.ts`:

```typescript
import { render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import GraphCluster from '../src/lib/components/GraphCluster.svelte';
import type { GraphPaths, GraphTaxonomy } from '../src/lib/types';

const taxonomy: GraphTaxonomy = {
  categories: [
    { id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' },
    { id: 'guard_bottom', label: 'Guard (Bottom)', dominance: 1, tint: '#e6f7e6' }
  ],
  positions: [
    { id: 'standing_neutral', name: 'Standing', category: 'standing' },
    { id: 'closed_guard_bottom', name: 'CG Bottom', category: 'guard_bottom' }
  ],
  transitions: [{ from: 'standing_neutral', to: 'closed_guard_bottom' }]
};

const paths: GraphPaths = {
  duration_s: 60,
  paths: {
    greig: [
      { timestamp_s: 0, position_id: 'standing_neutral', moment_id: 'm1' },
      { timestamp_s: 30, position_id: 'closed_guard_bottom', moment_id: 'm2' }
    ],
    anthony: []
  }
};

// Minimal Cytoscape + cose-bilkent stub for tests.
function stubCytoscape() {
  const handlers: Record<string, Array<(evt: { target: { id: () => string } }) => void>> = {};
  const mockEle = {
    id: vi.fn(() => 'standing_neutral'),
    position: vi.fn(),
    addClass: vi.fn(),
    removeClass: vi.fn(),
    style: vi.fn()
  };
  const added: Array<{ data: Record<string, unknown>; classes?: string }> = [];
  const cyInstance = {
    on: vi.fn((event: string, _selector: string, handler: (evt: { target: { id: () => string } }) => void) => {
      handlers[event] = handlers[event] || [];
      handlers[event].push(handler);
    }),
    add: vi.fn((eles: Array<{ data: Record<string, unknown>; classes?: string }>) => {
      added.push(...eles);
    }),
    remove: vi.fn(),
    getElementById: vi.fn(() => mockEle),
    nodes: vi.fn(() => ({ forEach: vi.fn() })),
    edges: vi.fn(() => ({ forEach: vi.fn(), length: added.length })),
    elements: vi.fn(() => ({ removeClass: vi.fn(), addClass: vi.fn() })),
    layout: vi.fn(() => ({ run: vi.fn() })),
    fit: vi.fn(),
    resize: vi.fn(),
    destroy: vi.fn(),
    // Expose captured state for tests.
    __captured: { added, handlers }
  };
  const cytoscape = vi.fn(() => cyInstance);
  // cose-bilkent registers itself via cytoscape.use()
  // @ts-expect-error extension method
  cytoscape.use = vi.fn();
  // @ts-expect-error global stub
  globalThis.cytoscape = cytoscape;
  // @ts-expect-error global stub
  globalThis.cytoscapeCoseBilkent = () => {};
  return cyInstance;
}

describe('GraphCluster', () => {
  let cy: ReturnType<typeof stubCytoscape>;

  beforeEach(() => {
    cy = stubCytoscape();
  });

  afterEach(() => {
    // @ts-expect-error cleanup
    delete globalThis.cytoscape;
    // @ts-expect-error cleanup
    delete globalThis.cytoscapeCoseBilkent;
    vi.restoreAllMocks();
  });

  it('renders a container with data-variant="full" by default', async () => {
    const { container } = render(GraphCluster, {
      variant: 'full',
      taxonomy,
      paths
    });
    const host = container.querySelector('[data-graphcluster]');
    expect(host).not.toBeNull();
    expect(host!.getAttribute('data-variant')).toBe('full');
  });

  it('renders a container with data-variant="mini" when variant is mini', () => {
    const { container } = render(GraphCluster, {
      variant: 'mini',
      taxonomy,
      paths
    });
    const host = container.querySelector('[data-graphcluster]');
    expect(host!.getAttribute('data-variant')).toBe('mini');
  });

  it('instantiates Cytoscape with elements derived from the taxonomy', async () => {
    render(GraphCluster, { variant: 'full', taxonomy, paths });
    await waitFor(() => {
      expect(cy.__captured.added.length).toBeGreaterThan(0);
    });
    // Category compound parents emitted
    const categoryNodes = cy.__captured.added.filter(
      (e) => e.data.isCategory === true
    );
    expect(categoryNodes.length).toBe(2);
  });

  it('invokes onnodeclick when a node tap event fires', async () => {
    const onnodeclick = vi.fn();
    render(GraphCluster, { variant: 'full', taxonomy, paths, onnodeclick });
    await waitFor(() => {
      expect(cy.on).toHaveBeenCalledWith('tap', 'node', expect.any(Function));
    });
    const tapHandler = cy.__captured.handlers['tap']?.[0];
    expect(tapHandler).toBeDefined();
    tapHandler!({ target: { id: () => 'standing_neutral' } });
    expect(onnodeclick).toHaveBeenCalledWith('standing_neutral');
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 4 new tests fail (component not found).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/graph-cluster.test.ts
git commit -m "test(bjj-app): add GraphCluster tests (failing — no impl)"
```

---

## Task 21: GraphCluster component — implementation

**Files:**
- Create: `tools/bjj-app/web/src/lib/components/GraphCluster.svelte`

- [ ] **Step 1: Write the component**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/lib/components/GraphCluster.svelte`:

```svelte
<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { GraphFilter, GraphPaths, GraphTaxonomy } from '$lib/types';
  import {
    buildCytoscapeElements,
    headPositionAt,
    type Point2D
  } from '$lib/graph-layout';

  let {
    variant,
    taxonomy,
    paths,
    scrubTimeS = 0,
    filter = { kind: 'all' } as GraphFilter,
    onnodeclick
  }: {
    variant: 'full' | 'mini';
    taxonomy: GraphTaxonomy;
    paths?: GraphPaths;
    scrubTimeS?: number;
    filter?: GraphFilter;
    onnodeclick?: (positionId: string) => void;
  } = $props();

  let host: HTMLDivElement | undefined = $state();
  let cy: any = null;          // Cytoscape instance
  let coseRegistered = false;  // one-time registration

  const effectivePaths: GraphPaths = $derived(
    paths ?? { duration_s: null, paths: { greig: [], anthony: [] } }
  );

  // ---------- Cytoscape lifecycle ----------

  function registerCoseOnce() {
    if (coseRegistered) return;
    // @ts-expect-error globals from CDN
    if (typeof globalThis.cytoscape === 'function' && typeof globalThis.cytoscapeCoseBilkent === 'function') {
      // @ts-expect-error cytoscape.use global
      globalThis.cytoscape.use(globalThis.cytoscapeCoseBilkent);
      coseRegistered = true;
    }
  }

  function baseStyle(): any[] {
    return [
      {
        selector: 'node[isCategory]',
        style: {
          'background-color': 'data(tint)',
          'background-opacity': 0.25,
          'border-width': 0,
          label: 'data(label)',
          'text-valign': 'top',
          'text-halign': 'center',
          'font-size': 10,
          color: '#ccc',
          'padding-top': '20px',
          'padding-bottom': '20px',
          'padding-left': '20px',
          'padding-right': '20px',
          shape: 'round-rectangle'
        }
      },
      {
        selector: 'node[!isCategory]',
        style: {
          'background-color': '#333',
          'border-color': 'rgba(255,255,255,0.3)',
          'border-width': 1,
          label: 'data(label)',
          'font-size': 9,
          color: 'rgba(255,255,255,0.75)',
          'text-wrap': 'wrap',
          'text-max-width': '70px',
          'text-valign': 'center',
          'text-halign': 'center',
          width: 28,
          height: 28
        }
      },
      {
        selector: 'edge.taxonomy',
        style: {
          width: 1,
          'line-color': 'rgba(255,255,255,0.08)',
          'curve-style': 'bezier',
          'target-arrow-shape': 'none'
        }
      },
      {
        selector: 'edge.path-greig',
        style: {
          width: 3,
          'line-color': 'rgba(255,255,255,0.85)',
          'curve-style': 'bezier',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': 'rgba(255,255,255,0.85)'
        }
      },
      {
        selector: 'edge.path-anthony',
        style: {
          width: 3,
          'line-color': 'rgba(244,63,94,0.85)',
          'curve-style': 'bezier',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': 'rgba(244,63,94,0.85)'
        }
      },
      {
        selector: '.dim',
        style: { opacity: 0.2 }
      },
      {
        selector: '#head-greig',
        style: {
          'background-color': '#ffffff',
          width: 14,
          height: 14,
          'border-width': 2,
          'border-color': '#ffffff',
          'z-index': 999
        }
      },
      {
        selector: '#head-anthony',
        style: {
          'background-color': '#f43f5e',
          width: 14,
          height: 14,
          'border-width': 2,
          'border-color': '#f43f5e',
          'z-index': 999
        }
      }
    ];
  }

  function mount() {
    if (!host) return;
    // @ts-expect-error cytoscape global
    const cytoscape = globalThis.cytoscape;
    if (typeof cytoscape !== 'function') {
      return; // CDN not loaded; graceful no-op
    }

    registerCoseOnce();

    const { nodes, edges } = buildCytoscapeElements(taxonomy, effectivePaths);

    cy = cytoscape({
      container: host,
      elements: [...nodes, ...edges],
      style: baseStyle(),
      layout: {
        name: 'cose-bilkent',
        animate: false,
        randomize: false,
        fit: true,
        padding: 20,
        nodeRepulsion: 4500,
        idealEdgeLength: 80,
        edgeElasticity: 0.1,
        gravityRangeCompound: 1.5,
        gravityCompound: 1.0,
        tile: true
      } as any,
      userZoomingEnabled: variant === 'full',
      userPanningEnabled: variant === 'full',
      boxSelectionEnabled: false,
      autoungrabify: variant === 'mini'
    });

    if (onnodeclick) {
      cy.on('tap', 'node', (evt: { target: { id: () => string } }) => {
        const id = evt.target.id();
        // Ignore taps on compound parent nodes.
        if (!id.startsWith('cat:')) {
          onnodeclick(id);
        }
      });
    }

    // Add player head markers (invisible initially; updated via effect).
    cy.add([
      { data: { id: 'head-greig' }, position: { x: 0, y: 0 }, classes: 'head' },
      { data: { id: 'head-anthony' }, position: { x: 0, y: 0 }, classes: 'head' }
    ]);
  }

  function rebuildElements() {
    if (!cy) return;
    // Remove only path overlay edges + head markers; keep taxonomy intact.
    cy.elements('edge.path-greig, edge.path-anthony').remove();
    const { edges: newEdges } = buildCytoscapeElements(taxonomy, effectivePaths);
    const overlayEdges = newEdges.filter(
      (e) => e.classes === 'path-greig' || e.classes === 'path-anthony'
    );
    cy.add(overlayEdges);
  }

  function updateHeadMarkers() {
    if (!cy) return;
    const nodeLookup = new Map<string, Point2D>();
    cy.nodes('[!isCategory]').forEach((n: any) => {
      const p = n.position();
      nodeLookup.set(n.id(), { x: p.x, y: p.y });
    });

    for (const [who, path] of [
      ['greig', effectivePaths.paths.greig],
      ['anthony', effectivePaths.paths.anthony]
    ] as const) {
      const head = cy.getElementById(`head-${who}`);
      if (!head || head.length === 0) continue;
      const pos = headPositionAt(path, scrubTimeS, nodeLookup);
      if (pos === null) {
        head.style('display', 'none');
      } else {
        head.style('display', 'element');
        head.position(pos);
      }
    }
  }

  function applyFilter() {
    if (!cy) return;
    cy.elements().removeClass('dim');
    if (filter.kind === 'all') return;
    if (filter.kind === 'category') {
      // Dim everything NOT in the selected category.
      cy.nodes('[!isCategory]').forEach((n: any) => {
        // Cytoscape returns parent id via n.data('parent').
        const parent = n.data('parent');
        if (parent !== `cat:${filter.id}`) n.addClass('dim');
      });
      cy.edges('.taxonomy').addClass('dim');
      cy.edges('.path-greig, .path-anthony').addClass('dim');
    } else if (filter.kind === 'player') {
      const other = filter.who === 'greig' ? 'anthony' : 'greig';
      cy.edges(`.path-${other}`).addClass('dim');
      const otherHead = cy.getElementById(`head-${other}`);
      if (otherHead && otherHead.length > 0) otherHead.addClass('dim');
    }
  }

  // Mount once when host is ready.
  $effect(() => {
    if (host && !cy) {
      mount();
      updateHeadMarkers();
    }
  });

  // Rebuild path overlays + markers when paths change.
  $effect(() => {
    // Read so the effect re-runs on changes.
    void effectivePaths;
    if (cy) {
      rebuildElements();
      updateHeadMarkers();
    }
  });

  // Update head markers as scrubTimeS changes.
  $effect(() => {
    void scrubTimeS;
    if (cy) updateHeadMarkers();
  });

  // Apply filter changes.
  $effect(() => {
    void filter;
    if (cy) applyFilter();
  });

  onDestroy(() => {
    if (cy) {
      cy.destroy();
      cy = null;
    }
  });
</script>

<div
  data-graphcluster
  data-variant={variant}
  class="h-full w-full {variant === 'mini' ? 'min-h-[200px]' : 'min-h-[500px]'}"
  bind:this={host}
></div>
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: GraphCluster 4 tests pass. No regressions.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/lib/components/GraphCluster.svelte
git commit -m "feat(bjj-app): add GraphCluster component (Cytoscape host with path overlays + head markers)"
```

---

## Task 22: `/graph` page — failing tests

**Files:**
- Create: `tools/bjj-app/web/tests/graph-page.test.ts`

- [ ] **Step 1: Write the tests**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/graph-page.test.ts`:

```typescript
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// $app/stores has to be mocked for page store access (matches home.test.ts pattern).
vi.mock('$app/stores', () => ({
  page: {
    subscribe: (run: (v: { url: URL }) => void) => {
      run({ url: new URL('http://localhost/graph') });
      return () => {};
    }
  }
}));

function stubCytoscape() {
  const cyInstance: any = {
    on: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
    getElementById: vi.fn(() => ({ length: 0, style: vi.fn(), position: vi.fn(), addClass: vi.fn() })),
    nodes: vi.fn(() => ({ forEach: vi.fn() })),
    edges: vi.fn(() => ({ forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn(), length: 0, remove: vi.fn() })),
    elements: vi.fn(() => ({ removeClass: vi.fn(), addClass: vi.fn(), remove: vi.fn() })),
    layout: vi.fn(() => ({ run: vi.fn() })),
    fit: vi.fn(),
    resize: vi.fn(),
    destroy: vi.fn()
  };
  // @ts-expect-error global
  globalThis.cytoscape = vi.fn(() => cyInstance);
  // @ts-expect-error global
  globalThis.cytoscape.use = vi.fn();
  // @ts-expect-error global
  globalThis.cytoscapeCoseBilkent = () => {};
  // @ts-expect-error global
  globalThis.marked = { parse: (s: string) => s };
}

describe('/graph page', () => {
  beforeEach(() => {
    stubCytoscape();
  });
  afterEach(() => {
    // @ts-expect-error cleanup
    delete globalThis.cytoscape;
    // @ts-expect-error cleanup
    delete globalThis.cytoscapeCoseBilkent;
    // @ts-expect-error cleanup
    delete globalThis.marked;
    vi.restoreAllMocks();
  });

  it('fetches taxonomy on mount and renders the GraphCluster', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [] // GET /api/rolls → empty list
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        categories: [{ id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' }],
        positions: [{ id: 'standing_neutral', name: 'Standing', category: 'standing' }],
        transitions: []
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const { default: Page } = await import('../src/routes/graph/+page.svelte');
    const { container } = render(Page);

    await waitFor(() => {
      expect(container.querySelector('[data-graphcluster]')).not.toBeNull();
    });
  });

  it('fetches paths when a roll is selected and passes them to GraphCluster', async () => {
    const fetchMock = vi.fn();
    // 1. GET /api/rolls
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [
        {
          id: '2026-04-21 - sample',
          title: 'Sample roll',
          date: '2026-04-21',
          partner: null,
          duration: null,
          result: null,
          roll_id: 'uuid-123'
        }
      ]
    });
    // 2. GET /api/graph
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        categories: [{ id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' }],
        positions: [{ id: 'standing_neutral', name: 'Standing', category: 'standing' }],
        transitions: []
      })
    });
    // 3. GET /api/graph/paths/uuid-123
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        duration_s: 60,
        paths: { greig: [], anthony: [] }
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const user = userEvent.setup();
    const { default: Page } = await import('../src/routes/graph/+page.svelte');
    render(Page);

    // Wait for the dropdown to appear and select the roll.
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByRole('combobox'), 'uuid-123');

    await waitFor(() => {
      const pathsCall = fetchMock.mock.calls.find((c) => c[0].includes('/graph/paths/'));
      expect(pathsCall).toBeDefined();
    });
  });

  it('renders filter chips once the taxonomy has loaded', async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => []
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        categories: [
          { id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' },
          { id: 'guard_bottom', label: 'Guard (Bottom)', dominance: 1, tint: '#e6f7e6' }
        ],
        positions: [],
        transitions: []
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    const { default: Page } = await import('../src/routes/graph/+page.svelte');
    render(Page);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^standing$/i })).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: 3 new tests fail (page doesn't exist).

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/tests/graph-page.test.ts
git commit -m "test(bjj-app): add /graph page tests (failing — no impl)"
```

---

## Task 23: `/graph` page — implementation

**Files:**
- Create: `tools/bjj-app/web/src/routes/graph/+page.svelte`

- [ ] **Step 1: Write the page**

Create `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/routes/graph/+page.svelte`:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import {
    ApiError,
    getGraph,
    getGraphPaths,
    getPositionNote,
    listRolls
  } from '$lib/api';
  import FilterChips from '$lib/components/FilterChips.svelte';
  import GraphCluster from '$lib/components/GraphCluster.svelte';
  import GraphScrubber from '$lib/components/GraphScrubber.svelte';
  import PositionDrawer from '$lib/components/PositionDrawer.svelte';
  import type {
    GraphFilter,
    GraphPaths,
    GraphTaxonomy,
    PositionNote,
    RollSummary
  } from '$lib/types';

  let rolls = $state<RollSummary[]>([]);
  let taxonomy = $state<GraphTaxonomy | null>(null);
  let paths = $state<GraphPaths | null>(null);
  let selectedRollId = $state<string>('');
  let scrubTimeS = $state(0);
  let filter = $state<GraphFilter>({ kind: 'all' });
  let drawerOpen = $state(false);
  let drawerNote = $state<PositionNote | null>(null);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      const [rollsRes, taxonomyRes] = await Promise.all([listRolls(), getGraph()]);
      rolls = rollsRes.filter((r) => r.roll_id !== null);
      taxonomy = taxonomyRes;
      // Apply ?roll= and ?t= query params if present.
      const url = $page.url;
      const queryRoll = url.searchParams.get('roll');
      const queryT = url.searchParams.get('t');
      if (queryRoll && rolls.find((r) => r.roll_id === queryRoll)) {
        selectedRollId = queryRoll;
        await loadPaths(queryRoll);
      }
      if (queryT !== null) {
        const t = Number(queryT);
        if (!Number.isNaN(t)) scrubTimeS = t;
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    }
  });

  async function onRollChange(e: Event) {
    const target = e.target as HTMLSelectElement;
    selectedRollId = target.value;
    if (selectedRollId) {
      await loadPaths(selectedRollId);
    } else {
      paths = null;
      scrubTimeS = 0;
    }
  }

  async function loadPaths(rollId: string) {
    try {
      paths = await getGraphPaths(rollId);
      if (scrubTimeS === 0 && paths.duration_s) {
        // leave at 0 unless query param already set it above
      }
    } catch (err) {
      error = err instanceof ApiError ? err.message : String(err);
    }
  }

  async function onNodeClick(positionId: string) {
    try {
      drawerNote = await getPositionNote(positionId);
    } catch (err) {
      drawerNote = null;
    }
    drawerOpen = true;
  }

  function onCloseDrawer() {
    drawerOpen = false;
  }

  function onFilterChange(next: GraphFilter) {
    filter = next;
  }

  function onScrubChange(t: number) {
    scrubTimeS = t;
  }

  const durationS = $derived(paths?.duration_s ?? 0);
</script>

<section class="flex h-[calc(100vh-4rem)] flex-col gap-3">
  <header class="flex flex-wrap items-center justify-between gap-3 px-4 py-2">
    <div class="flex items-center gap-3">
      <h1 class="text-lg font-semibold tracking-tight">BJJ Graph</h1>
      <select
        aria-label="Select roll"
        value={selectedRollId}
        onchange={onRollChange}
        class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1 text-xs text-white/85"
      >
        <option value="">— select a roll —</option>
        {#each rolls as roll (roll.roll_id)}
          <option value={roll.roll_id}>{roll.title}</option>
        {/each}
      </select>
    </div>
    {#if taxonomy}
      <FilterChips
        categories={taxonomy.categories}
        activeFilter={filter}
        onfilterchange={onFilterChange}
      />
    {/if}
  </header>

  {#if error}
    <div class="mx-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      {error}
    </div>
  {/if}

  <div class="relative flex-1 overflow-hidden border-y border-white/8">
    {#if taxonomy}
      <GraphCluster
        variant="full"
        taxonomy={taxonomy}
        paths={paths ?? { duration_s: null, paths: { greig: [], anthony: [] } }}
        scrubTimeS={scrubTimeS}
        filter={filter}
        onnodeclick={onNodeClick}
      />
    {:else}
      <p class="p-6 text-sm text-white/50">Loading graph…</p>
    {/if}
  </div>

  <div class="px-4 pb-2">
    <GraphScrubber
      scrubTimeS={scrubTimeS}
      durationS={durationS}
      rollId={selectedRollId}
      onscrubchange={onScrubChange}
    />
  </div>

  <PositionDrawer open={drawerOpen} positionNote={drawerNote} onclose={onCloseDrawer} />
</section>
```

- [ ] **Step 2: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: graph-page 3 tests pass; no regressions.

- [ ] **Step 3: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/graph/+page.svelte
git commit -m "feat(bjj-app): add /graph page (dropdown + filter chips + graph + scrubber + drawer)"
```

---

## Task 24: Review page — mount mini graph under MomentDetail

**Files:**
- Modify: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`
- Modify: `tools/bjj-app/web/tests/review-analyse.test.ts`

- [ ] **Step 1: Add a failing test for the mini graph mount**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/tests/review-analyse.test.ts` and append one new test inside the existing `describe('Review page — analyse flow', ...)` block, before its closing `});`:

```typescript

  it('mounts a mini graph below MomentDetail when a moment is selected', async () => {
    const fetchMock = vi.fn();
    // 1. GET roll detail (with moments + one analysed)
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        ...detailWithoutMoments(),
        moments: [
          {
            id: 'm1',
            frame_idx: 2,
            timestamp_s: 2.0,
            pose_delta: 0.5,
            analyses: [
              {
                id: 'a1',
                player: 'greig',
                position_id: 'standing_neutral',
                confidence: 0.9,
                description: 'd',
                coach_tip: 't'
              },
              {
                id: 'a2',
                player: 'anthony',
                position_id: 'standing_neutral',
                confidence: 0.9,
                description: null,
                coach_tip: null
              }
            ],
            annotations: []
          }
        ]
      })
    });
    // 2. GET /api/graph (taxonomy for mini graph)
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        categories: [{ id: 'standing', label: 'Standing', dominance: 0, tint: '#e6f2ff' }],
        positions: [{ id: 'standing_neutral', name: 'Standing', category: 'standing' }],
        transitions: []
      })
    });
    // 3. GET /api/graph/paths/<id>
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        duration_s: 10,
        paths: {
          greig: [{ timestamp_s: 2, position_id: 'standing_neutral', moment_id: 'm1' }],
          anthony: [{ timestamp_s: 2, position_id: 'standing_neutral', moment_id: 'm1' }]
        }
      })
    });
    vi.stubGlobal('fetch', fetchMock);

    // cytoscape stub so GraphCluster doesn't blow up when it mounts.
    // @ts-expect-error global
    globalThis.cytoscape = vi.fn(() => ({
      on: vi.fn(), add: vi.fn(), remove: vi.fn(),
      getElementById: vi.fn(() => ({ length: 0, style: vi.fn(), position: vi.fn(), addClass: vi.fn() })),
      nodes: vi.fn(() => ({ forEach: vi.fn() })),
      edges: vi.fn(() => ({ forEach: vi.fn(), addClass: vi.fn(), removeClass: vi.fn(), length: 0, remove: vi.fn() })),
      elements: vi.fn(() => ({ removeClass: vi.fn(), addClass: vi.fn(), remove: vi.fn() })),
      layout: vi.fn(() => ({ run: vi.fn() })),
      destroy: vi.fn()
    }));
    // @ts-expect-error global
    globalThis.cytoscape.use = vi.fn();
    // @ts-expect-error global
    globalThis.cytoscapeCoseBilkent = () => {};

    try {
      const user = userEvent.setup();
      const { default: Page } = await import('../src/routes/review/[id]/+page.svelte');
      const { container } = render(Page);

      await waitFor(() => {
        expect(screen.getByText('Review analyse test')).toBeInTheDocument();
      });

      // Click the only chip.
      await user.click(screen.getByRole('button', { name: /0:02/i }));

      await waitFor(() => {
        // Mini graph data-testid should appear.
        const miniHost = container.querySelector('[data-graphcluster][data-variant="mini"]');
        expect(miniHost).not.toBeNull();
      });
    } finally {
      // @ts-expect-error cleanup
      delete globalThis.cytoscape;
      // @ts-expect-error cleanup
      delete globalThis.cytoscapeCoseBilkent;
    }
  });
```

- [ ] **Step 2: Run — must fail**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: the new review-analyse test fails; existing tests still pass.

- [ ] **Step 3: Update `review/[id]/+page.svelte`**

Open `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web/src/routes/review/[id]/+page.svelte`.

Change the import block near the top. Find:
```svelte
  import {
    analyseRoll,
    ApiError,
    getRoll,
    publishRoll,
    PublishConflictError
  } from '$lib/api';
  import MomentDetail from '$lib/components/MomentDetail.svelte';
  import PublishConflictDialog from '$lib/components/PublishConflictDialog.svelte';
  import type { AnalyseEvent, Moment, RollDetail } from '$lib/types';
```
Replace with:
```svelte
  import {
    analyseRoll,
    ApiError,
    getGraph,
    getGraphPaths,
    getRoll,
    publishRoll,
    PublishConflictError
  } from '$lib/api';
  import GraphCluster from '$lib/components/GraphCluster.svelte';
  import MomentDetail from '$lib/components/MomentDetail.svelte';
  import PublishConflictDialog from '$lib/components/PublishConflictDialog.svelte';
  import type { AnalyseEvent, GraphPaths, GraphTaxonomy, Moment, RollDetail } from '$lib/types';
```

Add these state + logic additions to the `<script>` block (place them after the existing state declarations and before `onMount`):
```svelte
  let graphTaxonomy = $state<GraphTaxonomy | null>(null);
  let graphPaths = $state<GraphPaths | null>(null);
```

In the existing `onMount`, after `roll = await getRoll(id);` succeeds, add:
```svelte
      try {
        graphTaxonomy = await getGraph();
        graphPaths = await getGraphPaths(id);
      } catch {
        // Mini graph is a nice-to-have; ignore failures so the review page still loads.
      }
```

Find the block in the template where `<MomentDetail ...>` is rendered inside the selected-moment conditional:
```svelte
      {#if selectedMoment}
        <MomentDetail
          rollId={roll.id}
          moment={selectedMoment}
          onanalysed={onMomentAnalysed}
          onannotated={onMomentAnnotated}
        />
      {:else}
```

Immediately after `</MomentDetail>` (still inside the `{#if selectedMoment}` branch, before the `{:else}`) insert:

```svelte
        {#if graphTaxonomy && graphPaths}
          <section class="space-y-2 border-t border-white/8 pt-4">
            <div class="text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Graph at this moment
            </div>
            <div class="h-[220px] rounded-md overflow-hidden border border-white/8">
              <GraphCluster
                variant="mini"
                taxonomy={graphTaxonomy}
                paths={graphPaths}
                scrubTimeS={selectedMoment.timestamp_s}
              />
            </div>
            <div class="text-right">
              <a
                href={`/graph?roll=${encodeURIComponent(roll.id)}&t=${Math.floor(selectedMoment.timestamp_s)}`}
                class="text-[11px] text-white/60 hover:text-white/85 underline"
              >
                Open full BJJ graph →
              </a>
            </div>
          </section>
        {/if}
```

- [ ] **Step 4: Run — must pass**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/web
npm test
```

Expected: all tests pass. The new review-analyse test now finds `[data-graphcluster][data-variant="mini"]`.

- [ ] **Step 5: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/web/src/routes/review/[id]/+page.svelte tools/bjj-app/web/tests/review-analyse.test.ts
git commit -m "feat(bjj-app): mount mini graph under MomentDetail on review page"
```

---

## Task 25: Manual browser smoke test

**Files:** none — manual verification.

- [ ] **Step 1: Start dev mode**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app && ./scripts/dev.sh
```

- [ ] **Step 2: Prepare a test roll**

- Upload a short video via `http://127.0.0.1:5173/new`.
- Run pose pre-pass (Analyse button).
- Click at least 2 moments and Analyse them with Claude so both players get position IDs.
- Click "Save to Vault" to publish so the roll appears in the `/graph` dropdown.

- [ ] **Step 3: Navigate to `/graph`**

Open `http://127.0.0.1:5173/graph`. Expected:
- Header with "BJJ Graph" + roll dropdown + filter chips.
- Graph canvas shows 44 nodes clustered into 7 category regions with soft tints.
- Scrubber at bottom is disabled until a roll is chosen.

- [ ] **Step 4: Select the test roll**

Pick your roll from the dropdown. Expected:
- Path overlays appear for Greig (white) + Anthony (red) connecting the analysed moments.
- Scrubber becomes enabled.

- [ ] **Step 5: Drag the scrubber**

Watch the path-head markers glide smoothly between consecutive analysed nodes. Expected behaviour:
- Before the first analysed timestamp: markers invisible.
- Between two analysed timestamps: markers interpolate along the edge.
- After the last analysed timestamp: markers rest on the final node.

- [ ] **Step 6: Filter chips**

- Click a category chip (e.g. "Guard (Bottom)") — non-matching regions dim to 20%.
- Click "Greig" — Anthony's path dims.
- Click "All" — everything returns to full opacity.

- [ ] **Step 7: Click a node**

Click any position node in the graph. Expected:
- Right-side drawer slides in with the rendered markdown of that position's vault note.
- If the node is one of the 12 positions without a markdown file, the drawer shows "No vault note for this position yet".
- Close via X button or Esc.

- [ ] **Step 8: Open in review**

Click the "Open in review →" link in the scrubber footer at some non-zero scrub time. Expected:
- Browser navigates to `/review/<roll_id>?t=<scrub_time>`.
- (Note: video pre-seek from `?t=` is an incidental nicety; the review page's existing video element picks up the timestamp via the URL query. If this doesn't happen automatically yet, it's acceptable — the main integration is the link existing and landing on the right page.)

- [ ] **Step 9: Mini graph on the review page**

Back on `/review/<roll_id>`, select a moment chip. Expected:
- Below the MomentDetail panel, a "Graph at this moment" section appears with a ~220px graph rendering the full taxonomy + both players' path trails + the current moment's position pulsing.
- "Open full BJJ graph →" link goes back to `/graph?roll=...&t=...`.

- [ ] **Step 10: Stop dev server** (Ctrl-C).

---

## Task 26: Update README with M5 status

**Files:**
- Modify: `tools/bjj-app/README.md`

- [ ] **Step 1: Replace the Milestones section**

Find the `## Milestones` section in `/Users/greigbradley/Desktop/BJJ_Analysis/tools/bjj-app/README.md` and replace it (plus everything below it) with:

```markdown
## Milestones

- **M1 (shipped):** Scaffolding. Home page lists vault's `Roll Log/` via `GET /api/rolls`.
- **M2a (shipped):** Video upload (`POST /api/rolls`), review page skeleton, `/assets/` static mount.
- **M2b (shipped):** MediaPipe pose pre-pass, `POST /api/rolls/:id/analyse` SSE endpoint, timeline chips seek the video on click.
- **M3 (shipped):** Claude CLI adapter (sole `claude -p` caller), `POST /api/rolls/:id/moments/:frame_idx/analyse` streaming, SQLite cache, sliding-window rate limiter. Security audit at `docs/superpowers/audits/2026-04-21-claude-cli-subprocess-audit.md`.
- **M4 (shipped):** Append-only annotations per moment, explicit "Save to Vault" publish to `Roll Log/*.md`, hash-based conflict detection on `## Your Notes` only, home page routes via `roll_id` frontmatter.
- **M5 (this milestone):** Full `/graph` page with clustered state-space visualisation (44 nodes in 7 category regions), both players' paths overlaid, filter chips, vault-markdown side drawer, and a timeline scrubber with smoothly-animated path-head markers. Plus a mini graph widget on `/review/[id]` that shares the same component. Design at `docs/superpowers/specs/2026-04-21-bjj-app-m5-graph-page-design.md`.
- **M6 (next):** Summary step + PDF export. One Claude call computes scores, top-3 improvements, strengths. WeasyPrint renders a printed match report.
- **M7–M8:** PWA + mobile polish; cleanup (delete Streamlit `tools/app.py`).
```

- [ ] **Step 2: Commit**

```bash
cd /Users/greigbradley/Desktop/BJJ_Analysis
git add tools/bjj-app/README.md
git commit -m "docs(bjj-app): document M5 (graph page + mini graph + scrubber)"
```

---

## Completion criteria for M5

1. `pytest tests/backend -v` → all green. New M5 tests: `test_taxonomy.py` (8), `test_positions_vault.py` (8), `test_api_graph.py` (3), `test_api_graph_paths.py` (3). Total backend ≈ 115 (M1–M4) + 22 = **137 passing**.
2. `npm test` → all green. New M5 tests: `graph-layout.test.ts` (15), `filter-chips.test.ts` (5), `graph-scrubber.test.ts` (5), `position-drawer.test.ts` (5), `graph-cluster.test.ts` (4), `graph-page.test.ts` (3), plus one added to `review-analyse.test.ts`. Total frontend ≈ 24 (M4) + 38 = **62 passing**.
3. Manual smoke (10 steps above) passes.
4. No M1/M2a/M2b/M3/M4 tests regress.
5. The `/graph` page loads with a seeded, reproducible cose-bilkent layout — refreshing the page doesn't reshuffle nodes.
6. The scrubber's path-head animation is visibly smooth on a roll with ≥3 analysed moments per player.

---

## Out of scope (per spec — deferred to later milestones)

| Deliverable | Why deferred |
|---|---|
| Auto-play button on the scrubber | V1 is manual drag only. Easy follow-up. |
| Bidirectional video↔graph sync | Explicit design choice; `/graph` is standalone. |
| Wikilink navigation inside the drawer | Users open Obsidian for cross-doc browsing. |
| Graph export (PNG/SVG) | M6's PDF export will include a static graph snapshot. |
| Custom node positioning / save layout | Cose-bilkent seed gives stable layout. |
| Listing SQLite-only (unpublished) rolls in the dropdown | Only vault-published rolls appear; publish first. |
| Cross-roll trend statistics | Parent spec revisit list — needs ≥5 rolls to be useful. |
