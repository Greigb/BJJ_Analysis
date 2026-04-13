---
tags: [ml-learning, labelling]
lesson: 3
---

# 03 - Labelling with Claude Vision

## Goal

Use the existing analysis pipeline as a labelling tool, then learn to review and correct labels to build a clean dataset.

## Concepts

### Why Not Just Use Claude Forever?

Claude Vision is excellent at identifying BJJ positions, but:
- Every frame costs money (~$0.01-0.03 per frame)
- It requires network access and has rate limits
- Response times make real-time analysis impossible

Think of Claude as your **coach** -- it teaches you (the model) by providing labels. Once you've learned enough, you can identify positions on your own.

### The Labelling Workflow

1. **Auto-label**: Run `analyse_roll.py --json-only` to get Claude's labels
2. **Review**: Go through each frame + label pair and check correctness
3. **Correct**: Fix any wrong labels
4. **Export**: Save the cleaned dataset in a format suitable for training

### Common Labelling Errors to Watch For

Claude Vision is good but not perfect. Watch for:
- **Transition frames**: The moment between two positions. Claude might pick either one.
- **Occlusion**: When bodies overlap and the position is genuinely hard to see
- **Similar positions**: Half guard vs quarter guard, side control vs scarf hold
- **Role confusion**: Labelling Player A's position as Player B's

### Building a Review Script

You'll want a simple tool that shows you each frame alongside Claude's label and lets you accept or correct it. The JSON output from `analyse_roll.py` contains all the data:

```python
# Each entry in the timeline looks like:
{
    "frame_number": 1,
    "timestamp_sec": 0.0,
    "player_a_position": "standing_neutral",
    "player_b_position": "standing_neutral",
    "confidence": 0.95,
    "active_technique": null,
    "notes": "Both players standing, about to engage"
}
```

Focus on entries where `confidence < 0.7` first -- these are the ones Claude was unsure about.

### Label Format for Training

For your training dataset, you want a simple CSV:
```
frame_path,position_label
frames/frame_0001.jpg,closed_guard_bottom
frames/frame_0002.jpg,closed_guard_bottom
frames/frame_0003.jpg,half_guard_bottom
```

## Hands-on Exercise

1. Take the JSON output from Lesson 02
2. Filter for entries where confidence < 0.7
3. For each low-confidence entry, look at the frame and decide:
   - Was Claude right? Mark as "correct"
   - Was Claude wrong? Write the correct position_id
   - Is it genuinely ambiguous? Mark as "unclear" (we'll exclude these from training)
4. Count your correction rate: how often was Claude wrong?

## Resources

- [Label Studio](https://labelstud.io/) -- Open-source labelling tool (optional, for larger datasets)
- [Anthropic Vision API docs](https://docs.anthropic.com/en/docs/build-with-claude/vision) -- Understanding what Claude sees

## Journal

<!-- How accurate were Claude's labels? Which positions did it struggle with most? -->
