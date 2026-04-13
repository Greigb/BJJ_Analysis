#!/usr/bin/env python3
"""
BJJ Rolling Analyser — Prototype v1
====================================
Extracts keyframes from rolling footage and uses Claude's Vision API
to identify positions, transitions, and generate coaching feedback.

Usage:
    python analyse_roll.py path/to/video.mp4

    # Custom settings
    python analyse_roll.py path/to/video.mp4 --interval 2 --player-name Greig --output report.html

Requirements:
    pip install anthropic Pillow
    ffmpeg must be installed (brew install ffmpeg / apt install ffmpeg)
    Set ANTHROPIC_API_KEY environment variable

Camera tips for best results:
    - Overhead or elevated 45° angle (minimises occlusion)
    - Consistent lighting, clean mat background
    - Both grapplers fully in frame throughout
"""

import anthropic
import base64
import json
import os
import subprocess
import sys
import argparse
import tempfile
import time
from pathlib import Path
from datetime import timedelta


# ─── Configuration ──────────────────────────────────────────────────────────

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"

SYSTEM_PROMPT = """You are an expert Brazilian Jiu-Jitsu analyst with black belt-level knowledge.
You are analysing keyframes extracted from a rolling/sparring session.

Your job is to analyse each frame and return a JSON object with your assessment.

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
- Player A = the person identified in the first frame (you'll be told who to track)
- Player B = their training partner
- If positions are complementary (e.g. A has mount, B has bottom mount), label both
- If the frame is blurry, transitional, or unclear, use "scramble_generic" or "unclear"
- Be specific about techniques: name the exact sweep, submission, or pass attempt
- Coaching tips should be actionable: "create a frame with your forearm" not "improve defence"
- Confidence should reflect how certain you are of the position identification
"""

BATCH_ANALYSIS_PROMPT = """Analyse these {count} sequential frames from a BJJ rolling session.
The frames are {interval} seconds apart, starting at timestamp {start_time}s.

Player A (the person we're tracking): {player_name}
Context from previous frames: {context}

Return a JSON array with one object per frame, in order.
Remember: return ONLY valid JSON array, no markdown formatting, no backticks, no explanation outside the JSON.
"""

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

Return ONLY valid JSON, no markdown, no backticks.
"""


# ─── Frame Extraction ───────────────────────────────────────────────────────

def check_ffmpeg():
    """Verify ffmpeg is available."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", video_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def extract_frames(video_path: str, interval: float = 2.0, max_frames: int = 150) -> list:
    """
    Extract keyframes from video at the given interval.
    Returns list of dicts: { 'path': str, 'timestamp': float, 'frame_num': int }
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    duration = get_video_duration(video_path)
    total_possible = int(duration / interval)
    actual_interval = interval

    # If too many frames, increase interval
    if total_possible > max_frames:
        actual_interval = duration / max_frames
        print(f"  ⚠ Video too long for {interval}s interval ({total_possible} frames).")
        print(f"    Adjusting to {actual_interval:.1f}s interval ({max_frames} frames max).")

    # Create temp directory for frames
    frame_dir = tempfile.mkdtemp(prefix="bjj_frames_")

    print(f"  Extracting frames every {actual_interval:.1f}s from {duration:.0f}s video...")

    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-vf", f"fps=1/{actual_interval},scale=1024:-1",
        "-q:v", "3",
        "-y",
        os.path.join(frame_dir, "frame_%04d.jpg")
    ], capture_output=True, check=True)

    # Collect frame info
    frames = []
    for i, fname in enumerate(sorted(os.listdir(frame_dir))):
        if fname.endswith(".jpg"):
            frames.append({
                "path": os.path.join(frame_dir, fname),
                "timestamp": i * actual_interval,
                "frame_num": i + 1,
            })

    print(f"  ✓ Extracted {len(frames)} frames")
    return frames, actual_interval, duration


def frame_to_base64(frame_path: str) -> str:
    """Convert a frame image to base64 string."""
    with open(frame_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


# ─── API Analysis ───────────────────────────────────────────────────────────

def load_taxonomy() -> dict:
    """Load the position taxonomy."""
    with open(TAXONOMY_PATH) as f:
        return json.load(f)


def build_taxonomy_string(taxonomy: dict) -> str:
    """Format taxonomy positions for the system prompt."""
    lines = []
    for pos in taxonomy["positions"]:
        cat = taxonomy["categories"][pos["category"]]["label"]
        lines.append(f'  "{pos["id"]}" — {pos["name"]} [{cat}]')
    return "\n".join(lines)


def analyse_batch(
    client: anthropic.Anthropic,
    frames: list,
    interval: float,
    player_name: str,
    context: str,
    taxonomy: dict,
) -> list:
    """Send a batch of frames to Claude Vision API for analysis."""

    taxonomy_str = build_taxonomy_string(taxonomy)
    system = SYSTEM_PROMPT.format(taxonomy_positions=taxonomy_str)

    # Build content blocks — interleave images with frame markers
    content = []
    content.append({
        "type": "text",
        "text": BATCH_ANALYSIS_PROMPT.format(
            count=len(frames),
            interval=f"{interval:.1f}",
            start_time=f"{frames[0]['timestamp']:.1f}",
            player_name=player_name,
            context=context or "This is the start of the session.",
        ),
    })

    for frame in frames:
        content.append({
            "type": "text",
            "text": f"--- Frame {frame['frame_num']} (timestamp: {frame['timestamp']:.1f}s) ---",
        })
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": frame_to_base64(frame["path"]),
            },
        })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": content}],
    )

    # Parse response
    raw_text = response.content[0].text.strip()
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
        print(f"  ⚠ JSON parse error: {e}")
        print(f"    Raw response (first 300 chars): {raw_text[:300]}")
        return []


def generate_summary(
    client: anthropic.Anthropic,
    timeline: list,
    duration: float,
    player_name: str,
) -> dict:
    """Generate a coaching summary from the full timeline."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": SUMMARY_PROMPT.format(
                timeline_json=json.dumps(timeline, indent=2),
                duration=str(timedelta(seconds=int(duration))),
                player_name=player_name,
            ),
        }],
    )

    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
        raw_text = raw_text.strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse summary", "raw": raw_text}


# ─── HTML Report ────────────────────────────────────────────────────────────

def generate_html_report(
    timeline: list,
    summary: dict,
    player_name: str,
    video_path: str,
    duration: float,
    output_path: str,
):
    """Generate an HTML coaching report."""

    # Build position timeline bars
    categories_colors = {
        "standing": "#8B8FA3",
        "guard_bottom": "#4A90D9",
        "guard_top": "#D4A843",
        "dominant_top": "#34C759",
        "inferior_bottom": "#E85D4A",
        "scramble": "#AF52DE",
    }

    taxonomy = load_taxonomy()
    pos_map = {p["id"]: p for p in taxonomy["positions"]}

    timeline_bars = ""
    for entry in timeline:
        pos_id = entry.get("player_a_position", "unclear")
        pos_info = pos_map.get(pos_id, {"category": "scramble", "name": pos_id})
        color = categories_colors.get(pos_info["category"], "#666")
        confidence = entry.get("confidence", 0.5)
        ts = entry.get("timestamp_sec", 0)
        mins = int(ts // 60)
        secs = int(ts % 60)
        tooltip = f'{mins}:{secs:02d} — {pos_info["name"]}'
        if entry.get("active_technique"):
            tooltip += f' ({entry["active_technique"]})'

        timeline_bars += f'''<div class="tbar" style="background:{color};opacity:{0.4 + confidence * 0.6}" title="{tooltip}"></div>\n'''

    # Key moments
    key_moments_html = ""
    if "key_moments" in summary:
        for km in summary["key_moments"]:
            badge_color = {"good": "#34C759", "bad": "#E85D4A", "neutral": "#D4A843"}.get(km.get("assessment", "neutral"), "#D4A843")
            key_moments_html += f'''
            <div class="moment">
                <span class="moment-time">{km.get("timestamp", "?")}</span>
                <span class="moment-badge" style="background:{badge_color}22;color:{badge_color};border:1px solid {badge_color}44">{km.get("assessment", "?")}</span>
                <div class="moment-desc">{km.get("description", "")}</div>
                <div class="moment-suggestion">→ {km.get("suggestion", "")}</div>
            </div>'''

    # Improvements
    improvements_html = ""
    if "top_3_improvements" in summary:
        for i, imp in enumerate(summary["top_3_improvements"], 1):
            improvements_html += f'<div class="improvement"><span class="imp-num">{i}</span>{imp}</div>\n'

    # Strengths
    strengths_html = ""
    if "strengths_observed" in summary:
        for s in summary["strengths_observed"]:
            strengths_html += f'<div class="strength">✓ {s}</div>\n'

    # Scores
    scores = {
        "Guard Retention": summary.get("guard_retention_score", "–"),
        "Positional Awareness": summary.get("positional_awareness_score", "–"),
        "Transition Quality": summary.get("transition_quality_score", "–"),
    }
    scores_html = ""
    for label, score in scores.items():
        try:
            pct = int(score) * 10
        except (ValueError, TypeError):
            pct = 50
        scores_html += f'''
        <div class="score-row">
            <span class="score-label">{label}</span>
            <div class="score-bar-bg"><div class="score-bar-fill" style="width:{pct}%"></div></div>
            <span class="score-val">{score}/10</span>
        </div>'''

    dur_str = str(timedelta(seconds=int(duration)))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BJJ Roll Analysis — {player_name}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0B0C0F; color:#E5E7EB; font-family:'Barlow',sans-serif; padding:24px; max-width:800px; margin:0 auto; }}
  h1 {{ font-family:'Barlow Condensed',sans-serif; font-size:28px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#F9FAFB; margin-bottom:4px; }}
  .subtitle {{ font-family:'IBM Plex Mono',monospace; font-size:12px; color:#6B7280; margin-bottom:24px; }}
  .section {{ background:#12141A; border:1px solid #1E2030; border-radius:12px; padding:20px; margin-bottom:16px; }}
  .section-title {{ font-family:'Barlow Condensed',sans-serif; font-size:16px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#9CA3AF; margin-bottom:12px; }}
  .overview {{ font-size:15px; line-height:1.7; color:#C9CDD8; }}
  .timeline-strip {{ display:flex; gap:1px; height:32px; border-radius:6px; overflow:hidden; margin-bottom:8px; }}
  .tbar {{ flex:1; min-width:2px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:8px; }}
  .legend-item {{ display:flex; align-items:center; gap:6px; font-size:11px; color:#9CA3AF; }}
  .legend-dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
  .moment {{ padding:12px 0; border-bottom:1px solid #1E2030; }}
  .moment:last-child {{ border-bottom:none; }}
  .moment-time {{ font-family:'IBM Plex Mono',monospace; font-size:13px; color:#6B7280; margin-right:8px; }}
  .moment-badge {{ font-size:10px; padding:2px 8px; border-radius:20px; text-transform:uppercase; font-weight:600; letter-spacing:0.05em; }}
  .moment-desc {{ font-size:14px; color:#E5E7EB; margin-top:6px; }}
  .moment-suggestion {{ font-size:13px; color:#D4A843; margin-top:4px; }}
  .improvement {{ display:flex; align-items:flex-start; gap:10px; padding:10px 0; font-size:14px; color:#C9CDD8; border-bottom:1px solid #1E2030; }}
  .improvement:last-child {{ border-bottom:none; }}
  .imp-num {{ background:#E85D4A22; color:#E85D4A; width:24px; height:24px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; flex-shrink:0; }}
  .strength {{ padding:8px 0; font-size:14px; color:#34C759; }}
  .score-row {{ display:flex; align-items:center; gap:12px; padding:8px 0; }}
  .score-label {{ font-size:13px; color:#9CA3AF; width:160px; flex-shrink:0; }}
  .score-bar-bg {{ flex:1; height:8px; background:#1E2030; border-radius:4px; overflow:hidden; }}
  .score-bar-fill {{ height:100%; background:linear-gradient(90deg,#4A90D9,#34C759); border-radius:4px; transition:width 0.3s; }}
  .score-val {{ font-family:'IBM Plex Mono',monospace; font-size:13px; color:#E5E7EB; width:50px; text-align:right; }}
  .footer {{ text-align:center; font-size:11px; color:#4B5563; margin-top:32px; font-family:'IBM Plex Mono',monospace; }}
</style>
</head>
<body>
  <h1>Roll Analysis — {player_name}</h1>
  <div class="subtitle">Source: {os.path.basename(video_path)} · Duration: {dur_str} · {len(timeline)} frames analysed</div>

  <div class="section">
    <div class="section-title">Session Overview</div>
    <div class="overview">{summary.get("session_overview", "Analysis complete.")}</div>
  </div>

  <div class="section">
    <div class="section-title">Position Timeline</div>
    <div class="timeline-strip">
      {timeline_bars}
    </div>
    <div class="legend">
      <div class="legend-item"><div class="legend-dot" style="background:#8B8FA3"></div>Standing</div>
      <div class="legend-item"><div class="legend-dot" style="background:#4A90D9"></div>Guard (Bottom)</div>
      <div class="legend-item"><div class="legend-dot" style="background:#D4A843"></div>Guard (Top)</div>
      <div class="legend-item"><div class="legend-dot" style="background:#34C759"></div>Dominant (Top)</div>
      <div class="legend-item"><div class="legend-dot" style="background:#E85D4A"></div>Inferior (Bottom)</div>
      <div class="legend-item"><div class="legend-dot" style="background:#AF52DE"></div>Scramble</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Scores</div>
    {scores_html}
  </div>

  <div class="section">
    <div class="section-title">Key Moments</div>
    {key_moments_html if key_moments_html else '<div style="color:#6B7280;font-size:13px">No key moments identified.</div>'}
  </div>

  <div class="section">
    <div class="section-title">Top 3 Improvements</div>
    {improvements_html if improvements_html else '<div style="color:#6B7280;font-size:13px">No specific improvements identified.</div>'}
  </div>

  <div class="section">
    <div class="section-title">Strengths Observed</div>
    {strengths_html if strengths_html else '<div style="color:#6B7280;font-size:13px">Insufficient data to assess strengths.</div>'}
  </div>

  <div class="section">
    <div class="section-title">Overall Notes</div>
    <div class="overview">{summary.get("overall_notes", "Review complete.")}</div>
  </div>

  <div class="footer">
    Generated by BJJ Rolling Analyser v1 · Position taxonomy: {len(taxonomy["positions"])} positions
  </div>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)

    return output_path


# ─── Markdown Report ───────────────────────────────────────────────────────

def generate_markdown_report(
    timeline: list,
    summary: dict,
    player_name: str,
    video_path: str,
    duration: float,
    output_path: str,
):
    """Generate an Obsidian-compatible markdown coaching report."""
    taxonomy = load_taxonomy()
    pos_map = {p["id"]: p for p in taxonomy["positions"]}

    dur_str = str(timedelta(seconds=int(duration)))
    today = time.strftime("%Y-%m-%d")

    lines = [
        "---",
        f"date: {today}",
        f"partner: ",
        f"duration: \"{dur_str}\"",
        f"frames_analysed: {len(timeline)}",
        f"guard_retention: {summary.get('guard_retention_score', '')}",
        f"positional_awareness: {summary.get('positional_awareness_score', '')}",
        f"transition_quality: {summary.get('transition_quality_score', '')}",
        f"tags: [roll]",
        "---",
        "",
        f"# Roll - {today}",
        "",
        f"**Source:** {os.path.basename(video_path)}",
        f"**Duration:** {dur_str}",
        f"**Frames:** {len(timeline)}",
        "",
        "## Summary",
        "",
        summary.get("session_overview", "Analysis complete."),
        "",
        "## Scores",
        "",
        f"| Metric | Score |",
        f"|--------|-------|",
        f"| Guard Retention | {summary.get('guard_retention_score', '-')}/10 |",
        f"| Positional Awareness | {summary.get('positional_awareness_score', '-')}/10 |",
        f"| Transition Quality | {summary.get('transition_quality_score', '-')}/10 |",
        "",
    ]

    # Key moments
    if "key_moments" in summary and summary["key_moments"]:
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
    if "top_3_improvements" in summary and summary["top_3_improvements"]:
        lines.append("## Top Improvements")
        lines.append("")
        for i, imp in enumerate(summary["top_3_improvements"], 1):
            lines.append(f"{i}. {imp}")
        lines.append("")

    # Strengths
    if "strengths_observed" in summary and summary["strengths_observed"]:
        lines.append("## Strengths Observed")
        lines.append("")
        for s in summary["strengths_observed"]:
            lines.append(f"- {s}")
        lines.append("")

    # Position timeline (compact)
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
        pos_name = pos_info["name"]
        tech = entry.get("active_technique") or ""
        notes = entry.get("notes", "")
        # Wikilink the position name
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


# ─── Main Pipeline ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BJJ Rolling Analyser — AI-powered roll feedback")
    parser.add_argument("video", help="Path to rolling video file")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between keyframes (default: 2)")
    parser.add_argument("--player-name", default="Player A", help="Name of the player to track")
    parser.add_argument("--output", default=None, help="Output HTML report path")
    parser.add_argument("--batch-size", type=int, default=5, help="Frames per API call (default: 5)")
    parser.add_argument("--max-frames", type=int, default=150, help="Maximum frames to extract (default: 150)")
    parser.add_argument("--json-only", action="store_true", help="Output raw JSON timeline instead of HTML report")
    parser.add_argument("--markdown", action="store_true", help="Output Obsidian-compatible markdown note to Roll Log/")
    args = parser.parse_args()

    # ─── Preflight checks
    print("\n🥋 BJJ Rolling Analyser v1")
    print("=" * 50)

    if not check_ffmpeg():
        print("❌ ffmpeg not found. Install it:")
        print("   macOS:  brew install ffmpeg")
        print("   Linux:  sudo apt install ffmpeg")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY environment variable not set.")
        print("   export ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    taxonomy = load_taxonomy()

    # ─── Step 1: Extract frames
    print(f"\n📹 Step 1: Extracting frames from {args.video}")
    frames, interval, duration = extract_frames(
        args.video, args.interval, args.max_frames
    )

    # ─── Step 2: Analyse in batches
    print(f"\n🔍 Step 2: Analysing {len(frames)} frames (batch size: {args.batch_size})")
    timeline = []
    context = ""

    for batch_start in range(0, len(frames), args.batch_size):
        batch = frames[batch_start:batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1
        total_batches = (len(frames) + args.batch_size - 1) // args.batch_size

        print(f"  Batch {batch_num}/{total_batches} "
              f"(frames {batch[0]['frame_num']}-{batch[-1]['frame_num']}, "
              f"{batch[0]['timestamp']:.0f}s-{batch[-1]['timestamp']:.0f}s)...", end=" ", flush=True)

        try:
            results = analyse_batch(
                client, batch, interval, args.player_name, context, taxonomy
            )
            timeline.extend(results)
            print(f"✓ ({len(results)} positions detected)")

            # Build context for next batch
            if results:
                last = results[-1]
                context = (f"At {last.get('timestamp_sec', '?')}s: "
                          f"Player A in {last.get('player_a_position', '?')}, "
                          f"Player B in {last.get('player_b_position', '?')}. "
                          f"{last.get('notes', '')}")
        except Exception as e:
            print(f"⚠ Error: {e}")
            continue

        # Rate limiting — be gentle with the API
        if batch_start + args.batch_size < len(frames):
            time.sleep(1)

    print(f"\n  ✓ Analysed {len(timeline)} frames total")

    # ─── Step 3: Generate summary
    print("\n📊 Step 3: Generating coaching summary...")
    summary = generate_summary(client, timeline, duration, args.player_name)

    if "error" not in summary:
        print("  ✓ Summary generated")
    else:
        print(f"  ⚠ Summary had issues: {summary.get('error', '')}")

    # ─── Step 4: Output
    if args.json_only:
        output = {
            "video": args.video,
            "player": args.player_name,
            "duration_sec": duration,
            "frame_interval_sec": interval,
            "timeline": timeline,
            "summary": summary,
        }
        out_path = args.output or args.video.rsplit(".", 1)[0] + "_analysis.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n✅ JSON analysis saved to: {out_path}")
    elif args.markdown:
        today = time.strftime("%Y-%m-%d")
        video_name = os.path.splitext(os.path.basename(args.video))[0]
        roll_log_dir = Path(__file__).parent.parent / "Roll Log"
        roll_log_dir.mkdir(exist_ok=True)
        out_path = args.output or str(roll_log_dir / f"{today} - {video_name}.md")
        print(f"\n📄 Step 4: Generating Obsidian markdown report...")
        generate_markdown_report(timeline, summary, args.player_name, args.video, duration, out_path)
        print(f"\n✅ Markdown report saved to: {out_path}")
    else:
        out_path = args.output or args.video.rsplit(".", 1)[0] + "_report.html"
        print(f"\n📄 Step 4: Generating HTML report...")
        generate_html_report(timeline, summary, args.player_name, args.video, duration, out_path)
        print(f"\n✅ Report saved to: {out_path}")

    # ─── Quick stats
    print(f"\n{'─' * 50}")
    print(f"📊 Quick Stats:")
    print(f"   Duration: {str(timedelta(seconds=int(duration)))}")
    print(f"   Frames analysed: {len(timeline)}")
    if "dominant_time_pct" in summary:
        print(f"   Dominant/guard time: {summary['dominant_time_pct']:.0f}%")
    if "top_3_improvements" in summary:
        print(f"   Top improvement: {summary['top_3_improvements'][0]}")
    print(f"{'─' * 50}\n")

    # Cleanup temp frames
    for frame in frames:
        try:
            os.remove(frame["path"])
        except OSError:
            pass


if __name__ == "__main__":
    main()
