#!/usr/bin/python3
"""
BJJ Pose Analyser — Free, Local Proof of Concept
==================================================
Uses MediaPipe BlazePose to extract skeleton data from rolling footage
and classify BJJ positions from body geometry. No API key needed.

Usage:
    python pose_analyser.py path/to/video.mp4
    python pose_analyser.py path/to/video.mp4 --player-name Greig --interval 3
    python pose_analyser.py path/to/video.mp4 --visualise  # Save annotated frames

Requirements:
    pip install mediapipe opencv-python
    ffmpeg must be installed
"""

import cv2
import mediapipe as mp
import numpy as np
import json
import os
import sys
import argparse
import time
from pathlib import Path
from datetime import timedelta
from collections import Counter


# ─── Pose Landmarks ──────────────────────────────────────────────────────────
# MediaPipe BlazePose landmark indices
NOSE = 0
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16


def get_landmark_coords(landmarks, idx):
    """Extract x, y, z, visibility from a landmark."""
    lm = landmarks[idx]
    return np.array([lm.x, lm.y, lm.z]), lm.visibility


def angle_between(a, b, c):
    """Calculate angle at point b given three points a, b, c."""
    ba = a - b
    bc = c - b
    cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
    return np.degrees(np.arccos(np.clip(cosine, -1, 1)))


def midpoint(a, b):
    """Midpoint between two coordinate arrays."""
    return (a + b) / 2


# ─── Position Classification (Rule-Based) ────────────────────────────────────

def classify_position(landmarks):
    """
    Classify BJJ position from a single person's skeleton.

    This is a rule-based classifier using body geometry:
    - Torso angle (standing vs on ground)
    - Hip-knee-ankle angles (guard indicators)
    - Relative heights of body parts
    - Limb positions

    Returns (position_name, category, confidence, details)
    """
    # Extract key landmarks
    l_shoulder, l_shoulder_vis = get_landmark_coords(landmarks, LEFT_SHOULDER)
    r_shoulder, r_shoulder_vis = get_landmark_coords(landmarks, RIGHT_SHOULDER)
    l_hip, l_hip_vis = get_landmark_coords(landmarks, LEFT_HIP)
    r_hip, r_hip_vis = get_landmark_coords(landmarks, RIGHT_HIP)
    l_knee, l_knee_vis = get_landmark_coords(landmarks, LEFT_KNEE)
    r_knee, r_knee_vis = get_landmark_coords(landmarks, RIGHT_KNEE)
    l_ankle, l_ankle_vis = get_landmark_coords(landmarks, LEFT_ANKLE)
    r_ankle, r_ankle_vis = get_landmark_coords(landmarks, RIGHT_ANKLE)
    nose, nose_vis = get_landmark_coords(landmarks, NOSE)
    l_elbow, _ = get_landmark_coords(landmarks, LEFT_ELBOW)
    r_elbow, _ = get_landmark_coords(landmarks, RIGHT_ELBOW)
    l_wrist, _ = get_landmark_coords(landmarks, LEFT_WRIST)
    r_wrist, _ = get_landmark_coords(landmarks, RIGHT_WRIST)

    # Check visibility — if key landmarks are occluded, lower confidence
    key_visibility = np.mean([
        l_shoulder_vis, r_shoulder_vis,
        l_hip_vis, r_hip_vis,
        l_knee_vis, r_knee_vis,
    ])

    if key_visibility < 0.3:
        return "Unclear", "scramble", 0.2, "Key landmarks not visible"

    # Derived measurements
    mid_shoulder = midpoint(l_shoulder, r_shoulder)
    mid_hip = midpoint(l_hip, r_hip)

    # Torso vector (hip to shoulder) — y-axis: 0=top, 1=bottom in MediaPipe
    torso_vector = mid_shoulder - mid_hip
    torso_angle_from_vertical = np.degrees(
        np.arctan2(abs(torso_vector[0]), -torso_vector[1])
    )

    # Height spread: how much vertical space does the body occupy?
    all_y = [nose[1], l_shoulder[1], r_shoulder[1], l_hip[1], r_hip[1],
             l_knee[1], r_knee[1], l_ankle[1], r_ankle[1]]
    height_spread = max(all_y) - min(all_y)

    # Knee angles
    l_knee_angle = angle_between(l_hip, l_knee, l_ankle)
    r_knee_angle = angle_between(r_hip, r_knee, r_ankle)
    avg_knee_angle = (l_knee_angle + r_knee_angle) / 2

    # Hip angles (torso-to-thigh)
    l_hip_angle = angle_between(l_shoulder, l_hip, l_knee)
    r_hip_angle = angle_between(r_shoulder, r_hip, r_knee)

    # Is the person roughly upright?
    is_standing = torso_angle_from_vertical < 30 and height_spread > 0.45

    # Is the person roughly horizontal/on the ground?
    is_on_ground = torso_angle_from_vertical > 55 or height_spread < 0.35

    # Are hips higher than shoulders? (inverted / turtle)
    hips_above_shoulders = mid_hip[1] < mid_shoulder[1]

    # Are knees drawn up? (guard indicator)
    knees_drawn = avg_knee_angle < 110

    # Are legs extended?
    legs_extended = avg_knee_angle > 150

    # Elbow position relative to body
    elbows_tight = (
        abs(l_elbow[0] - l_shoulder[0]) < 0.1 and
        abs(r_elbow[0] - r_shoulder[0]) < 0.1
    )

    # ─── Classification rules ─────────────────────────────────

    # Standing
    if is_standing:
        if elbows_tight and avg_knee_angle > 140:
            return "Standing - Neutral", "standing", 0.8, \
                f"Upright (torso {torso_angle_from_vertical:.0f}deg), legs straight"
        else:
            return "Standing - Engaged", "standing", 0.7, \
                f"Upright (torso {torso_angle_from_vertical:.0f}deg), active stance"

    # Turtle (hips up, head down)
    if hips_above_shoulders and is_on_ground:
        return "Turtle", "scramble", 0.6, \
            "Hips above shoulders, compact position"

    # On ground with knees drawn up — guard position
    if is_on_ground and knees_drawn:
        # Try to distinguish guard types by hip angle
        if min(l_hip_angle, r_hip_angle) < 60:
            return "Closed Guard", "guard_bottom", 0.6, \
                f"On ground, knees drawn (avg {avg_knee_angle:.0f}deg), tight hip angle"
        elif min(l_knee_angle, r_knee_angle) < 80:
            return "Half Guard", "guard_bottom", 0.55, \
                f"On ground, one knee very bent ({min(l_knee_angle, r_knee_angle):.0f}deg)"
        else:
            return "Open Guard", "guard_bottom", 0.5, \
                f"On ground, knees drawn ({avg_knee_angle:.0f}deg)"

    # On ground, legs extended, torso flat — likely bottom position
    if is_on_ground and legs_extended:
        if torso_angle_from_vertical > 70:
            return "Bottom Position (flat)", "inferior_bottom", 0.5, \
                f"Flat on ground, legs extended, torso angle {torso_angle_from_vertical:.0f}deg"
        else:
            return "Side Control / Mount", "dominant_top", 0.45, \
                f"On ground, extended, moderate torso angle {torso_angle_from_vertical:.0f}deg"

    # Crouched / kneeling — intermediate position
    if not is_standing and not is_on_ground:
        if knees_drawn:
            return "Kneeling / Base", "guard_top", 0.5, \
                f"Intermediate height, knees bent ({avg_knee_angle:.0f}deg)"
        else:
            return "Scramble", "scramble", 0.4, \
                f"Intermediate position, torso {torso_angle_from_vertical:.0f}deg"

    # Fallback
    return "Unclear", "scramble", 0.3, \
        f"Could not determine (torso {torso_angle_from_vertical:.0f}deg, knees {avg_knee_angle:.0f}deg)"


# ─── Category Colours ────────────────────────────────────────────────────────

CATEGORY_COLOURS = {
    "standing": (139, 143, 163),      # grey
    "guard_bottom": (74, 144, 217),    # blue
    "guard_top": (212, 168, 67),       # gold
    "dominant_top": (52, 199, 89),     # green
    "inferior_bottom": (232, 93, 74),  # red
    "scramble": (175, 82, 222),        # purple
}


# ─── Video Processing ────────────────────────────────────────────────────────

def process_video(video_path, interval=2.0, max_frames=150, visualise=False, output_dir=None):
    """
    Process a video with MediaPipe pose estimation.
    Returns timeline of position classifications.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video {video_path}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    frame_skip = int(fps * interval)

    print(f"  Video: {fps:.1f} FPS, {total_frames} frames, {duration:.0f}s duration")
    print(f"  Sampling every {interval}s ({frame_skip} frames)")

    # Limit frames
    expected_samples = int(duration / interval)
    if expected_samples > max_frames:
        interval = duration / max_frames
        frame_skip = int(fps * interval)
        print(f"  Adjusted to {interval:.1f}s interval to stay under {max_frames} frames")

    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    if visualise and output_dir:
        os.makedirs(output_dir, exist_ok=True)

    timeline = []
    frame_idx = 0
    sample_count = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_skip == 0 and sample_count < max_frames:
            timestamp = frame_idx / fps
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)

            entry = {
                "frame_number": sample_count + 1,
                "timestamp_sec": round(timestamp, 1),
            }

            if results.pose_landmarks:
                position, category, confidence, details = classify_position(
                    results.pose_landmarks.landmark
                )
                entry["position"] = position
                entry["category"] = category
                entry["confidence"] = round(confidence, 2)
                entry["details"] = details

                # Extract key angles for the dataset
                landmarks = results.pose_landmarks.landmark
                l_hip, _ = get_landmark_coords(landmarks, LEFT_HIP)
                r_hip, _ = get_landmark_coords(landmarks, RIGHT_HIP)
                l_knee, _ = get_landmark_coords(landmarks, LEFT_KNEE)
                r_knee, _ = get_landmark_coords(landmarks, RIGHT_KNEE)
                l_ankle, _ = get_landmark_coords(landmarks, LEFT_ANKLE)
                r_ankle, _ = get_landmark_coords(landmarks, RIGHT_ANKLE)

                entry["landmarks_detected"] = True
                entry["left_knee_angle"] = round(angle_between(l_hip, l_knee, l_ankle), 1)
                entry["right_knee_angle"] = round(angle_between(r_hip, r_knee, r_ankle), 1)
            else:
                entry["position"] = "No Pose Detected"
                entry["category"] = "scramble"
                entry["confidence"] = 0.0
                entry["details"] = "MediaPipe could not detect a pose in this frame"
                entry["landmarks_detected"] = False

            timeline.append(entry)

            # Visualise
            if visualise and output_dir and results.pose_landmarks:
                annotated = frame.copy()
                mp.solutions.drawing_utils.draw_landmarks(
                    annotated,
                    results.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS,
                    mp.solutions.drawing_utils.DrawingSpec(
                        color=(0, 255, 0), thickness=2, circle_radius=3
                    ),
                    mp.solutions.drawing_utils.DrawingSpec(
                        color=(255, 255, 255), thickness=2
                    ),
                )
                # Add label
                colour = CATEGORY_COLOURS.get(entry["category"], (200, 200, 200))
                cv2.putText(
                    annotated,
                    f"{entry['position']} ({entry['confidence']:.0%})",
                    (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2,
                )
                ts_str = str(timedelta(seconds=int(timestamp)))
                cv2.putText(
                    annotated, ts_str,
                    (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2,
                )
                out_path = os.path.join(output_dir, f"frame_{sample_count+1:04d}.jpg")
                cv2.imwrite(out_path, annotated)

            mins = int(timestamp // 60)
            secs = int(timestamp % 60)
            status = entry["position"] if entry["landmarks_detected"] else "No pose"
            print(f"  {mins}:{secs:02d} — {status} ({entry['confidence']:.0%})")

            sample_count += 1

        frame_idx += 1

    cap.release()
    pose.close()

    return timeline, duration


# ─── Report Generation ────────────────────────────────────────────────────────

def generate_markdown_report(timeline, duration, player_name, video_path, output_path):
    """Generate an Obsidian markdown report from pose analysis."""
    today = time.strftime("%Y-%m-%d")
    dur_str = str(timedelta(seconds=int(duration)))

    # Position stats
    positions = [e["position"] for e in timeline if e["landmarks_detected"]]
    position_counts = Counter(positions)
    total_detected = len(positions)

    # Category stats
    categories = [e["category"] for e in timeline if e["landmarks_detected"]]
    category_counts = Counter(categories)

    # Average confidence
    confidences = [e["confidence"] for e in timeline if e["landmarks_detected"]]
    avg_confidence = np.mean(confidences) if confidences else 0

    # Detection rate
    detection_rate = sum(1 for e in timeline if e["landmarks_detected"]) / len(timeline) if timeline else 0

    category_labels = {
        "standing": "Standing",
        "guard_bottom": "Guard (Bottom)",
        "guard_top": "Inside Guard (Top)",
        "dominant_top": "Dominant (Top)",
        "inferior_bottom": "Inferior (Bottom)",
        "scramble": "Scramble / Transition",
    }

    lines = [
        "---",
        f"date: {today}",
        f"partner: ",
        f'duration: "{dur_str}"',
        f"frames_analysed: {len(timeline)}",
        f"poses_detected: {total_detected}",
        f"detection_rate: {detection_rate:.0%}",
        f"avg_confidence: {avg_confidence:.2f}",
        f"method: mediapipe-pose",
        "tags: [roll, pose-analysis]",
        "---",
        "",
        f"# Pose Analysis - {today}",
        "",
        f"**Source:** {os.path.basename(video_path)}",
        f"**Duration:** {dur_str}",
        f"**Frames analysed:** {len(timeline)}",
        f"**Poses detected:** {total_detected}/{len(timeline)} ({detection_rate:.0%})",
        f"**Average confidence:** {avg_confidence:.0%}",
        f"**Method:** MediaPipe BlazePose (free, local)",
        "",
        "## Position Breakdown",
        "",
        "| Position | Count | % of Roll |",
        "|----------|-------|-----------|",
    ]

    for pos, count in position_counts.most_common():
        pct = count / total_detected * 100 if total_detected else 0
        lines.append(f"| {pos} | {count} | {pct:.0f}% |")

    lines.extend([
        "",
        "## Category Breakdown",
        "",
        "| Category | Count | % of Roll |",
        "|----------|-------|-----------|",
    ])

    for cat, count in category_counts.most_common():
        pct = count / total_detected * 100 if total_detected else 0
        label = category_labels.get(cat, cat)
        lines.append(f"| {label} | {count} | {pct:.0f}% |")

    lines.extend([
        "",
        "## Frame-by-Frame Timeline",
        "",
        "| Time | Position | Confidence | Details |",
        "|------|----------|------------|---------|",
    ])

    for entry in timeline:
        ts = entry["timestamp_sec"]
        mins = int(ts // 60)
        secs = int(ts % 60)
        pos = entry["position"]
        conf = f"{entry['confidence']:.0%}"
        details = entry.get("details", "")
        lines.append(f"| {mins}:{secs:02d} | {pos} | {conf} | {details} |")

    lines.extend([
        "",
        "## Notes",
        "",
        "This analysis was generated using **MediaPipe BlazePose** — a free, local",
        "pose estimation model. It classifies positions from skeleton geometry",
        "(body angles, relative positions) without any API calls.",
        "",
        "**Limitations:**",
        "- Single-person pose detection (may mix up two grapplers)",
        "- Rule-based classification (not ML-trained yet)",
        "- Lower accuracy than vision-LLM analysis",
        "",
        "**Next steps:**",
        "- Review classifications and correct any mistakes",
        "- Use this labelled data to train a proper ML classifier ([[04 - Training a Position Classifier]])",
        "- Compare with Claude Vision API analysis when budget allows",
        "",
    ])

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return output_path


def generate_training_csv(timeline, output_path):
    """Export timeline as CSV for ML training."""
    lines = ["frame_number,timestamp_sec,position,category,confidence,left_knee_angle,right_knee_angle"]
    for entry in timeline:
        if entry["landmarks_detected"]:
            lines.append(
                f"{entry['frame_number']},"
                f"{entry['timestamp_sec']},"
                f"{entry['position']},"
                f"{entry['category']},"
                f"{entry['confidence']},"
                f"{entry.get('left_knee_angle', '')},"
                f"{entry.get('right_knee_angle', '')}"
            )
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    return output_path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="BJJ Pose Analyser — Free local analysis with MediaPipe"
    )
    parser.add_argument("video", help="Path to rolling video file")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Seconds between samples (default: 2)")
    parser.add_argument("--player-name", default="Player A",
                        help="Name of the player to track")
    parser.add_argument("--max-frames", type=int, default=150,
                        help="Maximum frames to analyse (default: 150)")
    parser.add_argument("--visualise", action="store_true",
                        help="Save annotated frames with skeleton overlay")
    parser.add_argument("--output", default=None,
                        help="Output file path")
    parser.add_argument("--csv", action="store_true",
                        help="Also export training CSV")
    args = parser.parse_args()

    print("\n--- BJJ Pose Analyser (Free / Local) ---")
    print("=" * 45)
    print(f"Using MediaPipe BlazePose — no API key needed")

    if not os.path.exists(args.video):
        print(f"Error: Video not found: {args.video}")
        sys.exit(1)

    # Setup visualisation output
    vis_dir = None
    if args.visualise:
        vis_dir = str(Path(args.video).parent / f"{Path(args.video).stem}_poses")
        print(f"  Annotated frames will be saved to: {vis_dir}")

    # Process video
    print(f"\nAnalysing {args.video}...")
    timeline, duration = process_video(
        args.video, args.interval, args.max_frames,
        visualise=args.visualise, output_dir=vis_dir,
    )

    detected = sum(1 for e in timeline if e["landmarks_detected"])
    print(f"\nPoses detected: {detected}/{len(timeline)}")

    # Generate markdown report
    today = time.strftime("%Y-%m-%d")
    video_name = Path(args.video).stem
    roll_log_dir = Path(__file__).parent.parent / "Roll Log"
    roll_log_dir.mkdir(exist_ok=True)
    md_path = args.output or str(roll_log_dir / f"{today} - {video_name} (pose).md")

    generate_markdown_report(timeline, duration, args.player_name, args.video, md_path)
    print(f"Report saved to: {md_path}")

    # Export CSV for training
    if args.csv:
        csv_path = str(Path(args.video).parent / f"{video_name}_training.csv")
        generate_training_csv(timeline, csv_path)
        print(f"Training CSV saved to: {csv_path}")

    if args.visualise:
        print(f"Annotated frames saved to: {vis_dir}/")

    # Quick stats
    positions = [e["position"] for e in timeline if e["landmarks_detected"]]
    if positions:
        most_common = Counter(positions).most_common(3)
        print(f"\nTop positions detected:")
        for pos, count in most_common:
            print(f"  {pos}: {count} frames")

    print(f"\nDone! Open the report in Obsidian: Roll Log/")


if __name__ == "__main__":
    main()
