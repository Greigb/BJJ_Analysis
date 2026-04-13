---
tags: [ml-learning, training]
lesson: 4
---

# 04 - Training a Position Classifier

## Goal

Train your first machine learning model to classify BJJ positions from images, using scikit-learn.

## Concepts

### Your First Model: Random Forest

A Random Forest is a collection of decision trees that each vote on the answer. Think of it as asking 100 training partners to identify a position -- the majority answer wins.

Why start here:
- Simple to understand and implement
- Works reasonably well on small datasets
- Fast to train (seconds, not hours)
- Easy to inspect what it learned

### The Training Pipeline

```python
# Pseudocode for the full pipeline
images = load_images("path/to/frames/")          # Load JPEGs
labels = load_labels("path/to/labels.csv")        # Load position labels
X = resize_and_flatten(images, size=(64, 64))     # 64x64 pixels = 12,288 features
X_train, X_test, y_train, y_test = train_test_split(X, labels, test_size=0.2)
model = RandomForestClassifier(n_estimators=100)
model.fit(X_train, y_train)
accuracy = model.score(X_test, y_test)
```

### Feature Representation

For this first model, we'll use the simplest possible features: raw pixel values.
1. Resize each frame to 64x64 pixels
2. Convert to grayscale (64 * 64 = 4,096 features)
3. Flatten into a 1D array

This is crude -- like identifying a position by squinting at a tiny blurry photo. It works better than you'd expect for a first pass, and the next lesson improves on it dramatically.

### Understanding the Results

**Accuracy** alone is misleading. If 60% of your data is "closed guard", a model that always guesses "closed guard" gets 60% accuracy.

The **confusion matrix** is more useful. It shows, for each true position, what the model predicted:

```
                  Predicted
              CG    HG    SC    Mount
True  CG    [45     3     1     1   ]   ← Closed Guard: 45/50 correct
      HG    [ 5    38     4     3   ]   ← Half Guard: often confused with CG
      SC    [ 0     2    42     6   ]
      Mount [ 1     1     3    45   ]
```

### What To Expect

With ~1,500 frames and raw pixels:
- **Category-level** accuracy (standing/guard/dominant/inferior/scramble): ~60-75%
- **Position-level** accuracy (specific position within category): ~35-50%

This is your baseline. The point isn't perfection -- it's understanding the pipeline so you can improve it.

## Hands-on Exercise

1. Install scikit-learn: `pip install scikit-learn`
2. Prepare your labelled frames from Lessons 02-03
3. Write a script that:
   - Loads frames and labels
   - Resizes frames to 64x64 grayscale
   - Splits into train/test (80/20)
   - Trains a RandomForestClassifier
   - Prints accuracy and confusion matrix
4. Questions to answer:
   - What's the overall accuracy?
   - Which positions does the model confuse most?
   - Does category-level accuracy differ from position-level?

## Resources

- [scikit-learn: Random Forest](https://scikit-learn.org/stable/modules/ensemble.html#random-forests) -- Official docs
- [scikit-learn: Confusion Matrix](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.confusion_matrix.html) -- How to read it
- [Pillow: Image resizing](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.resize) -- For preprocessing

## Journal

<!-- What accuracy did you get? Which positions were most confused? What surprised you? -->
