---
tags: [ml-learning, classification]
lesson: 1
---

# 01 - Image Classification Basics

## Goal

Understand what image classification is, how supervised learning works, and what a training pipeline looks like -- before writing any code.

## Concepts

### What is a Classifier?

A classifier is a program that looks at an input (like a photo) and assigns it a label (like "closed guard" or "mount"). It's like a training partner who watches a freeze-frame and calls out what position they see.

### Supervised Learning

"Supervised" means you teach the model by showing it examples with the correct answer:
- **Input:** A frame from your rolling footage
- **Label:** "closed_guard_bottom"

Show the model hundreds of these pairs, and it learns patterns. This is exactly like drilling: you show your body the correct movement over and over until it recognises the position instinctively.

### Training vs Testing

You split your labelled data into two groups:
- **Training set** (~80%) -- the model learns from these
- **Test set** (~20%) -- you check if the model actually learned, using frames it's never seen

This is like the difference between drilling and rolling. Drilling is training. Rolling is the test -- can you apply what you drilled against an unfamiliar situation?

### Key Terms

| Term | Meaning | BJJ Analogy |
|------|---------|-------------|
| **Features** | The data the model looks at (pixel values, skeleton points) | The grips, hooks, and frames you observe |
| **Labels** | The correct answer for each example | The position name your coach would call |
| **Accuracy** | % of test examples the model gets right | Your submission rate in rolling |
| **Confusion matrix** | Table showing what the model confuses | Knowing you mix up half guard and quarter guard |
| **Overfitting** | Model memorises training data but fails on new data | Drilling one specific setup so much you can't adapt to variations |

### How Many Examples Do You Need?

A rough rule of thumb for a 30-class classifier:
- **Minimum:** ~50 labelled frames per position (1,500 total)
- **Good:** ~200 per position (6,000 total)
- **Great:** ~500+ per position (15,000 total)

This sounds like a lot, but with video at 2-second intervals, a single 5-minute roll gives you ~150 frames. Ten rolls = 1,500 frames.

## Hands-on Exercise

No code yet. Instead:

1. Pick 10 frames from a roll (or use any BJJ images)
2. For each frame, write down:
   - What position is Player A in?
   - What position is Player B in?
   - How confident are you? (1-10)
   - What made it hard or easy to identify?
3. Notice: which positions are easy to identify? Which are ambiguous? This is exactly the challenge the model will face.

## Resources

- [3Blue1Brown: Neural Networks](https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi) -- Visual, intuitive explanations
- [Google ML Crash Course](https://developers.google.com/machine-learning/crash-course) -- Free, structured intro
- [scikit-learn: Classification](https://scikit-learn.org/stable/supervised_learning.html) -- The library we'll use first

## Journal

<!-- What was surprising? Which positions were hardest to identify manually? -->
