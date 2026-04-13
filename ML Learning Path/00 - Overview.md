---
tags: [ml-learning, overview]
lesson: 0
---

# ML Learning Path - Overview

## What We're Building

A machine learning model that can identify BJJ positions from video frames -- automatically, without needing an API call for every frame.

Right now, the `analyse_roll.py` script sends every frame to the Claude Vision API. This works well, but:
- It costs money per analysis ($1-4 per roll)
- It requires an internet connection
- It's relatively slow (rate-limited API calls)

By training your own position classifier, you'll eventually be able to:
- Analyse rolls offline and instantly
- Process footage in real-time during open mat
- Build a dataset that improves over time

## The Journey

Think of this like learning a martial art. You don't start with berimbolo -- you start with closed guard.

| Lesson | What You'll Learn | BJJ Analogy |
|--------|-------------------|-------------|
| [[01 - Image Classification Basics]] | What is a classifier, how does it learn | Learning the rules of the game |
| [[02 - Data Collection Strategy]] | Building a training dataset from your rolls | Drilling fundamentals |
| [[03 - Labelling with Claude Vision]] | Using AI to label frames, then correcting | Getting feedback from your coach |
| [[04 - Training a Position Classifier]] | Training your first model (Random Forest) | Your first live roll |
| [[05 - Pose Estimation with MediaPipe]] | Using skeleton data instead of raw pixels | Developing technique awareness |
| [[06 - Evaluation and Iteration]] | Measuring and improving your model | Reviewing footage and improving |

## Prerequisites

- Python 3.9+
- The existing analysis tool (`tools/analyse_roll.py`)
- Some BJJ rolling footage
- Curiosity

## How to Use These Notes

Each lesson follows the same structure:
1. **Goal** -- what you'll understand or build
2. **Concepts** -- explanation with BJJ-specific examples
3. **Hands-on** -- a practical exercise using your data
4. **Resources** -- links for deeper reading
5. **Journal** -- space for your own notes and observations

Work through them in order. There's no rush -- take time with each exercise.

## Journal

<!-- Your overall notes as you progress through the path -->
