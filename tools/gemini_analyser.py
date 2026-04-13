#!/usr/bin/python3
"""
BJJ Gemini Analyser — Free Vision API Analysis
================================================
Uses Google Gemini's free tier to analyse BJJ rolling footage.
Same pipeline as analyse_roll.py but zero cost.

Usage:
    python gemini_analyser.py path/to/video.mp4
    python gemini_analyser.py path/to/video.mp4 --player-name Greig --interval 3

Requirements:
    pip install google-genai opencv-python Pillow
    export GEMINI_API_KEY='your-key-here'  (free from https://aistudio.google.com/apikey)
"""

import cv2
import json
import os
import sys
import argparse
import time
import base64
from pathlib import Path
from datetime import timedelta
from collections import Counter
from io import BytesIO

from google import genai
from google.genai import types
from PIL import Image


# ─── Configuration ────────────────────────────────────────────────────────────

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"

SYSTEM_PROMPT = """You are an expert Brazilian Jiu-Jitsu analyst with black belt-level knowledge.
You are analysing keyframes extracted from a rolling/sparring session.

POSITION TAXONOMY — use ONLY these position IDs:
{taxonomy_positions}

For EACH frame image provided, return a JSON object (no markdown, no backticks, just raw JSON):
{{
  "frame_number": <int>,
  "timestamp_sec": <float>,
  "player_a_position": "<position_id from taxonomy>",
  "player_b_position": "<position_id from taxonomy>",
  "confidence": <float 0.0-1.0>,
  "active_technique": "<technique being attempted or null>",
  "notes": "<brief observation about what's happening>",
  "coaching_tip": "<one actionable suggestion if relevant, or null>"
}}

Guidelines:
- Player A = the person identified as the focus (you'll be told who to track)
- Player B = their training partner
- If positions are complementary (e.g. A has mount, B has bottom mount), label both
- If the frame is blurry, transitional, or unclear, use "scramble_generic" or "unclear"
- Be specific about techniques: name the exact sweep, submission, or pass attempt
- Coaching tips should be actionable: "create a frame with your forearm" not "improve defence"
"""

BATCH_PROMPT = """Analyse these {count} sequential frames from a BJJ rolling session.
The frames are {interval} seconds apart, starting at timestamp {start_time}s.

Player A (the person we're tracking): {player_name}
Context from previous frames: {context}

Return a JSON array with one object per frame, in order.
Return ONLY valid JSON array, no markdown formatting, no backticks, no explanation outside the JSON."""

SUMMARY_PROMPT = """You are a BJJ black belt coach reviewing a complete rolling session analysis.

Here is the timestamped position data from the session:
{timeline_json}

The session was {duration} long.
Player being coached: {player_name}

Provide a coaching summary as a JSON object:
{{
  "session_overview": "<2-3 sentence summary of the roll>",
  "position_time_breakdown": {{
    "<category>": <seconds_spent>
  }},
  "dominant_time_pct": <float, percentage of time in dominant/guard positions vs inferior>,
  "key_moments": [
    {{
      "timestamp": "<mm:ss>",
      "description": "<what happened>",
      "assessment": "<good/bad/neutral>",
      "suggestion": "<what to do differently>"
    }}
  ],
  "top_3_improvements": [
    "<specific actionable improvement 1>",
    "<specific actionable improvement 2>",
    "<specific actionable improvement 3>"
  ],
  "strengths_observed": [
    "<strength 1>",
    "<strength 2>"
  ],
  "guard_retention_score": <1-10>,
  "positional_awareness_score": <1-10>,
  "transition_quality_score": <1-10>,
  "overall_notes": "<final coaching remarks>"
}}

Return ONLY valid JSON, no markdown, no backticks."""


# ─── Taxonomy ─────────────────────────────────────────────────────────────────

def load_taxonomy():
    with open(TAXONOMY_PATH) as f:
        return json.load(f)


def build_taxonomy_string(taxonomy):
    lines = []
    for pos in taxonomy["positions"]:
        cat = taxonomy["categories"][pos["category"]]["label"]
        lines.append(f'  "{pos["id"]}" — {pos["name"]} [{cat}]')
    return "\n".join(lines)


# ─── Frame Extraction ─────────────────────────────────────────────────────────

def extract_frames(video_path, interval=2.0, max_frames=150):
    """Extract frames from video using OpenCV."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video {video_path}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    frame_skip = int(fps * interval)

    expected = int(duration / interval)
    if expected > max_frames:
        interval = duration / max_frames
        frame_skip = int(fps * interval)
        print(f"  Adjusted to {interval:.1f}s interval to stay under {max_frames} frames")

    print(f"  Video: {fps:.1f} FPS, {duration:.0f}s, sampling every {interval:.1f}s")

    frames = []
    frame_idx = 0
    sample_count = 0

    while cap.isOpened() and sample_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_skip == 0:
            timestamp = frame_idx / fps
            # Resize for API efficiency
            h, w = frame.shape[:2]
            scale = min(1024 / w, 1024 / h, 1.0)
            if scale < 1.0:
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

            # Convert to PIL Image
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb)

            frames.append({
                "image": pil_image,
                "timestamp": timestamp,
                "frame_num": sample_count + 1,
            })
            sample_count += 1

        frame_idx += 1

    cap.release()
    print(f"  Extracted {len(frames)} frames")
    return frames, interval, duration


# ─── Gemini API ───────────────────────────────────────────────────────────────

def analyse_batch(client, frames, interval, player_name, context, taxonomy_str):
    """Send a batch of frames to Gemini for analysis."""

    # Build content parts
    parts = [
        BATCH_PROMPT.format(
            count=len(frames),
            interval=f"{interval:.1f}",
            start_time=f"{frames[0]['timestamp']:.1f}",
            player_name=player_name,
            context=context or "This is the start of the session.",
        )
    ]

    for frame in frames:
        parts.append(f"--- Frame {frame['frame_num']} (timestamp: {frame['timestamp']:.1f}s) ---")
        parts.append(frame["image"])

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(taxonomy_positions=taxonomy_str),
            max_output_tokens=4096,
            temperature=0.2,
        ),
    )

    raw_text = response.text.strip()

    # Strip markdown fences if present
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
        raw_text = raw_text.strip()

    try:
        results = json.loads(raw_text)
        if isinstance(results, dict):
            results = [results]
        return results
    except json.JSONDecodeError as e:
        print(f"  Warning: JSON parse error: {e}")
        print(f"  Raw (first 300 chars): {raw_text[:300]}")
        return []


def generate_summary(client, timeline, duration, player_name):
    """Generate coaching summary from timeline."""
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=SUMMARY_PROMPT.format(
            timeline_json=json.dumps(timeline, indent=2),
            duration=str(timedelta(seconds=int(duration))),
            player_name=player_name,
        ),
        config=types.GenerateContentConfig(
            max_output_tokens=4096,
            temperature=0.3,
        ),
    )

    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
        raw_text = raw_text.strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse summary", "raw": raw_text}


# ─── Markdown Report ──────────────────────────────────────────────────────────

def generate_markdown_report(timeline, summary, player_name, video_path, duration, output_path):
    """Generate Obsidian-compatible markdown report."""
    taxonomy = load_taxonomy()
    pos_map = {p["id"]: p for p in taxonomy["positions"]}

    dur_str = str(timedelta(seconds=int(duration)))
    today = time.strftime("%Y-%m-%d")

    lines = [
        "---",
        f"date: {today}",
        f"partner: ",
        f'duration: "{dur_str}"',
        f"frames_analysed: {len(timeline)}",
        f"guard_retention: {summary.get('guard_retention_score', '')}",
        f"positional_awareness: {summary.get('positional_awareness_score', '')}",
        f"transition_quality: {summary.get('transition_quality_score', '')}",
        f"method: gemini-vision-free",
        f"tags: [roll, gemini-analysis]",
        "---",
        "",
        f"# Roll Analysis - {today}",
        "",
        f"**Source:** {os.path.basename(video_path)}",
        f"**Duration:** {dur_str}",
        f"**Frames:** {len(timeline)}",
        f"**Method:** Gemini 2.0 Flash (free tier)",
        "",
        "## Summary",
        "",
        summary.get("session_overview", "Analysis complete."),
        "",
        "## Scores",
        "",
        "| Metric | Score |",
        "|--------|-------|",
        f"| Guard Retention | {summary.get('guard_retention_score', '-')}/10 |",
        f"| Positional Awareness | {summary.get('positional_awareness_score', '-')}/10 |",
        f"| Transition Quality | {summary.get('transition_quality_score', '-')}/10 |",
        "",
    ]

    # Key moments
    if summary.get("key_moments"):
        lines.append("## Key Moments")
        lines.append("")
        for km in summary["key_moments"]:
            ts = km.get("timestamp", "?")
            desc = km.get("description", "")
            assessment = km.get("assessment", "neutral")
            suggestion = km.get("suggestion", "")
            lines.append(f"- **{ts}** [{assessment}] - {desc}")
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

    # Position timeline
    lines.append("## Position Timeline")
    lines.append("")
    lines.append("| Time | Position | Technique | Notes |")
    lines.append("|------|----------|-----------|-------|")
    for entry in timeline:
        ts = entry.get("timestamp_sec", 0)
        mins = int(ts // 60)
        secs = int(ts % 60)
        pos_id = entry.get("player_a_position", "unclear")
        pos_info = pos_map.get(pos_id, {"name": pos_id})
        pos_name = pos_info.get("name", pos_id)
        tech = entry.get("active_technique") or ""
        notes = entry.get("notes", "")
        lines.append(f"| {mins}:{secs:02d} | [[{pos_name}]] | {tech} | {notes} |")
    lines.append("")

    # Overall notes
    if summary.get("overall_notes"):
        lines.append("## Overall Notes")
        lines.append("")
        lines.append(summary["overall_notes"])
        lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return output_path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="BJJ Gemini Analyser — Free vision API analysis"
    )
    parser.add_argument("video", help="Path to rolling video file")
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Seconds between keyframes (default: 3)")
    parser.add_argument("--player-name", default="Player A",
                        help="Name of the player to track")
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--batch-size", type=int, default=3,
                        help="Frames per API call (default: 3, keep low for free tier)")
    parser.add_argument("--max-frames", type=int, default=100,
                        help="Maximum frames to analyse (default: 100)")
    parser.add_argument("--json-only", action="store_true",
                        help="Output raw JSON instead of markdown")
    args = parser.parse_args()

    print("\n--- BJJ Gemini Analyser (Free Tier) ---")
    print("=" * 45)

    # Check API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set.")
        print("Get a free key at: https://aistudio.google.com/apikey")
        print("Then run: export GEMINI_API_KEY='your-key-here'")
        sys.exit(1)

    if not os.path.exists(args.video):
        print(f"Error: Video not found: {args.video}")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    taxonomy = load_taxonomy()
    taxonomy_str = build_taxonomy_string(taxonomy)

    # Step 1: Extract frames
    print(f"\nStep 1: Extracting frames from {args.video}")
    frames, interval, duration = extract_frames(
        args.video, args.interval, args.max_frames
    )

    # Step 2: Analyse in batches
    total_batches = (len(frames) + args.batch_size - 1) // args.batch_size
    print(f"\nStep 2: Analysing {len(frames)} frames ({total_batches} API calls)")
    print(f"  Free tier: 15 requests/min — this will take ~{total_batches * 5}s")

    timeline = []
    context = ""

    for batch_start in range(0, len(frames), args.batch_size):
        batch = frames[batch_start:batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1

        print(f"  Batch {batch_num}/{total_batches} "
              f"(frames {batch[0]['frame_num']}-{batch[-1]['frame_num']}, "
              f"{batch[0]['timestamp']:.0f}s-{batch[-1]['timestamp']:.0f}s)...",
              end=" ", flush=True)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                results = analyse_batch(
                    client, batch, interval, args.player_name, context, taxonomy_str
                )
                timeline.extend(results)
                print(f"OK ({len(results)} positions)")

                if results:
                    last = results[-1]
                    context = (
                        f"At {last.get('timestamp_sec', '?')}s: "
                        f"Player A in {last.get('player_a_position', '?')}, "
                        f"Player B in {last.get('player_b_position', '?')}. "
                        f"{last.get('notes', '')}"
                    )
                break
            except Exception as e:
                err_str = str(e)
                if "429" in err_str and attempt < max_retries - 1:
                    wait = 15 * (attempt + 1)
                    print(f"Rate limited, waiting {wait}s...", end=" ", flush=True)
                    time.sleep(wait)
                else:
                    print(f"Error: {e}")
                    break

        # Rate limit: stay well under 15 req/min for free tier
        if batch_start + args.batch_size < len(frames):
            time.sleep(8)

    print(f"\n  Analysed {len(timeline)} frames total")

    # Step 3: Summary
    print("\nStep 3: Generating coaching summary...")
    summary = generate_summary(client, timeline, duration, args.player_name)

    if "error" not in summary:
        print("  Summary generated")
    else:
        print(f"  Summary had issues: {summary.get('error', '')}")

    # Step 4: Output
    if args.json_only:
        output = {
            "video": args.video,
            "player": args.player_name,
            "duration_sec": duration,
            "frame_interval_sec": interval,
            "timeline": timeline,
            "summary": summary,
        }
        out_path = args.output or str(Path(args.video).stem) + "_gemini.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nJSON saved to: {out_path}")
    else:
        today = time.strftime("%Y-%m-%d")
        video_name = Path(args.video).stem
        roll_log_dir = Path(__file__).parent.parent / "Roll Log"
        roll_log_dir.mkdir(exist_ok=True)
        out_path = args.output or str(roll_log_dir / f"{today} - {video_name} (gemini).md")

        print(f"\nStep 4: Generating Obsidian report...")
        generate_markdown_report(timeline, summary, args.player_name, args.video, duration, out_path)
        print(f"Report saved to: {out_path}")

    # Quick stats
    print(f"\n{'─' * 45}")
    if "dominant_time_pct" in summary:
        print(f"  Dominant/guard time: {summary['dominant_time_pct']:.0f}%")
    if summary.get("top_3_improvements"):
        print(f"  Top improvement: {summary['top_3_improvements'][0]}")
    if summary.get("guard_retention_score"):
        print(f"  Guard retention: {summary['guard_retention_score']}/10")
    print(f"{'─' * 45}\n")


if __name__ == "__main__":
    main()
