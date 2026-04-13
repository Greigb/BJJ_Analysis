---
tags: [ml-learning, evaluation]
lesson: 6
---

# 06 - Evaluation and Iteration

## Goal

Evaluate what worked, what didn't, and plan your next steps for improving the BJJ position classifier.

## Concepts

### Taking Stock

By now you've built:
1. A labelled dataset from your rolling footage
2. A pixel-based Random Forest classifier
3. A pose-based classifier using MediaPipe

Time to step back and evaluate honestly -- just like reviewing footage after a competition.

### Evaluation Checklist

Run through these questions for each model:

- [ ] What is the overall accuracy? Is it better than random guessing (1/30 = 3.3%)?
- [ ] What is the category-level accuracy (6 classes)?
- [ ] Which positions have the best/worst per-class accuracy?
- [ ] Which position pairs are most commonly confused?
- [ ] Does the model perform differently on different rolls (overfitting to one environment)?
- [ ] How does confidence correlate with accuracy?

### Common Failure Modes

| Problem | Symptom | Solution |
|---------|---------|----------|
| Not enough data | Low accuracy across all classes | Collect more rolls, augment data |
| Class imbalance | High accuracy on common positions, near-zero on rare ones | Oversample rare classes, collect targeted footage |
| Overfitting | High training accuracy, low test accuracy | More data, simpler model, cross-validation |
| Feature quality | Pose model no better than pixels | Better pose extraction, feature engineering |
| Label noise | Accuracy plateaus despite more data | Review and clean labels |

### Strategies for Improvement

**More data** (almost always helps):
- Record more rolls with consistent camera setup
- Include variety: different partners, gi/nogi, different gyms
- Film specific position drilling for rare classes

**Better features**:
- Combine pixel + pose features
- Add temporal features (how you got to this position)
- Use pre-trained image features (transfer learning with a CNN)

**Better models**:
- Try SVM, Gradient Boosted Trees
- Simple neural network (MLP) on pose features
- Fine-tune a pre-trained CNN (ResNet, EfficientNet) on your frames
- The jump to deep learning makes sense when you have 5,000+ labelled frames

**Better labels**:
- Review confusion-matrix hot spots: are those genuine model errors or label errors?
- Simplify the taxonomy: merge similar positions that even you can't tell apart
- Use a coarse-to-fine approach: classify category first, then position within category

### Where To Go Next

Once your model reaches useful accuracy:

1. **Integrate into the pipeline**: Replace or supplement Claude Vision API calls with your model
2. **Real-time mode**: Feed webcam/GoPro frames through the model during open mat
3. **Session tracking**: Compare position distributions across rolls to measure progress
4. **Technique detection**: Extend from position classification to detecting specific techniques (much harder, but the foundation is the same)

## Hands-on Exercise

1. Create a comparison table of your models so far:
   | Model | Features | Overall Acc | Category Acc | Best Position | Worst Position |
   |-------|----------|-------------|--------------|---------------|----------------|
   | RF (pixels) | 64x64 gray | ? | ? | ? | ? |
   | RF (pose) | 33 landmarks | ? | ? | ? | ? |

2. For your best model, pick the 3 most confused position pairs
3. Look at 5 misclassified frames for each pair -- why did the model fail?
4. Write down your plan: what would you do next to get the biggest accuracy gain?

## Resources

- [scikit-learn: Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) -- More robust evaluation
- [Transfer Learning with PyTorch](https://pytorch.org/tutorials/beginner/transfer_learning_tutorial.html) -- When you're ready for deep learning
- [Papers With Code: Action Recognition](https://paperswithcode.com/task/action-recognition-in-videos) -- Related research

## Journal

<!-- What's your best accuracy so far? What's the single biggest thing holding your model back? What will you try next? -->
