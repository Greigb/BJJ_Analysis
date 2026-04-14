#!/usr/bin/python3
"""
BJJ Groq Analyser — Free, Fully Automated Analysis
=====================================================
Uses Groq's free API with Llama 4 Scout vision to analyse BJJ footage.
No manual steps: video in → report out.

Usage:
    python groq_analyser.py path/to/video.mp4 --player-name Greig
    python groq_analyser.py path/to/video.mp4 --player-name Greig --video-url "https://youtube.com/..."

Requirements:
    pip install groq opencv-python Pillow
    export GROQ_API_KEY='your-key-here'  (free from https://console.groq.com/keys)
"""

import cv2
import json
import os
import sys
import argparse
import base64
import time
from pathlib import Path
from datetime import timedelta
from io import BytesIO
from PIL import Image
from groq import Groq


# ─── Configuration ────────────────────────────────────────────────────────────

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"
MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
MAX_IMAGES_PER_REQUEST = 4  # Groq allows 5, keep 1 buffer

SYSTEM_PROMPT = """You are an expert Brazilian Jiu-Jitsu analyst with black belt-level knowledge.
You are analysing keyframes extracted from a rolling/sparring session.

POSITION TAXONOMY — use ONLY these position IDs:
{taxonomy_positions}

{player_id_block}

IMPORTANT: The video may show multiple people (bystanders, referees, coaches,
other grapplers on adjacent mats). Focus ONLY on the two people actively
grappling. Ignore anyone standing on the sideline, sitting, or not engaged
in the roll. If you cannot determine which two people are the focus, describe
what you see and set both positions to "unclear".

For EACH frame image provided, return a JSON object:
{{
  "frame_number": <int>,
  "timestamp_sec": <float>,
  "player_a_position": "<position_id from taxonomy>",
  "player_b_position": "<position_id from taxonomy>",
  "confidence": <float 0.0-1.0>,
  "active_technique": "<technique being attempted or null>",
  "notes": "<brief observation — mention what you see that identifies Player A>",
  "coaching_tip": "<one actionable suggestion if relevant, or null>"
}}

Guidelines:
- Player A = the person we're tracking
- Player B = their training partner
- If positions are complementary (e.g. A has mount, B has bottom mount), label both
- If the frame is blurry or unclear, use "scramble_generic" or "unclear"
- Be SPECIFIC with leg entanglements: identify exact ashi garami / sankaku position
- Coaching tips should be actionable
"""

BATCH_PROMPT = """Analyse these {count} sequential frames from a BJJ rolling session.
The frames are {interval} seconds apart, starting at timestamp {start_time}s.

Player A (the person we're tracking): {player_name}
Context from previous frames: {context}

Return a JSON array with one object per frame, in order.
Return ONLY valid JSON array, no markdown, no backticks, no explanation."""

SUMMARY_PROMPT = """You are a BJJ black belt coach reviewing a complete rolling session analysis.

Here is the timestamped position data from the session:
{timeline_json}

The session was {duration} long.
Player being coached: {player_name}

Provide a coaching summary as a JSON object:
{{
  "session_overview": "<2-3 sentence summary of the roll>",
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

def extract_frames(video_path, interval=3.0, max_frames=80):
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
            # Resize for API (keep under 4MB base64 limit)
            h, w = frame.shape[:2]
            scale = min(512 / w, 512 / h, 1.0)
            if scale < 1.0:
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

            # Convert to base64 JPEG
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb)
            buffer = BytesIO()
            pil_image.save(buffer, format="JPEG", quality=70)
            b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            frames.append({
                "base64": b64,
                "timestamp": timestamp,
                "frame_num": sample_count + 1,
            })
            sample_count += 1

        frame_idx += 1

    cap.release()
    print(f"  Extracted {len(frames)} frames")
    return frames, interval, duration


# ─── Groq API ─────────────────────────────────────────────────────────────────

def parse_json_response(raw_text):
    """Parse JSON from API response, handling markdown fences."""
    raw = raw_text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            result = [result]
        return result
    except json.JSONDecodeError as e:
        print(f"  Warning: JSON parse error: {e}")
        print(f"  Raw (first 300 chars): {raw[:300]}")
        return []


def analyse_batch(client, frames, interval, player_name, context, system_prompt):
    """Send a batch of frames to Groq for analysis."""
    content = [
        {
            "type": "text",
            "text": BATCH_PROMPT.format(
                count=len(frames),
                interval=f"{interval:.1f}",
                start_time=f"{frames[0]['timestamp']:.1f}",
                player_name=player_name,
                context=context or "This is the start of the session.",
            ),
        }
    ]

    for frame in frames:
        content.append({
            "type": "text",
            "text": f"--- Frame {frame['frame_num']} (timestamp: {frame['timestamp']:.1f}s) ---",
        })
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{frame['base64']}",
            },
        })

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        max_tokens=4096,
        temperature=0.2,
    )

    return parse_json_response(response.choices[0].message.content)


def generate_summary(client, timeline, duration, player_name):
    """Generate coaching summary from timeline."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": SUMMARY_PROMPT.format(
                    timeline_json=json.dumps(timeline, indent=2),
                    duration=str(timedelta(seconds=int(duration))),
                    player_name=player_name,
                ),
            }
        ],
        max_tokens=4096,
        temperature=0.3,
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Failed to parse summary", "raw": raw}


# ─── Report Generation ────────────────────────────────────────────────────────

def make_timestamp_link(ts_str, ts_sec, video_url):
    if not video_url:
        return f"**{ts_str}**"
    if "youtube.com" in video_url or "youtu.be" in video_url:
        if "youtu.be/" in video_url:
            vid_id = video_url.split("youtu.be/")[1].split("?")[0]
        elif "v=" in video_url:
            vid_id = video_url.split("v=")[1].split("&")[0]
        else:
            return f"**{ts_str}**"
        return f"[**{ts_str}**](https://www.youtube.com/watch?v={vid_id}&t={int(ts_sec)}s)"
    return f"**{ts_str}**"


def generate_markdown_report(timeline, summary, player_name, video_path, duration, output_path, video_url=None):
    """Generate Obsidian-compatible markdown report."""
    taxonomy = load_taxonomy()
    pos_map = {p["id"]: p for p in taxonomy["positions"]}
    cat_map = taxonomy["categories"]

    dur_str = str(timedelta(seconds=int(duration)))
    today = time.strftime("%Y-%m-%d")

    cat_emoji = {
        "Standing": "⬜",
        "Guard (Bottom)": "🟦",
        "Inside Guard (Top)": "🟨",
        "Dominant Position (Top)": "🟩",
        "Inferior Position (Bottom)": "🟥",
        "Leg Entanglement": "🟧",
        "Scramble / Transition": "🟪",
    }

    lines = [
        "---",
        f"date: {today}",
        f"partner: ",
        f'duration: "{dur_str}"',
        f"frames_analysed: {len(timeline)}",
        f"guard_retention: {summary.get('guard_retention_score', '')}",
        f"positional_awareness: {summary.get('positional_awareness_score', '')}",
        f"transition_quality: {summary.get('transition_quality_score', '')}",
        f"method: groq-llama-vision",
        f"tags: [roll, groq-analysis]",
        "---",
        "",
        f"# Roll Analysis - {today}",
        "",
        f"**Player:** {player_name}",
        f"**Source:** {os.path.basename(video_path)}",
        f"**Duration:** {dur_str}",
        f"**Frames:** {len(timeline)}",
        f"**Method:** Groq Llama 4 Scout (free tier)",
    ]
    if video_url:
        lines.append(f"**Video:** [{video_url}]({video_url})")
    lines.append("")

    # Summary
    if summary.get("session_overview"):
        lines.extend(["## Summary", "", summary["session_overview"], ""])

    # Scores
    lines.extend([
        "## Scores", "",
        "| Metric | Score |",
        "|--------|-------|",
        f"| Guard Retention | {summary.get('guard_retention_score', '-')}/10 |",
        f"| Positional Awareness | {summary.get('positional_awareness_score', '-')}/10 |",
        f"| Transition Quality | {summary.get('transition_quality_score', '-')}/10 |",
        "",
    ])

    # Position timeline bar
    bar = ""
    for entry in timeline:
        pos_id = entry.get("player_a_position", "unclear")
        if pos_id in pos_map:
            cat_id = pos_map[pos_id]["category"]
            cat_label = cat_map.get(cat_id, {}).get("label", "")
            bar += cat_emoji.get(cat_label, "⬛")
        else:
            bar += "⬛"
    lines.extend([
        "## Position Timeline", "",
        bar, "",
        "Legend: ⬜Standing 🟦Guard(Bottom) 🟨Guard(Top) 🟩Dominant(Top) 🟥Inferior(Bottom) 🟧Leg Entanglement 🟪Scramble",
        "",
    ])

    # Key moments
    if summary.get("key_moments"):
        lines.append("## Key Moments")
        lines.append("")
        for km in summary["key_moments"]:
            ts = km.get("timestamp", "?")
            parts = ts.replace("?", "0").split(":")
            ts_sec = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0
            ts_link = make_timestamp_link(ts, ts_sec, video_url)
            lines.append(f"- {ts_link} [{km.get('assessment', 'neutral')}] - {km.get('description', '')}")
            if km.get("suggestion"):
                lines.append(f"  - *Suggestion:* {km['suggestion']}")
        lines.append("")

    # Improvements
    if summary.get("top_3_improvements"):
        lines.extend(["## Top Improvements", ""])
        for i, imp in enumerate(summary["top_3_improvements"], 1):
            lines.append(f"{i}. {imp}")
        lines.append("")

    # Strengths
    if summary.get("strengths_observed"):
        lines.extend(["## Strengths Observed", ""])
        for s in summary["strengths_observed"]:
            lines.append(f"- {s}")
        lines.append("")

    # Full timeline
    lines.extend([
        "## Frame-by-Frame", "",
        "| Time | Player A | Player B | Technique | Notes |",
        "|------|----------|----------|-----------|-------|",
    ])
    for entry in timeline:
        ts_sec = entry.get("timestamp_sec", 0)
        mins = int(ts_sec // 60)
        secs = int(ts_sec % 60)
        ts_str = f"{mins}:{secs:02d}"
        ts_link = make_timestamp_link(ts_str, ts_sec, video_url)
        pos_a_id = entry.get("player_a_position", "unclear")
        pos_b_id = entry.get("player_b_position", "unclear")
        pos_a = pos_map.get(pos_a_id, {}).get("name", pos_a_id)
        pos_b = pos_map.get(pos_b_id, {}).get("name", pos_b_id)
        tech = entry.get("active_technique") or ""
        notes = entry.get("notes", "")
        tip = entry.get("coaching_tip") or ""
        note_text = notes
        if tip:
            note_text += f" *Tip: {tip}*"
        lines.append(f"| {ts_link} | [[{pos_a}]] | [[{pos_b}]] | {tech} | {note_text} |")
    lines.append("")

    # Overall notes
    if summary.get("overall_notes"):
        lines.extend(["## Overall Notes", "", summary["overall_notes"], ""])

    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    return output_path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="BJJ Groq Analyser — Free, fully automated analysis"
    )
    parser.add_argument("video", help="Path to rolling video file")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Seconds between keyframes (default: 5)")
    parser.add_argument("--player-name", default="Player A",
                        help="Name of the player to track")
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--max-frames", type=int, default=60,
                        help="Maximum frames to analyse (default: 60)")
    parser.add_argument("--video-url", default=None,
                        help="YouTube URL for clickable timestamps")
    parser.add_argument("--json-only", action="store_true",
                        help="Output raw JSON instead of markdown")
    parser.add_argument("--player-description", default="",
                        help="Visual description of Player A (e.g. 'white gi', 'blue shorts')")
    args = parser.parse_args()

    print("\n--- BJJ Groq Analyser (Free Tier) ---")
    print("=" * 42)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY not set.")
        print("Get a free key at: https://console.groq.com/keys")
        print("Then run: export GROQ_API_KEY='your-key-here'")
        sys.exit(1)

    if not os.path.exists(args.video):
        print(f"Error: Video not found: {args.video}")
        sys.exit(1)

    client = Groq(api_key=api_key)
    taxonomy = load_taxonomy()
    taxonomy_str = build_taxonomy_string(taxonomy)
    player_id_block = ""
    if args.player_description:
        player_id_block = f"""Player A visual identification: {args.player_description}
Use this description to consistently identify Player A across ALL frames.
If Player A's appearance changes (e.g. position shift), maintain tracking based on continuity."""
    system_prompt = SYSTEM_PROMPT.format(taxonomy_positions=taxonomy_str, player_id_block=player_id_block)

    # Step 1: Extract frames
    print(f"\nStep 1: Extracting frames from {args.video}")
    frames, interval, duration = extract_frames(
        args.video, args.interval, args.max_frames
    )

    # Step 2: Analyse in batches
    batch_size = MAX_IMAGES_PER_REQUEST
    total_batches = (len(frames) + batch_size - 1) // batch_size
    print(f"\nStep 2: Analysing {len(frames)} frames ({total_batches} API calls)")

    timeline = []
    context = ""

    for batch_start in range(0, len(frames), batch_size):
        batch = frames[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1

        print(f"  Batch {batch_num}/{total_batches} "
              f"(frames {batch[0]['frame_num']}-{batch[-1]['frame_num']}, "
              f"{batch[0]['timestamp']:.0f}s-{batch[-1]['timestamp']:.0f}s)...",
              end=" ", flush=True)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                results = analyse_batch(
                    client, batch, interval, args.player_name, context, system_prompt
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
                err = str(e)
                if "429" in err and attempt < max_retries - 1:
                    wait = 10 * (attempt + 1)
                    print(f"Rate limited, waiting {wait}s...", end=" ", flush=True)
                    time.sleep(wait)
                else:
                    print(f"Error: {err[:100]}")
                    break

        # Rate limit spacing
        if batch_start + batch_size < len(frames):
            time.sleep(3)

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
            "timeline": timeline,
            "summary": summary,
        }
        out_path = args.output or str(Path(args.video).stem) + "_groq.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nJSON saved to: {out_path}")
    else:
        today = time.strftime("%Y-%m-%d")
        video_name = Path(args.video).stem
        roll_log_dir = Path(__file__).parent.parent / "Roll Log"
        roll_log_dir.mkdir(exist_ok=True)
        out_path = args.output or str(roll_log_dir / f"{today} - {video_name} (groq).md")

        print(f"\nStep 4: Generating Obsidian report...")
        generate_markdown_report(
            timeline, summary, args.player_name, args.video,
            duration, out_path, args.video_url
        )
        print(f"Report saved to: {out_path}")

    # Quick stats
    print(f"\n{'─' * 42}")
    if summary.get("guard_retention_score"):
        print(f"  Guard retention: {summary['guard_retention_score']}/10")
    if summary.get("top_3_improvements"):
        print(f"  Top improvement: {summary['top_3_improvements'][0]}")
    print(f"{'─' * 42}\n")


if __name__ == "__main__":
    main()
