#!/usr/bin/python3
"""
Validate BJJ analysis JSON for gaps, missing frames, and consistency.

Usage:
    python validate_analysis.py analysis.json --frames-dir assets/greig_v3/
    python validate_analysis.py analysis.json --interval 3
"""

import json
import sys
import os
import argparse
from pathlib import Path


def validate(analysis_path, frames_dir=None, expected_interval=None):
    with open(analysis_path) as f:
        data = json.load(f)

    timeline = data.get("timeline", [])
    if not timeline:
        print("ERROR: No timeline data found.")
        return False

    issues = []
    warnings = []

    # 1. Check for timestamp gaps
    timestamps = [e.get("timestamp_sec", 0) for e in timeline]
    timestamps_sorted = sorted(timestamps)

    if expected_interval:
        for i in range(1, len(timestamps_sorted)):
            gap = timestamps_sorted[i] - timestamps_sorted[i-1]
            if gap > expected_interval * 2:
                ts1 = f"{int(timestamps_sorted[i-1]//60)}:{int(timestamps_sorted[i-1]%60):02d}"
                ts2 = f"{int(timestamps_sorted[i]//60)}:{int(timestamps_sorted[i]%60):02d}"
                issues.append(f"GAP: {gap:.0f}s gap between {ts1} and {ts2} (expected max {expected_interval*2}s)")

    # 2. Check extracted frames vs timeline entries
    if frames_dir and os.path.isdir(frames_dir):
        frame_files = sorted([f for f in os.listdir(frames_dir) if f.endswith('.jpg')])
        frame_count = len(frame_files)
        timeline_count = len(timeline)

        if timeline_count < frame_count * 0.8:
            issues.append(f"MISSING FRAMES: {timeline_count} timeline entries but {frame_count} frames extracted ({frame_count - timeline_count} missing)")

        # Extract timestamps from filenames
        frame_timestamps = []
        for f in frame_files:
            parts = f.replace('.jpg', '').split('_')
            for p in parts:
                if p.endswith('s'):
                    try:
                        frame_timestamps.append(int(p[:-1]))
                    except ValueError:
                        pass

        # Find frames not in timeline
        timeline_ts_set = set(int(t) for t in timestamps)
        missing = []
        for ft in frame_timestamps:
            # Allow 1 second tolerance
            if not any(abs(ft - tt) <= 1 for tt in timeline_ts_set):
                mins = ft // 60
                secs = ft % 60
                missing.append(f"{mins}:{secs:02d}")

        if missing:
            issues.append(f"UNANALYSED FRAMES: {len(missing)} frames extracted but not in timeline: {', '.join(missing[:10])}")
            if len(missing) > 10:
                issues[-1] += f" ... and {len(missing) - 10} more"

    # 3. Check for required fields
    required_fields = ["timestamp_sec", "player_a_position", "player_b_position"]
    for i, entry in enumerate(timeline):
        for field in required_fields:
            if field not in entry or entry[field] is None:
                ts = entry.get("timestamp", f"entry_{i}")
                warnings.append(f"MISSING FIELD: {field} at {ts}")

    # 4. Check for events
    has_slap = any(e.get("event") == "slap_bump" for e in timeline)
    has_tap = any(e.get("event") == "tap" for e in timeline)
    if not has_slap:
        warnings.append("NO SLAP/BUMP: Roll start event not detected. Check the first few frames.")
    if not has_tap:
        warnings.append("NO TAP: No submission event detected. Was this a time-based round?")

    # 5. Check position validity
    taxonomy_path = Path(__file__).parent / "taxonomy.json"
    if taxonomy_path.exists():
        with open(taxonomy_path) as f:
            taxonomy = json.load(f)
        valid_ids = set(p["id"] for p in taxonomy["positions"])
        for entry in timeline:
            for field in ["player_a_position", "player_b_position"]:
                pos = entry.get(field, "")
                if pos and pos not in valid_ids:
                    ts = entry.get("timestamp", "?")
                    warnings.append(f"INVALID POSITION: '{pos}' at {ts} not in taxonomy")

    # 6. Summary
    print(f"\n{'='*50}")
    print(f"VALIDATION: {analysis_path}")
    print(f"{'='*50}")
    print(f"Timeline entries: {len(timeline)}")
    print(f"Time range: {timestamps_sorted[0]:.0f}s to {timestamps_sorted[-1]:.0f}s")
    if frames_dir:
        print(f"Extracted frames: {len(frame_files) if os.path.isdir(frames_dir) else 'N/A'}")

    if not issues and not warnings:
        print(f"\n  PASSED — No issues found.")
        return True

    if issues:
        print(f"\n  ERRORS ({len(issues)}):")
        for issue in issues:
            print(f"    {issue}")

    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for w in warnings[:15]:
            print(f"    {w}")
        if len(warnings) > 15:
            print(f"    ... and {len(warnings) - 15} more")

    return len(issues) == 0


def main():
    parser = argparse.ArgumentParser(description="Validate BJJ analysis JSON")
    parser.add_argument("input", help="Path to analysis JSON file")
    parser.add_argument("--frames-dir", default=None, help="Directory of extracted frames to check against")
    parser.add_argument("--interval", type=int, default=None, help="Expected interval between frames in seconds")
    args = parser.parse_args()

    passed = validate(args.input, args.frames_dir, args.interval)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
