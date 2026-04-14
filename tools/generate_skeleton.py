#!/usr/bin/python3
"""
Generate analysis JSON skeleton from extracted frames.

Creates a JSON file with one entry per extracted frame, pre-populated
with timestamps. Fill in the position classifications manually or
with Claude Code vision.

Usage:
    python generate_skeleton.py assets/greig_v3/ --output assets/skeleton.json
    python generate_skeleton.py assets/greig_v3/ --output assets/skeleton.json --player-a "Greig" --player-b "Anthony"
"""

import json
import os
import re
import argparse
from pathlib import Path


def extract_timestamp(filename):
    """Extract timestamp in seconds from a frame filename like f_01_0s.jpg"""
    match = re.search(r'_(\d+)s\.jpg$', filename)
    if match:
        return int(match.group(1))
    return None


def format_ts(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}"


def main():
    parser = argparse.ArgumentParser(description="Generate analysis skeleton from frames")
    parser.add_argument("frames_dir", help="Directory containing extracted frames")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--player-a", default="Player A", help="Player A name")
    parser.add_argument("--player-b", default="Player B", help="Player B name")
    args = parser.parse_args()

    frames_dir = args.frames_dir
    if not os.path.isdir(frames_dir):
        print(f"Error: {frames_dir} is not a directory")
        return

    # Collect frames and timestamps
    frames = []
    for f in sorted(os.listdir(frames_dir)):
        if not f.endswith('.jpg'):
            continue
        ts = extract_timestamp(f)
        if ts is not None:
            frames.append({"filename": f, "timestamp_sec": ts})

    if not frames:
        print("No frames found with timestamp pattern (*_Ns.jpg)")
        return

    print(f"Found {len(frames)} frames in {frames_dir}")
    print(f"Time range: {format_ts(frames[0]['timestamp_sec'])} to {format_ts(frames[-1]['timestamp_sec'])}")

    # Calculate interval
    if len(frames) > 1:
        intervals = [frames[i+1]['timestamp_sec'] - frames[i]['timestamp_sec'] for i in range(len(frames)-1)]
        avg_interval = sum(intervals) / len(intervals)
        print(f"Average interval: {avg_interval:.1f}s")

    # Generate skeleton
    timeline = []
    for frame in frames:
        ts = frame["timestamp_sec"]
        entry = {
            "timestamp": format_ts(ts),
            "timestamp_sec": ts,
            "event": None,
            "player_a_position": "unclear",
            "player_b_position": "unclear",
            "confidence": 0.0,
            "visual_reasoning": "",
            "active_technique": None,
            "notes": f"TODO: Analyse {frame['filename']}",
            "coaching_tip": None,
            "frame_file": frame["filename"],
        }
        timeline.append(entry)

    data = {
        "player_a": args.player_a,
        "player_b": args.player_b,
        "frames_dir": frames_dir,
        "total_frames": len(frames),
        "timeline": timeline,
        "summary": {
            "session_overview": "TODO",
            "key_moments": [],
            "top_3_improvements": ["TODO", "TODO", "TODO"],
            "strengths_observed": ["TODO", "TODO"],
            "guard_retention_score": 0,
            "guard_retention_reason": "TODO",
            "positional_awareness_score": 0,
            "positional_awareness_reason": "TODO",
            "transition_quality_score": 0,
            "transition_quality_reason": "TODO",
            "overall_notes": "TODO"
        }
    }

    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\nSkeleton saved to: {args.output}")
    print(f"  {len(timeline)} entries — every frame has a slot")
    print(f"  All positions set to 'unclear' — fill in classifications")
    print(f"  Run: python validate_analysis.py {args.output} --frames-dir {frames_dir} --interval {int(avg_interval)}")


if __name__ == "__main__":
    main()
