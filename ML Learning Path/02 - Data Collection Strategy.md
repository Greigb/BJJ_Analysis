---
tags: [ml-learning, data]
lesson: 2
---

# 02 - Data Collection Strategy

## Goal

Understand how to build a high-quality training dataset from your BJJ rolling footage, and why data quality matters more than model complexity.

## Concepts

### Garbage In, Garbage Out

The single most important factor in ML is data quality. A simple model trained on clean, well-labelled data will outperform a complex model trained on noisy data. In BJJ terms: a white belt with solid fundamentals beats a blue belt with sloppy technique.

### Your Data Pipeline

```
Rolling footage (MP4)
    ↓ ffmpeg (extract frames)
Keyframes (JPG, every 2s)
    ↓ Claude Vision API (initial labels)
Labelled frames (frame + position_id)
    ↓ Manual review (correct mistakes)
Clean training dataset
    ↓ Train/test split
Ready for model training
```

The `analyse_roll.py --json-only` command gives you steps 1-2 automatically. Step 3 (manual review) is where you add value.

### What Makes Good Training Data

| Factor | Good | Bad |
|--------|------|-----|
| **Camera angle** | Overhead / 45 degrees | Side-on (occlusion) |
| **Lighting** | Even, consistent | Shadows, backlighting |
| **Framing** | Both grapplers fully visible | Partial bodies, cropped |
| **Variety** | Different partners, gi/nogi, speeds | Same roll repeated |
| **Balance** | Similar frame counts per position | 500 closed guard, 5 crucifix |

### Class Imbalance

Some positions happen way more than others. You'll probably have hundreds of "closed guard" frames but only a few "crucifix" frames. This is a real problem -- the model learns to just guess "closed guard" for everything.

Solutions:
- **Collect more** of rare positions (targeted drilling footage)
- **Oversample** rare classes (duplicate them in training)
- **Undersample** common classes (use fewer of them)
- **Augment** -- flip, rotate, brightness-adjust images to create variations

### How Much Data to Collect First

Start small. Get 5 rolls analysed and reviewed before worrying about model training. That gives you ~750 labelled frames -- enough to train a first model and see what's working.

## Hands-on Exercise

1. Run the analyser on one of your rolls:
   ```bash
   python tools/analyse_roll.py path/to/roll.mp4 --json-only --player-name Greig --output tools/data/my_first_roll.json
   ```
2. Open the JSON output and look at the labels
3. Count how many frames landed in each position category
4. Note which positions have 0 frames -- these are gaps in your dataset
5. Save these observations in your journal below

## Resources

- [Google: Data Preparation and Feature Engineering](https://developers.google.com/machine-learning/data-prep) -- Practical guide
- [Andrew Ng: Data-Centric AI](https://www.youtube.com/watch?v=06-AZXmwHjo) -- Why data quality > model complexity

## Journal

<!-- Which positions are over/under-represented in your footage? What camera setup will you use going forward? -->
