---
tags: [dashboard]
---

# BJJ Analysis Vault

Welcome to your BJJ analysis knowledge base. This vault combines position knowledge, roll analysis, and a structured ML learning path.

## Quick Links

### Knowledge Base
- **[[Positions/]]** - 30 BJJ positions with techniques and transitions
- **[[Techniques/]]** - 94 techniques with descriptions and drill ideas

### Analysis
- **[[Roll Log/]]** - Your analysed rolling sessions
- **How to analyse a roll:**
  ```bash
  cd tools/
  python analyse_roll.py path/to/video.mp4 --player-name Greig --markdown
  ```

## Position Categories

| Category | Positions | Colour |
|----------|-----------|--------|
| Standing | [[Standing - Neutral]], [[Clinch - Collar Tie]] | Grey |
| Guard (Bottom) | [[Closed Guard (Bottom)]], [[Half Guard (Bottom)]], [[Butterfly Guard]], [[Open Guard (generic)]], [[De La Riva Guard]], [[Spider - Lasso Guard]], [[Single Leg X - Ashi Garami]] | Blue |
| Inside Guard (Top) | [[Inside Closed Guard (Top)]], [[Half Guard (Top)]], [[Passing Open Guard (Top)]], [[Headquarters - Passing Position]] | Gold |
| Dominant (Top) | [[Side Control (Top)]], [[Mount (Top)]], [[Back Mount - Back Control]], [[Knee on Belly]], [[North-South (Top)]], [[Crucifix]] | Green |
| Inferior (Bottom) | [[Bottom Side Control]], [[Bottom Mount]], [[Back Taken (Defending)]], [[Turtle (Bottom)]], [[North-South (Bottom)]] | Red |
| Scramble | [[50-50]], [[Turtle Attack (Top)]], [[Front Headlock - Guillotine Position]], [[Leg Entanglement]], [[Scramble (No Clear Position)]] | Purple |

## Tools

| Tool | Purpose |
|------|---------|
| `tools/analyse_roll.py` | Analyse rolling footage with Claude Vision API |
| `tools/generate_vault_notes.py` | Regenerate position/technique notes from taxonomy |
| `tools/taxonomy.json` | Position taxonomy (30 positions, 6 categories) |
