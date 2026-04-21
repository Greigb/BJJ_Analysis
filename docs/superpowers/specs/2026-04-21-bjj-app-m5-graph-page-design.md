# BJJ App M5 — Graph Page + Mini Graph — Design

**Date:** 2026-04-21
**Status:** Design approved, implementation plan pending
**Parent spec:** [2026-04-20-bjj-local-review-app-design.md](./2026-04-20-bjj-local-review-app-design.md)
**Prior milestone:** M4 (annotations + vault write-back) merged at `3dc45c8` on main.

## Context

M1–M4 shipped the upload → analyse → review → annotate → publish flow for a single roll. What's missing is the cross-cutting view: where do these moments sit in the BJJ state space as a whole? A user who looks at a 15-minute roll through 44 position IDs wants to see both players' paths overlaid on the full taxonomy, with context about how each position relates to its neighbours.

M5 ships two new views:
- A full-screen `/graph` page showing the clustered BJJ state space (44 positions × 7 categories) with both players' roll paths overlaid, click-to-vault-note side panel, category/player filter chips, and a timeline scrubber that animates the path head smoothly as you scrub.
- A mini graph widget on `/review/[id]` that renders under the `MomentDetail` panel when a moment is selected, showing both players' current node plus a dashed trail of prior analysed moments.

Both views share a single `GraphCluster.svelte` component with a `variant` prop.

## Goals

1. **Full state-space visualisation.** See all 44 taxonomy positions clustered by category (7 regions with soft tints), connected by the background transitions from `valid_transitions`.
2. **Per-roll player paths overlaid.** Greig (white) and Anthony (red) paths drawn as connect-the-dots between analysed moments; sparse gaps are fine.
3. **Smooth scrubber.** A timeline range input animates each player's path-head marker along the current path edge, interpolating linearly between analysed moments.
4. **Click-to-vault-note drawer.** Right-side drawer renders the clicked position's Obsidian markdown from `Positions/*.md` (matched by frontmatter `position_id`).
5. **Filter chips.** Single-select chips dim non-matching regions/players to 20% opacity. `All` resets.
6. **Mini graph on review page.** When a moment is selected, a compact static graph below `MomentDetail` shows both players' positions at that moment plus dashed trails. "Open full BJJ graph" link jumps to `/graph` pre-scrolled to that moment.

## Non-goals (explicit)

- **No auto-play on the graph page.** The scrubber is manual drag-only in V1. A play/pause button can be added later.
- **No bidirectional video↔graph sync.** `/graph` is standalone (no video element). If you want to see the video at a specific scrub time, you click "Open in review" which pre-seeks the video.
- **No wikilink navigation in the side drawer.** `[[Technique]]` links render as plain underlined text, not anchors. Users open Obsidian for cross-navigation.
- **No new SQLite schema.** All data comes from taxonomy.json + M3's analyses table + existing `Positions/*.md` vault files.
- **No per-position technique lists curation.** The drawer shows whatever's in the markdown file; M5 doesn't touch Positions content.
- **No auto-layout customisation UI.** Users cannot reposition nodes; layout is deterministic from a seeded cose-bilkent run.

## Design decisions (captured from brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Scope | B — full M5 per parent spec, including scrubber | User wants the full state-space-playback experience. |
| Player path drawing | (a) Connect-the-dots | Honest about sparse data; simplest to draw. |
| Graph layout | (a) cose-bilkent compound | Automatic category clustering via Cytoscape compound parents. Seeded for reproducibility. |
| Filter chip behaviour | (b) Dim (single-select) | Emphasis without losing orientation; no re-layout jank. |
| Scrubber location | (a) Standalone on `/graph`, no video | Graph gets full canvas; video stays on review page. |
| Side panel layout | (a) Right-side drawer | Matches Obsidian's pane style; enough width for markdown. |
| Mini graph placement | (b) Only when moment selected, below MomentDetail | Contextual value; keeps review page clean when idle. |
| Path-head animation | (b) Smooth linear interpolation | Justifies B's extra cost; delivers the playback experience. |

## Architecture

Cytoscape.js renders everything. The full `/graph` page and the mini widget on `/review/[id]` share one component (`GraphCluster.svelte`) with a `variant` prop that toggles size, interactivity, scrubber, and filter chips. Backend is thin — three read-only endpoints serving cached taxonomy + per-roll path queries + position markdown.

### Dependencies

Both loaded via CDN `<script>` tags in `web/src/app.html`:
- `cytoscape.min.js` (v3.28+) — core graph renderer.
- `cytoscape-cose-bilkent.js` — compound-parent clustering layout extension.

Chosen over npm install to avoid a frontend bundle size hit and match the parent spec's direction. Offline dev caches the CDN response; acceptable for a single-user LAN app.

### New backend modules

- **`server/analysis/taxonomy.py`** — Pure reader. `load_taxonomy(path) -> Taxonomy` returns a dict with `{categories, positions, transitions, tints}`. Transitions list comes from `valid_transitions` in the JSON. Tints are a hardcoded palette keyed by `category_id`. Called once at app startup; result is cached in `app.state.taxonomy`.
- **`server/analysis/positions_vault.py`** — `load_positions_index(vault_root) -> dict`. Scans `Positions/*.md` once at startup, parses frontmatter, builds `{position_id: {name, markdown, vault_path}}` dict. Positions without a `position_id` frontmatter field are skipped. Index stored at `app.state.positions_index`.
- **`server/api/graph.py`** — Three endpoints (see API surface below).

### New frontend modules

- **`web/src/lib/components/GraphCluster.svelte`** — Core component. Takes `variant: 'full' | 'mini'`, `nodes`, `edges`, `categories`, `paths?`, `onnodeclick?`, `scrubTime?`. Mounts a Cytoscape instance on a `<div>`, renders compound category parents + 44 position nodes + taxonomy edges + path overlays. Handles node-click emission, scrub-time path-head animation.
- **`web/src/lib/components/PositionDrawer.svelte`** — Right-side drawer. Takes `open`, `positionNote`, `onclose`. Renders markdown via `marked.js` (CDN). Esc key + X button close.
- **`web/src/lib/components/GraphScrubber.svelte`** — Range input bound to a `scrubTime` value. Takes `durationS`, `scrubTime`, `rollId`. Emits `ontimechange`. Includes "Open in review" link with query params.
- **`web/src/lib/components/FilterChips.svelte`** — Chip row. Takes `categories`, `activeFilter`, `onfilterchange`. Emits selection changes.
- **`web/src/routes/graph/+page.svelte`** — The `/graph` page. Wires roll dropdown, filter chips, scrubber, GraphCluster, drawer state.

### Mounting the mini graph on /review/[id]

`<GraphCluster variant="mini" ...>` mounts below the `MomentDetail` component when `selectedMoment !== null`. Props include the single selected moment's positions as `currentMoment`, plus the full analysed-moments list as `allMoments` for the dashed trail.

## Data model

No SQLite schema changes. All sources already exist:

- **`tools/taxonomy.json`** — 7 categories, 44 positions, `valid_transitions` edge list. Shipped in repo.
- **`server.db.analyses`** (M3) — per-moment per-player `{player, position_id, confidence, description, coach_tip}`. The path for a roll/player is `SELECT position_id, timestamp_s FROM analyses JOIN moments ORDER BY timestamp_s`.
- **`Positions/*.md`** — 46 markdown files. Each starts with YAML frontmatter including `position_id`. 32/44 taxonomy positions have a markdown note; the rest fall through to the 404 handler in the drawer.

### Category tints

Hardcoded palette in `taxonomy.py`:
```python
TINTS = {
    "standing":          "#e6f2ff",  # pale blue
    "guard_bottom":      "#e6f7e6",  # pale green
    "guard_top":         "#fff5e6",  # pale orange
    "dominant_top":      "#ffe6e6",  # pale red
    "inferior_bottom":   "#f0e6ff",  # pale purple
    "leg_entanglement":  "#fff9cc",  # pale yellow
    "scramble":          "#eeeeee",  # pale grey
}
```
Shipped to the frontend in the `GET /api/graph` response; no duplication in JS.

## API surface

All under `/api`. All three endpoints are read-only and safe to cache.

| Method | Path | Purpose |
|---|---|---|
| GET | `/graph` | Taxonomy skeleton: categories + positions + transitions + tints. Cached in memory; constant across the app's lifetime. |
| GET | `/graph/paths/:roll_id` | Per-roll sparse path arrays for Greig and Anthony. Ordered by timestamp_s. 404 if roll doesn't exist. |
| GET | `/vault/position/:position_id` | Markdown body for the position's vault note. 404 if no `Positions/*.md` file has that `position_id` in frontmatter. |

### `GET /api/graph` response shape

```json
{
  "categories": [
    {"id": "guard_bottom", "label": "Guard (Bottom)", "dominance": 1, "tint": "#e6f7e6"},
    ...
  ],
  "positions": [
    {"id": "closed_guard_bottom", "name": "Closed Guard (Bottom)", "category": "guard_bottom"},
    ...
  ],
  "transitions": [
    {"from": "standing_neutral", "to": "standing_clinch"},
    ...
  ]
}
```

### `GET /api/graph/paths/:roll_id` response shape

```json
{
  "duration_s": 225.0,
  "paths": {
    "greig": [
      {"timestamp_s": 3.0, "position_id": "closed_guard_bottom", "moment_id": "..."},
      {"timestamp_s": 10.0, "position_id": "half_guard_bottom", "moment_id": "..."}
    ],
    "anthony": [
      {"timestamp_s": 3.0, "position_id": "closed_guard_top", "moment_id": "..."},
      {"timestamp_s": 10.0, "position_id": "half_guard_top", "moment_id": "..."}
    ]
  }
}
```
Empty arrays (`[]`) if no analyses yet. `duration_s` from `rolls.duration_s` (may be null on pre-M2a rolls, handled gracefully).

### `GET /api/vault/position/:position_id` response shape

```json
{
  "position_id": "closed_guard_bottom",
  "name": "Closed Guard (Bottom)",
  "markdown": "# Closed Guard (Bottom)\n\n**Category:** Guard (Bottom)\n\n## How to Identify\n...",
  "vault_path": "Positions/Closed Guard (Bottom).md"
}
```
Returns 404 with `{"detail": "No vault note for this position"}` if position_id has no corresponding markdown file with matching frontmatter.

## Key flows

### Flow A — `/graph` page load + roll selection

```
1. User navigates to /graph (from home nav or from review page's "Open full BJJ graph" button).
2. Frontend calls GET /api/graph → taxonomy skeleton.
3. Cytoscape renders compound-clustered layout via cose-bilkent (seeded, deterministic).
   Each category = compound parent node with tint as background-color.
   Each position = child of its category parent.
   Each valid_transition = edge with grey dashed style.
4. Roll dropdown populated via GET /api/rolls (existing endpoint).
5. User picks a roll → frontend calls GET /api/graph/paths/:roll_id.
6. Path overlay rendering (connect-the-dots):
     - Highlight each visited node with a per-player ring (white/red).
     - Draw thick colored edges between consecutive analysed moments in timestamp order.
     - The edges are "overlay" edges distinct from taxonomy edges; they draw on top.
7. Filter chips respond by setting Cytoscape style selectors to dim non-matching to 0.2 opacity.
```

### Flow B — Scrub + smooth path-head animation

```
1. User drags the range-input scrubber. A $state "scrubTimeS" updates reactively.
2. Per player, on scrubTime change:
     prev = last path entry where timestamp_s <= scrubTimeS
     next = first path entry where timestamp_s > scrubTimeS
     if both: t = (scrubTimeS - prev.timestamp_s) / (next.timestamp_s - prev.timestamp_s)
              head.x = lerp(prev_node.x, next_node.x, t)
              head.y = lerp(prev_node.y, next_node.y, t)
     elif only prev: head at prev_node (at rest)
     elif only next: head invisible (scrubber is before first analysed moment)
3. Cytoscape "head marker" node (one per player) is a top-layer node with position updated via
   cy.getElementById('head-greig').position({x, y}) inside a Svelte $effect.
4. Path-trail rendering:
     - Solid colored edges between completed segments (prev and before).
     - Dashed edge from prev → head marker's current position (a dynamic edge updated per scrub).
     - Future segments (after next) invisible.
```

### Flow C — Click node → side panel

```
1. User taps a node in the graph.
2. Cytoscape's 'tap' event fires with the node id = position_id.
3. Frontend calls GET /api/vault/position/:position_id.
   200 → PositionDrawer opens on the right with rendered markdown.
   404 → drawer opens with fallback "No vault note for this position yet" + category/visual_cues from taxonomy.
4. Close via X button or Esc key.
```

### Flow D — Mini graph on /review/[id]

```
1. User selects a moment chip on /review/[id].
2. MomentDetail renders as usual (existing M3+M4 behaviour).
3. Below MomentDetail, <GraphCluster variant="mini" ...> mounts. The mini graph fetches both `GET /api/graph` (taxonomy; cached client-side across the session in a module-level state) and `GET /api/graph/paths/:roll_id` (per-roll path arrays). Both endpoints are already used by `/graph` — reusing them keeps path logic centralised in the backend and guarantees the two views show identical data.
     currentMoment = selectedMoment (the chip the user just clicked)
     Interactivity disabled: no tap, no scrubber, no filter chips.
4. Mini graph visual:
     - All 44 nodes + taxonomy edges at low opacity (background skeleton).
     - Dashed colored edges through each player's analysed moments up to and including currentMoment.
     - currentMoment's two nodes (greig + anthony) get a pulse ring (CSS animation).
5. Bottom of mini graph: "Open full BJJ graph →" anchor to /graph?roll=<roll_id>&t=<moment.timestamp_s>.
```

### Edge cases handled inline

| Case | Handling |
|---|---|
| No analyses yet for the roll | Paths are empty arrays. Graph renders the taxonomy skeleton only; scrubber is still present but disabled (greyed-out) with label "No analyses yet". |
| Position ID in analyses doesn't match any taxonomy position | Skip it in path construction; log a warning. Should not happen under normal flow (Claude returns ids from our prompt's list). |
| Position ID has no vault markdown | `GET /vault/position/:id` returns 404; drawer shows fallback text. Non-fatal. |
| `duration_s` is null on the roll | `duration_s` in the paths response is null; scrubber defaults its max to the last path timestamp + 1s. |
| User opens `/graph` with no roll selected | Graph shows taxonomy skeleton only. Filter chips still work. Scrubber hidden until a roll is picked. |
| Cytoscape fails to load (offline) | `<GraphCluster>` renders a fallback message: "Graph rendering unavailable — check your connection." |
| Two players occupy the same node at the same moment | Both rings overlap with a 2px offset so both colors are visible. Path edges draw through normally. |

## UI layout

### `/graph` page

Single scrollable page, three horizontal bands:

```
┌─────────────────────────────────────────────────────────────────────┐
│ Header: BJJ Graph   [Roll: ▼]   [All] [Std] [GB] [GT] ... [Greig][A]│
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                Cytoscape canvas (graph body, full-bleed)            │
│                        ← drawer slides from right                   │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  0:00  ▐──────────●──────────▐  3:45            Open in review →    │
└─────────────────────────────────────────────────────────────────────┘
```

- Header: page title, roll dropdown, filter chips in one band. Chips are single-select; clicking `All` resets.
- Canvas: graph fills the middle. When the drawer opens, canvas shrinks to `calc(100% - 400px)` — Cytoscape re-layouts automatically.
- Footer: scrubber `<input type="range">` + `currentTime / duration` display + "Open in review" link (preserves `?roll` and `?t`).

### `/review/[id]` page — mini graph integration

```
existing layout …
├ moments chip row
├ MomentDetail panel
├ ─── NEW: Mini Graph ──────────────────────────────────┐
│   [compact graph ~200px tall]                          │
│   "Open full BJJ graph →" /graph?roll=...&t=...         │
├ ─────────────────────────────────────────────────────┘
└ Save to Vault footer
```

### Side drawer

```
┌────────────────────────┐
│ Closed Guard (Bottom) X│
├────────────────────────┤
│ (rendered markdown)    │
│ Category: Guard Bottom │
│ ## How to Identify     │
│ Person on their BACK…  │
│ ...                     │
└────────────────────────┘
```

- Width: 400px desktop, full-width on <640px viewports.
- Close: X button, Esc key, or click outside the drawer (on the dimmed overlay).

### Filter chip states

- Unselected (`All` default): all chips neutral, graph at 100% opacity.
- Selected (e.g. `Guard Bottom`): that chip solid-tinted with category color; other chips fade to 50%; non-matching nodes/edges/paths dim to 20% opacity.
- Per-player chips (`Greig`, `Anthony`) stack separately — clicking dims the other player's path to 20%.

## File layout

```
tools/bjj-app/
├── server/
│   ├── analysis/
│   │   ├── taxonomy.py               # NEW: load_taxonomy + TINTS
│   │   └── positions_vault.py        # NEW: load_positions_index + get_position
│   ├── api/
│   │   └── graph.py                  # NEW: GET /api/graph, /api/graph/paths/:id, /api/vault/position/:id
│   └── main.py                       # MODIFY: register graph_api.router; build taxonomy + positions_index at startup
├── tests/backend/
│   ├── test_taxonomy.py              # NEW
│   ├── test_positions_vault.py       # NEW
│   ├── test_api_graph.py             # NEW
│   └── test_api_graph_paths.py       # NEW
└── web/
    ├── src/
    │   ├── app.html                   # MODIFY: add cytoscape + cose-bilkent CDN <script> tags
    │   ├── lib/
    │   │   ├── api.ts                # MODIFY: add getGraph, getGraphPaths, getPositionNote
    │   │   ├── types.ts              # MODIFY: add GraphNode, GraphEdge, GraphCategory, GraphPaths, PositionNote
    │   │   └── components/
    │   │       ├── GraphCluster.svelte          # NEW: shared full/mini renderer
    │   │       ├── PositionDrawer.svelte        # NEW: right-side drawer
    │   │       ├── GraphScrubber.svelte         # NEW: time scrubber for /graph
    │   │       └── FilterChips.svelte           # NEW: category + player filter row
    │   └── routes/
    │       ├── graph/+page.svelte               # NEW: /graph full page
    │       └── review/[id]/+page.svelte         # MODIFY: mount <GraphCluster variant="mini"> under MomentDetail
    └── tests/
        ├── graph-cluster.test.ts                # NEW
        ├── graph-scrubber.test.ts               # NEW
        ├── position-drawer.test.ts              # NEW
        ├── filter-chips.test.ts                 # NEW
        ├── graph-page.test.ts                   # NEW
        └── review-analyse.test.ts               # MODIFY: mini graph assertion
```

## Testing strategy

### Backend (pytest)

- **`test_taxonomy.py`** — `load_taxonomy` with a fixture json file returns parsed categories/positions/transitions; each category has a `tint` string; unknown category in a position raises.
- **`test_positions_vault.py`** — Build a tmp vault with two position markdown files; verify the index contains only the one with `position_id` frontmatter. `get_position` returns the full markdown body for a known id and None for a missing id.
- **`test_api_graph.py`** — `GET /api/graph` returns the full shape. `GET /api/vault/position/:id` returns markdown for a known id; 404 for an unknown id.
- **`test_api_graph_paths.py`** — Reuse M3 `insert_analyses` fixtures. Create a roll with 2 moments analysed for both players. `GET /api/graph/paths/:roll_id` returns two sorted path arrays. 404 for unknown roll. Empty arrays for a roll with no analyses.

### Frontend (Vitest + Svelte Testing Library)

- **`graph-cluster.test.ts`** — Render with `variant="full"` → container exists with `data-variant="full"`. Render with `variant="mini"` → smaller container, no scrubber. Render with sample paths → path overlay edges drawn (asserted via Cytoscape's `cy.edges('.path-overlay').length`). Clicking a node fires `onnodeclick` with position_id.
- **`graph-scrubber.test.ts`** — Renders range input. Dragging updates bound value. "Open in review" link includes `?roll=` and `?t=`.
- **`position-drawer.test.ts`** — Open with a position note → renders markdown headings + body. Esc closes. Open with null note → fallback text renders.
- **`filter-chips.test.ts`** — Default (all neutral). Click a chip → active state. Click `All` → back to neutral. Emits filter change callbacks.
- **`graph-page.test.ts`** — `/graph` page mounts and fetches `/api/graph` + `/api/graph/paths/...`, passes results to `<GraphCluster>`, wires chip + scrubber state.
- **`review-analyse.test.ts`** (extended) — When a moment is selected, a `<div data-testid="mini-graph">` is rendered below MomentDetail.

### Cytoscape testing notes

Vitest runs in jsdom. Cytoscape works in jsdom (no WebGL needed) but cannot render actual graph geometry. Component tests assert structural facts (correct container attrs, correct number of nodes/edges attached, correct event handlers fire) rather than pixel-level layout. Layout fidelity is covered by the manual smoke test.

### Manual smoke (M5 completion gate)

1. Upload a roll, analyse ≥2 moments for both players.
2. Navigate to `/graph`, pick the roll from the dropdown.
3. See 44 position nodes clustered into 7 category regions with soft tints.
4. See Greig (white ring + thick white overlay edges) and Anthony (red ring + thick red overlay edges) paths.
5. Drag the scrubber — path-head markers glide smoothly between their current and next nodes.
6. Click `Guard Bottom` — non-Guard-Bottom regions dim to 20% opacity.
7. Click `Greig` — Anthony's path dims to 20%.
8. Click a node — right drawer slides in with rendered Obsidian markdown (headings, bullets, visual_cues).
9. Esc key closes the drawer.
10. Click "Open in review" on the scrubber footer — navigates to `/review/<roll>` with the video pre-seeked to the scrub time.
11. On `/review/[id]`, select a moment chip — mini graph appears below MomentDetail with both players' current positions pulsing + dashed trail back through prior moments.
12. Click "Open full BJJ graph" on the mini graph — lands on `/graph` with that roll pre-selected and scrubber pre-set to that moment's timestamp.

## Dependencies

**Backend:** no new Python dependencies.

**Frontend:** two CDN scripts in `web/src/app.html`:
```html
<script src="https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
<script src="https://unpkg.com/cytoscape-cose-bilkent@4.1.0/cytoscape-cose-bilkent.js"></script>
```

Also needs a markdown renderer for the drawer. Two options:
- `marked.js` via CDN (`https://cdn.jsdelivr.net/npm/marked/marked.min.js`) — ~30KB, zero config.
- Render markdown server-side in `GET /api/vault/position/:id` via Python's `markdown` package — adds a dependency but keeps the frontend simpler.

**Chosen:** CDN `marked.js` to stay consistent with the cytoscape CDN approach and keep the backend free of HTML rendering.

## Out of scope (explicitly deferred to later milestones)

| Deliverable | Why deferred |
|---|---|
| Auto-play button on the scrubber | V1 is manual-only. Add a play/pause with a fixed speed later if useful. |
| Bidirectional video↔graph sync (video plays, graph scrubs in step) | Would require `/graph` to embed the video or use a shared store; explicit UX choice to keep `/graph` standalone. |
| Scrubber bookmarks ("jump to moment N") | The mini graph's "Open full BJJ graph" pre-seeks to the current moment's time, which covers the main use case. |
| Per-player trail customisation (opacity, thickness) | Hardcoded styles in V1. |
| Wikilink navigation inside the drawer | Users open Obsidian for cross-doc browsing. |
| Custom node positioning / save layout | cose-bilkent seed gives a stable layout; user can't drag nodes. |
| Graph export (PNG/SVG) | M6 PDF export will include a static graph snapshot. Live graph export can come later. |
| Zoom-to-fit button | Cytoscape ships one; we'll expose it if testing shows the default viewport is awkward. |

## Completion criteria

1. `pytest tests/backend -v` → all green, including the 4 new M5 backend test files (~15 new tests).
2. `npm test` → all green, including the 5 new M5 frontend test files (~20 new tests). Total frontend ≥ ~44.
3. Manual smoke (12 steps) passes.
4. No M1/M2a/M2b/M3/M4 tests regress.
5. The taxonomy + positions index are built once at app startup; `GET /api/graph` serves from cache and responds in <5ms.
6. Scrubber path-head animation feels smooth (subjective but gated on manual smoke step 5).
