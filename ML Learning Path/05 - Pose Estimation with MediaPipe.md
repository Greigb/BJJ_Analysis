---
tags: [ml-learning, pose-estimation]
lesson: 5
---

# 05 - Pose Estimation with MediaPipe

## Goal

Replace raw pixel features with skeleton keypoints using MediaPipe BlazePose, then retrain your classifier and compare.

## Concepts

### Why Skeleton Data?

Raw pixels contain a lot of noise: gi colour, mat pattern, lighting, camera angle. The model has to learn to ignore all of that and focus on body positions.

Pose estimation extracts the signal directly: 33 body landmarks (shoulders, elbows, hips, knees, etc.) as x/y/z coordinates. This is like the difference between a white belt who stares at the whole picture vs a black belt who reads hip position, knee angle, and weight distribution.

### MediaPipe BlazePose

Google's MediaPipe provides a free, fast pose estimation model. For each person in a frame, it outputs 33 landmarks:

```
0: nose          11: left shoulder   23: left hip
1: left eye      12: right shoulder  24: right hip
2: right eye     13: left elbow      25: left knee
3: left ear      14: right elbow     26: right knee
4: right ear     15: left wrist      27: left ankle
5: left shoulder 16: right wrist     28: right ankle
...              ...                 ...
```

Each landmark has x, y, z coordinates + visibility score = 33 * 4 = 132 features per person.

For BJJ, you ideally want both grapplers' poses: 132 * 2 = 264 features. Much smaller than 4,096 pixel values, and much more meaningful.

### The Challenge: Two-Person Pose

MediaPipe BlazePose detects one person at a time. For two grapplers intertwined, it often:
- Detects only the more visible person
- Mixes landmarks between the two
- Fails when bodies overlap heavily

Strategies:
- Use the best detection available (even partial)
- Calculate relative features: distance between Person A's hip and Person B's shoulder
- Accept that some frames won't have clean two-person poses

### Feature Engineering

Raw landmarks are useful, but derived features can be even better:

| Feature | What It Captures |
|---------|-----------------|
| Hip-to-hip distance | How close/far the grapplers are |
| Torso angle (shoulder-to-hip) | Standing vs lying down |
| Knee angle | Guard position indicators |
| Relative height difference | Who's on top |
| Limb crossing patterns | Entanglement indicators |

### Expected Improvement

With skeleton features vs raw pixels:
- **Category-level**: ~75-85% (up from ~60-75%)
- **Position-level**: ~50-65% (up from ~35-50%)

The biggest gains come from positions that look similar in pixels but differ in body geometry (e.g., half guard vs closed guard).

## Hands-on Exercise

1. Install MediaPipe: `pip install mediapipe`
2. Write a script that:
   - Loads a frame
   - Runs BlazePose
   - Extracts the 33 landmarks
   - Visualises them overlaid on the frame
3. Process your labelled dataset: extract poses for each frame
4. Retrain the Random Forest using pose features instead of pixels
5. Compare: confusion matrix side-by-side with Lesson 04

## Resources

- [MediaPipe Pose](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker) -- Official docs
- [MediaPipe Python Guide](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python) -- Python setup
- [Human Pose Estimation overview](https://paperswithcode.com/task/pose-estimation) -- Research landscape

## Journal

<!-- How did pose features change your accuracy? Which positions improved most? Where does pose estimation struggle? -->
