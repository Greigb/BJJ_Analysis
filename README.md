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

## Roadmap

1. Pose estimation layer (MediaPipe BlazePose)
2. ML classifier (train on labelled skeleton data)
3. Transition graph validation (flag impossible transitions)
4. Session-over-session tracking (progress metrics)
5. Real-time mode (analyse live footage)
