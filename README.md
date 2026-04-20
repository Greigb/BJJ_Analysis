# BJJ Analysis

An Obsidian vault and AI-powered toolkit for analysing BJJ rolling footage, building a position knowledge base, and learning to train a custom ML classifier.

## What's Inside

### Obsidian Vault

Open this folder in [Obsidian](https://obsidian.md/) to get an interconnected BJJ knowledge base:

- **Positions/** -- 30 position notes with techniques and transitions linked via wikilinks
- **Techniques/** -- 94 technique notes linked back to their positions
- **Roll Log/** -- Analysed rolling sessions with scores and coaching feedback
- **ML Learning Path/** -- 7 structured lessons from "what is ML" to "train a position classifier"
- **Home.md** -- Vault dashboard with quick links to everything

### Analysis Tools

```
tools/
├── analyse_roll.py          # AI-powered roll analysis (Claude Vision API)
├── generate_vault_notes.py  # Generate position/technique notes from taxonomy
├── taxonomy.json            # 30 positions, 6 categories, valid transitions
├── requirements.txt         # Python dependencies
└── components/
    ├── bjj-position-graph.jsx      # Interactive position graph (React)
    └── bjj-position-taxonomy.jsx   # Position taxonomy browser (React)
```

## Sample Analysis — Greig vs Anthony, Tempo Open Mat (2026-04-14)

The most recent footage is a 3:39 open mat session at Tempo Jiu Jitsu, split by the analyser into two distinct rolls (separated by a tap event detected at 2:26). See [`Roll Log/2026-04-14 - Greig vs Anthony - Roll 1 (WIN by submission).md`](Roll%20Log/2026-04-14%20-%20Greig%20vs%20Anthony%20-%20Roll%201%20%28WIN%20by%20submission%29.md) for the full breakdown.

### What the analyser produced

**Roll 1 — WIN by submission (0:03 → 2:26, 2:23 of mat time)**

| Metric | Score | Reason |
|---|---|---|
| Guard Retention | 7/10 | On top the entire roll. |
| Positional Awareness | 7/10 | Good 80/20 escape from 50/50, but caught in 50/50 three times. |
| Transition Quality | 7/10 | Clean passes, smooth 50/50 escapes, finished with submission. |

**Position timeline (one cell per analysed frame):**

```
⬜⬜🟨🟨🟧🟧🟧🟧🟧🟪🟨🟩🟩🟨🟨🟨🟨🟨🟩🟩🟨🟧🟩🟨🟨🟩🟨🟩
```
⬜ Standing 🟨 Guard (Top) 🟧 Leg Entanglement 🟪 Scramble 🟩 Dominant (Top) 🟦 Guard (Bottom) 🟥 Inferior (Bottom)

**Roll 2 — Continuation, swept and lost position (2:31 → 3:39):**

```
🟨🟪🟥🟥🟥🟥🟥🟥🟦🟦
```

### What the tool is actually doing

For each analysed frame the pipeline:

1. **Detects roll-boundary events** — slap/bump (start) at 0:03, tap (end) at 2:26 — so the analyser splits the footage into two rolls automatically rather than treating it as one continuous match.
2. **Classifies position for both players** against the 30-position taxonomy in `tools/taxonomy.json` (e.g. `Passing Open Guard (Top)` vs `Single Leg X / Ashi Garami`).
3. **Applies the leg-entanglement decision tree** — three-question walk (Q1 mirrored? Q2 same direction? Q3 outside leg over hip?) to disambiguate `50/50` vs `80/20 (Dominant 50-50)` vs `single leg X`. Sample output at 0:26:
   > *Q1 mirrored? YES → Q2 same direction? YES → Q3 outside leg over hip? YES → eighty_twenty.*
4. **Validates transitions** against the allowed-edges graph in the taxonomy and flags illegal jumps for review.
5. **Generates an Obsidian note** with annotated frame screenshots, wikilinks back to position pages, per-phase coaching tips, and the position-distribution table.
6. **Writes raw JSON** alongside the markdown so the same frames can later become labelled training data for an ML classifier.

### Coach's notes the analyser surfaced

- **Anthony's 50/50 game** — pulled into mirrored leg entanglement three times in 2:23. Decision tree caught all three. The action item is the entry point at ~0:14, not the entanglement itself.
- **Reguard cycle** — 4+ passes to side control, 0 advances to mount. Side control held for ~12s on average before reguard. Target: pass → mount within 3 seconds.
- **Closed-guard sweep at 2:40** — broken posture on the knees inside closed guard, same vulnerability flagged in every prior analysis. Action: stand to break.

## Quick Start

### 1. Open the Vault

1. Install [Obsidian](https://obsidian.md/)
2. Open this folder as a vault
3. Start at **Home.md**

### 2. Analyse a Roll

```bash
# Install dependencies
cd tools/
pip install -r requirements.txt
export ANTHROPIC_API_KEY='your-key-here'

# HTML report
python analyse_roll.py path/to/roll.mp4 --player-name Greig

# Obsidian markdown note (lands in Roll Log/)
python analyse_roll.py path/to/roll.mp4 --player-name Greig --markdown

# Raw JSON for ML training data
python analyse_roll.py path/to/roll.mp4 --player-name Greig --json-only
```

### 3. Start the ML Learning Path

Open **ML Learning Path/00 - Overview.md** in Obsidian and work through the lessons in order.

## Regenerating Vault Notes

If you modify `taxonomy.json`, regenerate the position and technique notes:

```bash
python tools/generate_vault_notes.py
```

## Camera Tips for Best Results

1. **Angle** -- overhead or elevated 45 degrees is ideal
2. **Stability** -- tripod or fixed mount
3. **Lighting** -- even, consistent, avoid backlighting
4. **Framing** -- both grapplers fully visible throughout
5. **Background** -- clean mat, minimal clutter

## Cost Estimate

Each analysis uses Claude Sonnet with vision:
- 5 min roll @ 2s interval = ~150 frames = ~30 API calls ~ $1-3
- 10 min roll @ 3s interval = ~200 frames = ~40 API calls ~ $2-4

## Next Steps

Driven directly by gaps surfaced in the 2026-04-14 analysis:

1. **Pose estimation layer (MediaPipe BlazePose)** — replace prose position calls with skeleton geometry so the leg-entanglement decision tree (Q1/Q2/Q3) runs deterministically instead of being inferred each frame by Claude.
2. **ML position classifier** — train on the JSON exports already accumulating in `assets/` (every roll analysis writes a labelled frame set). First target: the seven recurring positions in the Roll 1 timeline.
3. **Pattern detection across sessions** — automatically flag recurring vulnerabilities (the closed-guard sweep at 2:40 is the same posture failure flagged in every prior roll). Surface it in the Home dashboard, not buried in one note.
4. **Tighter event detection** — slap/bump and tap detection landed in v4; next is sweep-detection and submission-attempt detection so the roll splitter does not need a tap to find boundaries.
5. **Session-over-session tracking** — chart guard-retention / positional-awareness / transition-quality scores against partner and date.
6. **Real-time mode** — stream frames from a phone camera and surface decision-tree calls live during open mat.

## Roadmap (longer term)

- Transition graph validation surfaced as an Obsidian sidebar
- Auto-generated technique drilling plans from the top-3 improvements list
- Coach-mode export (PDF) per session
