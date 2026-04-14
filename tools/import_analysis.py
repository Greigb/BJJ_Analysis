#!/usr/bin/python3
"""
BJJ Analysis Importer — Convert AI Studio JSON to Obsidian Report
==================================================================
Takes a JSON analysis (from Claude Vision or any source) and generates
a full Obsidian report with position timeline, scores, and coaching feedback.

Usage:
    # From a JSON file
    python import_analysis.py analysis.json --player-name Greig

    # Paste JSON via stdin
    python import_analysis.py --stdin --player-name Greig

    # Specify video source name
    python import_analysis.py analysis.json --player-name Greig --video-name "Tuesday Open Mat"
"""

import json
import sys
import argparse
import time
from pathlib import Path
from collections import Counter


TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"


def format_timestamp(seconds):
    """Format seconds as m:ss string."""
    s = int(float(seconds))
    return f"{s // 60}:{s % 60:02d}"


def load_taxonomy():
    with open(TAXONOMY_PATH) as f:
        return json.load(f)


def make_timestamp_link(timestamp_str, timestamp_sec, video_url):
    """Create a clickable timestamp link if video URL is provided."""
    if not video_url:
        return f"**{timestamp_str}**"

    sec = int(timestamp_sec)
    if "youtube.com" in video_url or "youtu.be" in video_url:
        # Extract video ID and build timestamp URL
        if "youtu.be/" in video_url:
            vid_id = video_url.split("youtu.be/")[1].split("?")[0]
        elif "v=" in video_url:
            vid_id = video_url.split("v=")[1].split("&")[0]
        else:
            return f"**{timestamp_str}**"
        return f"[**{timestamp_str}**](https://www.youtube.com/watch?v={vid_id}&t={sec}s)"
    else:
        # Generic URL with no timestamp support
        return f"[**{timestamp_str}**]({video_url})"


def generate_report(data, player_name, video_name, output_path, video_url=None):
    """Generate an Obsidian markdown report from analysis JSON."""
    taxonomy = load_taxonomy()
    pos_map = {p["id"]: p for p in taxonomy["positions"]}
    cat_map = taxonomy["categories"]

    timeline = data.get("timeline", [])
    summary = data.get("summary", {})
    today = time.strftime("%Y-%m-%d")

    # Calculate duration from timeline
    if timeline:
        last_ts = max(e.get("timestamp_sec", 0) for e in timeline)
        duration_str = f"{int(last_ts // 60)}:{int(last_ts % 60):02d}"
    else:
        duration_str = "unknown"

    # Position stats
    positions_a = [e.get("player_a_position", "unclear") for e in timeline]
    category_counts = Counter()
    for pos_id in positions_a:
        if pos_id in pos_map:
            cat_id = pos_map[pos_id]["category"]
            cat_label = cat_map.get(cat_id, {}).get("label", cat_id)
            category_counts[cat_label] += 1
        else:
            category_counts["Unknown"] += 1

    # Category colours for the visual bar
    cat_colours = {
        "Standing": "grey",
        "Guard (Bottom)": "blue",
        "Inside Guard (Top)": "gold",
        "Dominant Position (Top)": "green",
        "Inferior Position (Bottom)": "red",
        "Leg Entanglement": "orange",
        "Scramble / Transition": "purple",
    }

    lines = [
        "---",
        f"date: {today}",
        f"partner: ",
        f'duration: "{duration_str}"',
        f"frames_analysed: {len(timeline)}",
        f"guard_retention: {summary.get('guard_retention_score', '')}",
        f"positional_awareness: {summary.get('positional_awareness_score', '')}",
        f"transition_quality: {summary.get('transition_quality_score', '')}",
        f"method: claude-vision",
        f"tags: [roll, claude-analysis]",
        "---",
        "",
        f"# Roll Analysis - {video_name or today}",
        "",
        f"**Player:** {player_name}",
        f"**Duration:** {duration_str}",
        f"**Moments analysed:** {len(timeline)}",
        f"**Method:** Claude Vision",
    ]
    if video_url:
        lines.append(f"**Video:** [{video_url}]({video_url})")

    # Detect roll start/end events
    roll_start = None
    roll_end = None
    resets = []
    for entry in timeline:
        event = entry.get("event")
        ts_sec = entry.get("timestamp_sec", 0)
        if event == "slap_bump" and roll_start is None:
            roll_start = ts_sec
        elif event == "tap":
            roll_end = ts_sec
        elif event == "reset":
            resets.append(ts_sec)

    if roll_start is not None:
        lines.append(f"**Roll starts:** {format_timestamp(roll_start)}")
    if roll_end is not None:
        lines.append(f"**Roll ends:** {format_timestamp(roll_end)} (tap)")
    if roll_start is not None and roll_end is not None:
        actual_duration = roll_end - roll_start
        lines.append(f"**Actual roll time:** {format_timestamp(actual_duration)}")
    if resets:
        lines.append(f"**Resets:** {', '.join(format_timestamp(r) for r in resets)}")

    lines.append("")

    # Summary
    if summary.get("session_overview"):
        lines.extend([
            "## Summary",
            "",
            summary["session_overview"],
            "",
        ])

    # Scores
    lines.extend([
        "## Scores",
        "",
        "| Metric | Score |",
        "|--------|-------|",
        f"| Guard Retention | {summary.get('guard_retention_score', '-')}/10 |",
        f"| Positional Awareness | {summary.get('positional_awareness_score', '-')}/10 |",
        f"| Transition Quality | {summary.get('transition_quality_score', '-')}/10 |",
        "",
    ])

    # Position distribution
    lines.extend([
        "## Position Distribution",
        "",
        "| Category | Count | % |",
        "|----------|-------|---|",
    ])
    total = sum(category_counts.values())
    for cat_label, count in category_counts.most_common():
        pct = count / total * 100 if total else 0
        lines.append(f"| {cat_label} | {count} | {pct:.0f}% |")
    lines.append("")

    # Visual position bar
    lines.append("### Position Timeline Bar")
    lines.append("")
    bar_chars = {
        "Standing": "⬜",
        "Guard (Bottom)": "🟦",
        "Inside Guard (Top)": "🟨",
        "Dominant Position (Top)": "🟩",
        "Inferior Position (Bottom)": "🟥",
        "Leg Entanglement": "🟧",
        "Scramble / Transition": "🟪",
    }
    bar = ""
    for pos_id in positions_a:
        if pos_id in pos_map:
            cat_id = pos_map[pos_id]["category"]
            cat_label = cat_map.get(cat_id, {}).get("label", "")
            bar += bar_chars.get(cat_label, "⬛")
        else:
            bar += "⬛"
    lines.append(bar)
    lines.append("")
    lines.append("Legend: ⬜Standing 🟦Guard(Bottom) 🟨Guard(Top) 🟩Dominant(Top) 🟥Inferior(Bottom) 🟧Leg Entanglement 🟪Scramble")
    lines.append("")

    # Key moments
    if summary.get("key_moments"):
        lines.append("## Key Moments")
        lines.append("")
        for km in summary["key_moments"]:
            ts = km.get("timestamp", "?")
            # Parse timestamp to seconds for link
            parts = ts.replace("?", "0").split(":")
            ts_sec = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0
            ts_link = make_timestamp_link(ts, ts_sec, video_url)
            desc = km.get("description", "")
            assessment = km.get("assessment", "neutral")
            suggestion = km.get("suggestion", "")
            lines.append(f"- {ts_link} [{assessment}] - {desc}")
            if suggestion:
                lines.append(f"  - *Suggestion:* {suggestion}")
        lines.append("")

    # Improvements
    if summary.get("top_3_improvements"):
        lines.append("## Top Improvements")
        lines.append("")
        for i, imp in enumerate(summary["top_3_improvements"], 1):
            lines.append(f"{i}. {imp}")
        lines.append("")

    # Strengths
    if summary.get("strengths_observed"):
        lines.append("## Strengths Observed")
        lines.append("")
        for s in summary["strengths_observed"]:
            lines.append(f"- {s}")
        lines.append("")

    # Full timeline table
    lines.extend([
        "## Position Timeline",
        "",
        "| Time | Player A | Player B | Technique | Notes |",
        "|------|----------|----------|-----------|-------|",
    ])
    for entry in timeline:
        ts = entry.get("timestamp", "?")
        ts_sec = entry.get("timestamp_sec", 0)
        ts_link = make_timestamp_link(ts, ts_sec, video_url)
        pos_a_id = entry.get("player_a_position", "unclear")
        pos_b_id = entry.get("player_b_position", "unclear")
        pos_a = pos_map.get(pos_a_id, {}).get("name", pos_a_id)
        pos_b = pos_map.get(pos_b_id, {}).get("name", pos_b_id)
        tech = entry.get("active_technique") or ""
        notes = entry.get("notes", "")
        tip = entry.get("coaching_tip") or ""
        event = entry.get("event")
        note_text = notes
        if event == "slap_bump":
            note_text = "**ROLL START (slap/bump)** " + note_text
        elif event == "tap":
            note_text = "**TAP (submission)** " + note_text
        elif event == "reset":
            note_text = "**RESET** " + note_text
        if tip:
            note_text += f" *Tip: {tip}*"
        lines.append(f"| {ts_link} | [[{pos_a}]] | [[{pos_b}]] | {tech} | {note_text} |")
    lines.append("")

    # Overall notes
    if summary.get("overall_notes"):
        lines.extend([
            "## Overall Notes",
            "",
            summary["overall_notes"],
            "",
        ])

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Import BJJ analysis JSON into an Obsidian report"
    )
    parser.add_argument("input", nargs="?", help="Path to JSON file")
    parser.add_argument("--stdin", action="store_true",
                        help="Read JSON from stdin")
    parser.add_argument("--player-name", default="Player A",
                        help="Name of the player being analysed")
    parser.add_argument("--video-name", default=None,
                        help="Name/description of the video")
    parser.add_argument("--output", default=None,
                        help="Output file path")
    parser.add_argument("--video-url", default=None,
                        help="YouTube or video URL (timestamps become clickable links)")
    args = parser.parse_args()

    if args.stdin:
        print("Paste your JSON below (then press Ctrl+D when done):")
        raw = sys.stdin.read()
    elif args.input:
        with open(args.input) as f:
            raw = f.read()
    else:
        print("Error: provide a JSON file path or use --stdin")
        sys.exit(1)

    # Clean up markdown fences if pasted from AI Studio
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        print(f"First 200 chars: {raw[:200]}")
        sys.exit(1)

    today = time.strftime("%Y-%m-%d")
    video_label = args.video_name or "AI Studio Analysis"
    roll_log_dir = Path(__file__).parent.parent / "Roll Log"
    roll_log_dir.mkdir(exist_ok=True)
    out_path = args.output or str(roll_log_dir / f"{today} - {video_label}.md")

    report_path = generate_report(data, args.player_name, video_label, out_path, args.video_url)

    print(f"Report saved to: {report_path}")
    print(f"Open in Obsidian: Roll Log/")


if __name__ == "__main__":
    main()
