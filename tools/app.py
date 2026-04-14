#!/usr/bin/python3
"""
BJJ Rolling Analyser — Streamlit App
======================================
Local web app for analysing BJJ footage.

Launch:
    cd tools/
    streamlit run app.py
"""

import streamlit as st
import json
import time
import os
import sys
import re
import base64
from pathlib import Path
from collections import Counter
from datetime import timedelta
from io import BytesIO
try:
    from streamlit_agraph import agraph, Node, Edge, Config
    HAS_AGRAPH = True
except ImportError:
    HAS_AGRAPH = False

sys.path.insert(0, str(Path(__file__).parent))

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"
ROLL_LOG_DIR = Path(__file__).parent.parent / "Roll Log"


# ─── Taxonomy ─────────────────────────────────────────────────────────────────

@st.cache_data
def load_taxonomy():
    with open(TAXONOMY_PATH) as f:
        return json.load(f)


def get_position_ids(taxonomy):
    groups = {}
    for pos in taxonomy["positions"]:
        cat = taxonomy["categories"][pos["category"]]["label"]
        groups.setdefault(cat, []).append(pos["id"])
    lines = []
    for cat, ids in groups.items():
        lines.append(f"**{cat}:** {', '.join(ids)}")
    return "\n".join(lines)


@st.cache_data
def load_position_reference():
    ref_path = Path(__file__).parent / "position_reference.json"
    if ref_path.exists():
        with open(ref_path) as f:
            return json.load(f)
    return {}


def build_taxonomy_string(taxonomy):
    ref = load_position_reference()
    lines = []
    for pos in taxonomy["positions"]:
        cat = taxonomy["categories"][pos["category"]]["label"]
        cues = pos.get("visual_cues", "")
        lines.append(f'  "{pos["id"]}" — {pos["name"]} [{cat}]')
        if cues:
            lines.append(f'    Visual: {cues}')
        # Add GrappleMap variations for context
        pos_ref = ref.get(pos["id"], {})
        variations = pos_ref.get("grapplemap_variations", [])
        if variations:
            lines.append(f'    Also known as: {", ".join(variations[:4])}')
    return "\n".join(lines)


def build_category_prompt(taxonomy):
    """Build prompt for Pass 1: category identification."""
    lines = ["Identify which CATEGORY this frame belongs to:\n"]
    for cat_id, cat in taxonomy["categories"].items():
        cues = cat.get("visual_cues", "")
        lines.append(f'  "{cat_id}" — {cat["label"]}')
        if cues:
            lines.append(f'    How to identify: {cues}')
    return "\n".join(lines)


def build_position_prompt_for_category(taxonomy, category_id):
    """Build prompt for Pass 2: specific position within a category."""
    cat = taxonomy["categories"].get(category_id, {})
    positions = [p for p in taxonomy["positions"] if p["category"] == category_id]
    lines = [f"This frame is in the '{cat.get('label', category_id)}' category.",
             f"Identify the SPECIFIC position from these options:\n"]
    for pos in positions:
        cues = pos.get("visual_cues", "")
        lines.append(f'  "{pos["id"]}" — {pos["name"]}')
        if cues:
            lines.append(f'    Visual: {cues}')
    return "\n".join(lines)


# ─── YouTube Helpers ──────────────────────────────────────────────────────────

def extract_youtube_id(url):
    if not url:
        return None
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    elif "v=" in url:
        return url.split("v=")[1].split("&")[0]
    return None


def youtube_timestamp_url(video_url, seconds):
    vid_id = extract_youtube_id(video_url)
    if vid_id:
        return f"https://www.youtube.com/watch?v={vid_id}&t={int(seconds)}s"
    return video_url


def youtube_embed_html(video_url, start_sec=0, player_id="yt-player"):
    """Generate YouTube IFrame embed with JS seek control."""
    vid_id = extract_youtube_id(video_url)
    if not vid_id:
        return ""
    return f"""
    <div id="{player_id}-container" style="position:sticky;top:0;z-index:100;background:#0B0C0F;padding:8px 0;">
        <iframe id="{player_id}" width="100%" height="400"
            src="https://www.youtube.com/embed/{vid_id}?enablejsapi=1&start={int(start_sec)}"
            frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowfullscreen style="border-radius:12px;">
        </iframe>
    </div>
    <script>
        var ytPlayer;
        function onYouTubeIframeAPIReady() {{
            ytPlayer = new YT.Player('{player_id}');
        }}
        function seekTo(seconds) {{
            if (ytPlayer && ytPlayer.seekTo) {{
                ytPlayer.seekTo(seconds, true);
                ytPlayer.playVideo();
            }}
        }}
        if (!document.getElementById('yt-api-script')) {{
            var tag = document.createElement('script');
            tag.id = 'yt-api-script';
            tag.src = 'https://www.youtube.com/iframe_api';
            document.head.appendChild(tag);
        }}
    </script>
    """


def safe_parse_timestamp(ts_str):
    """Parse a timestamp string like '1:30', '27.7', '90' into seconds."""
    try:
        if ":" in str(ts_str):
            parts = str(ts_str).split(":")
            return int(float(parts[0])) * 60 + int(float(parts[1]))
        else:
            return int(float(ts_str))
    except (ValueError, IndexError):
        return 0


def format_timestamp(seconds):
    """Format seconds as m:ss string."""
    s = int(float(seconds))
    return f"{s // 60}:{s % 60:02d}"


# ─── Colours ──────────────────────────────────────────────────────────────────

CAT_COLOURS = {
    "Standing": "#8B8FA3",
    "Guard (Bottom)": "#4A90D9",
    "Inside Guard (Top)": "#D4A843",
    "Dominant Position (Top)": "#34C759",
    "Inferior Position (Bottom)": "#E85D4A",
    "Leg Entanglement": "#F97316",
    "Scramble / Transition": "#AF52DE",
}

CAT_EMOJI = {
    "Standing": "⬜",
    "Guard (Bottom)": "🟦",
    "Inside Guard (Top)": "🟨",
    "Dominant Position (Top)": "🟩",
    "Inferior Position (Bottom)": "🟥",
    "Leg Entanglement": "🟧",
    "Scramble / Transition": "🟪",
}


# ─── Groq Auto-Analysis ───────────────────────────────────────────────────────

def extract_first_frame(video_path):
    """Extract just the first frame from a video for player identification. Returns base64 string or None."""
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        h, w = frame.shape[:2]
        scale = min(640 / w, 640 / h, 1.0)
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)
        buffer = BytesIO()
        pil_image.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception:
        return None


def run_groq_analysis(video_path, player_name, interval, max_frames, groq_key, taxonomy, player_description="", player_b_description=""):
    """Run fully automated Groq analysis on a video file. Returns (data, error)."""
    try:
        import cv2
        from PIL import Image
        from groq import Groq
    except ImportError as e:
        return None, f"Missing dependency: {e}."

    taxonomy_str = build_taxonomy_string(taxonomy)

    player_id_block = ""
    if player_description or player_b_description:
        lines = []
        if player_description:
            lines.append(f"Player A visual identification: {player_description}")
        if player_b_description:
            lines.append(f"Player B visual identification: {player_b_description}")
        lines.append("Use these descriptions to consistently identify each player across ALL frames.")
        lines.append("If appearances overlap or are unclear, use continuity from previous frames.")
        player_id_block = "\n".join(lines)

    category_guide = build_category_prompt(taxonomy)

    system_prompt = f"""You are an expert Brazilian Jiu-Jitsu analyst with black belt-level knowledge.
You are analysing keyframes extracted from a rolling/sparring session.

{player_id_block}

IMPORTANT: The video may show multiple people (bystanders, referees, coaches,
other grapplers on adjacent mats). Focus ONLY on the two people actively
grappling. Ignore anyone standing on the sideline, sitting, or not engaged
in the roll.

CLASSIFICATION METHOD — follow these steps for EACH frame:
Step 1: Identify the CATEGORY first using these visual guides:
{category_guide}

Step 2: Once you know the category, identify the SPECIFIC POSITION using these visual guides:
{taxonomy_str}

Step 3: Verify your answer — does your position match what you actually see?
Common mistakes to avoid:
- Closed guard requires ankles LOCKED behind the back (if legs are open, it's open guard)
- Side control requires PERPENDICULAR chest-to-chest with NO legs between (if a leg is trapped, it's half guard)
- Inside sankaku requires legs TRIANGLED around ONE leg (if legs are mirrored, it's 50/50)
- Mount requires SITTING ON the opponent (if lying across, it's side control)
- Turtle requires hands-and-knees face DOWN (if on their back, it's a different position)

For EACH frame, return a JSON object:
{{
  "frame_number": <int>,
  "timestamp_sec": <float>,
  "category": "<category_id — the category you identified in Step 1>",
  "player_a_position": "<position_id — the specific position from Step 2>",
  "player_b_position": "<position_id — the complementary position for the other player>",
  "confidence": <float 0.0-1.0>,
  "visual_reasoning": "<what you see in the image that led to this classification — describe body positions, limb placement, relative positioning>",
  "active_technique": "<technique being attempted or null>",
  "notes": "<brief observation>",
  "coaching_tip": "<one actionable suggestion or null>"
}}"""

    batch_prompt_tpl = """Analyse these {{count}} sequential frames from a BJJ rolling session.
The frames are {{interval}} seconds apart, starting at timestamp {{start_time}}s.
Player A: {{player_name}}
Context: {{context}}
Return a JSON array with one object per frame. Return ONLY valid JSON, no markdown, no backticks."""

    summary_prompt_tpl = """You are a BJJ black belt coach. Here is position data from a rolling session:
{{timeline_json}}
Session duration: {{duration}}. Player: {{player_name}}.

Return a JSON object with these fields. For each score, include a "reason" explaining why you gave that score:
{{
  "session_overview": "<2-3 sentences>",
  "key_moments": [{{"timestamp": "<mm:ss>", "description": "<what>", "assessment": "<good/bad/neutral>", "suggestion": "<advice>"}}],
  "top_3_improvements": ["<specific actionable improvement 1>", "<2>", "<3>"],
  "strengths_observed": ["<1>", "<2>"],
  "guard_retention_score": <1-10>,
  "guard_retention_reason": "<why this score>",
  "positional_awareness_score": <1-10>,
  "positional_awareness_reason": "<why this score>",
  "transition_quality_score": <1-10>,
  "transition_quality_reason": "<why this score>",
  "overall_notes": "<remarks>"
}}
Return ONLY valid JSON, no markdown, no backticks."""

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None, f"Could not open video: {video_path}"

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames_count / fps if fps > 0 else 0
    frame_skip = int(fps * interval)

    expected = int(duration / interval)
    if expected > max_frames:
        interval = duration / max_frames
        frame_skip = int(fps * interval)

    frames = []
    frame_idx = 0
    sample_count = 0

    while cap.isOpened() and sample_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_skip == 0:
            timestamp = frame_idx / fps
            h, w = frame.shape[:2]
            scale = min(512 / w, 512 / h, 1.0)
            if scale < 1.0:
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb)
            buffer = BytesIO()
            pil_image.save(buffer, format="JPEG", quality=70)
            b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            frames.append({"base64": b64, "timestamp": timestamp, "frame_num": sample_count + 1})
            sample_count += 1
        frame_idx += 1
    cap.release()

    if not frames:
        return None, "No frames extracted from video"

    client = Groq(api_key=groq_key)
    model = "meta-llama/llama-4-scout-17b-16e-instruct"
    batch_size = 3  # Reduced from 4 to lower tokens per request
    timeline = []
    context = "This is the start of the session."
    failed_batches = 0
    total_batches = (len(frames) + batch_size - 1) // batch_size
    progress = st.progress(0, text="Analysing frames...")
    status_text = st.empty()

    for batch_start in range(0, len(frames), batch_size):
        batch = frames[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        pct = batch_num / total_batches
        progress.progress(pct, text=f"Batch {batch_num}/{total_batches} (frames {batch[0]['frame_num']}-{batch[-1]['frame_num']})")

        content = [{
            "type": "text",
            "text": batch_prompt_tpl
                .replace("{{count}}", str(len(batch)))
                .replace("{{interval}}", f"{interval:.1f}")
                .replace("{{start_time}}", f"{batch[0]['timestamp']:.1f}")
                .replace("{{player_name}}", player_name)
                .replace("{{context}}", context),
        }]
        for fr in batch:
            content.append({"type": "text", "text": f"--- Frame {fr['frame_num']} ({fr['timestamp']:.1f}s) ---"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{fr['base64']}"}})

        batch_success = False
        for attempt in range(4):  # More retries with longer waits
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                    max_tokens=4096, temperature=0.2,
                )
                raw = resp.choices[0].message.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1]
                    if raw.endswith("```"):
                        raw = raw.rsplit("```", 1)[0]
                    raw = raw.strip()
                results = json.loads(raw)
                if isinstance(results, dict):
                    results = [results]
                for idx, result in enumerate(results):
                    if idx < len(batch):
                        result["frame_base64"] = batch[idx]["base64"]
                timeline.extend(results)
                if results:
                    last = results[-1]
                    context = f"At {last.get('timestamp_sec', '?')}s: Player A in {last.get('player_a_position', '?')}, Player B in {last.get('player_b_position', '?')}. {last.get('notes', '')}"
                batch_success = True
                status_text.caption(f"Analysed {len(timeline)} frames so far...")
                break
            except Exception as e:
                err = str(e)
                if "429" in err and attempt < 3:
                    wait = 20 * (attempt + 1)  # 20s, 40s, 60s
                    progress.progress(pct, text=f"Rate limited — waiting {wait}s (attempt {attempt+2}/4)...")
                    time.sleep(wait)
                elif "json" in err.lower() and attempt < 3:
                    time.sleep(5)  # Quick retry on JSON parse error
                else:
                    st.warning(f"Batch {batch_num} failed: {err[:80]}")
                    break

        if not batch_success:
            failed_batches += 1
            # Attach frames even without analysis so thumbnails show
            for fr in batch:
                timeline.append({
                    "frame_number": fr["frame_num"],
                    "timestamp_sec": fr["timestamp"],
                    "player_a_position": "unclear",
                    "player_b_position": "unclear",
                    "notes": "Analysis failed for this frame (rate limited)",
                    "frame_base64": fr["base64"],
                })

        # Wait between batches — 10s keeps us under 30k TPM with 3 images/batch
        if batch_start + batch_size < len(frames):
            time.sleep(10)

    # Show partial result warning
    if failed_batches > 0:
        st.warning(f"{failed_batches}/{total_batches} batches failed due to rate limiting. Partial results shown below. Try reducing 'Max frames' or increasing 'Sample interval'.")

    # Generate summary from whatever we have
    progress.progress(1.0, text="Generating summary...")
    analysed_entries = [e for e in timeline if e.get("player_a_position") != "unclear"]

    if analysed_entries:
        # Wait before summary to avoid rate limit
        time.sleep(10)
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": summary_prompt_tpl
                        .replace("{{timeline_json}}", json.dumps(analysed_entries, indent=2))
                        .replace("{{duration}}", str(timedelta(seconds=int(duration))))
                        .replace("{{player_name}}", player_name)
                    }],
                    max_tokens=4096, temperature=0.3,
                )
                raw = resp.choices[0].message.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1]
                    if raw.endswith("```"):
                        raw = raw.rsplit("```", 1)[0]
                    raw = raw.strip()
                summary = json.loads(raw)
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(20 * (attempt + 1))
                else:
                    summary = {"session_overview": f"Summary generation failed. {len(analysed_entries)} frames were analysed successfully.", "overall_notes": ""}
                    break
    else:
        summary = {"session_overview": "No frames were successfully analysed. Try reducing the number of frames or increasing the sample interval.", "overall_notes": ""}

    progress.empty()
    status_text.empty()
    return {"timeline": timeline, "summary": summary, "duration_sec": duration}, None


# ─── Graph Data Helpers ───────────────────────────────────────────────────────

@st.cache_data
def load_jsx_techniques():
    jsx_path = Path(__file__).parent / "components" / "bjj-position-taxonomy.jsx"
    if not jsx_path.exists():
        return {}
    text = jsx_path.read_text()
    result = {}
    pattern = r'name:\s*"([^"]+)",\s*techniques:\s*\[([^\]]+)\]'
    for match in re.finditer(pattern, text):
        name = match.group(1)
        techs = [t.strip().strip('"').strip("'") for t in match.group(2).split(",")]
        result[name] = [t for t in techs if t]
    return result


@st.cache_data
def load_jsx_youtube_links():
    jsx_path = Path(__file__).parent / "components" / "bjj-position-graph.jsx"
    if not jsx_path.exists():
        return {}
    text = jsx_path.read_text()
    result = {}
    node_pattern = r'id:\s*"([^"]+)".*?yt:\s*"([^"]+)".*?ytTitle:\s*"([^"]+)"'
    for match in re.finditer(node_pattern, text, re.DOTALL):
        result[match.group(1)] = {"url": match.group(2), "title": match.group(3)}
    return result


def match_position_to_techniques(pos_name, jsx_techniques):
    pos_lower = pos_name.lower()
    best_match = None
    best_score = 0
    for jsx_name, techs in jsx_techniques.items():
        jsx_lower = jsx_name.lower()
        if pos_lower in jsx_lower or jsx_lower in pos_lower:
            score = len(set(pos_lower.split()) & set(jsx_lower.split()))
            if score > best_score:
                best_score = score
                best_match = techs
        pos_words = set(pos_lower.replace("(", "").replace(")", "").split())
        jsx_words = set(jsx_lower.replace("(", "").replace(")", "").split())
        overlap = len(pos_words & jsx_words)
        if overlap > best_score:
            best_score = overlap
            best_match = techs
    return best_match or []


# ─── Export to Obsidian ───────────────────────────────────────────────────────

def export_to_obsidian(data, player_name, video_name, video_url):
    taxonomy = load_taxonomy()
    pos_map = {p["id"]: p for p in taxonomy["positions"]}
    timeline = data.get("timeline", [])
    summary = data.get("summary", {})
    today = time.strftime("%Y-%m-%d")

    if timeline:
        last_ts = max(e.get("timestamp_sec", 0) for e in timeline)
        duration_str = f"{int(last_ts // 60)}:{int(last_ts % 60):02d}"
    else:
        duration_str = "unknown"

    lines = [
        "---", f"date: {today}", f"partner: ", f'duration: "{duration_str}"',
        f"frames_analysed: {len(timeline)}",
        f"guard_retention: {summary.get('guard_retention_score', '')}",
        f"positional_awareness: {summary.get('positional_awareness_score', '')}",
        f"transition_quality: {summary.get('transition_quality_score', '')}",
        f"method: streamlit-app", f"tags: [roll, app-analysis]",
        "---", "", f"# Roll Analysis - {video_name}", "",
        f"**Player:** {player_name}", f"**Duration:** {duration_str}",
        f"**Moments analysed:** {len(timeline)}",
    ]
    if video_url:
        lines.append(f"**Video:** [{video_url}]({video_url})")
    lines.append("")
    if summary.get("session_overview"):
        lines.extend(["## Summary", "", summary["session_overview"], ""])
    lines.extend([
        "## Scores", "", "| Metric | Score |", "|--------|-------|",
        f"| Guard Retention | {summary.get('guard_retention_score', '-')}/10 |",
        f"| Positional Awareness | {summary.get('positional_awareness_score', '-')}/10 |",
        f"| Transition Quality | {summary.get('transition_quality_score', '-')}/10 |", "",
    ])
    lines.extend(["## Position Timeline", "",
        "| Time | Player A | Player B | Technique | Notes |",
        "|------|----------|----------|-----------|-------|",
    ])
    for entry in timeline:
        ts_sec = entry.get("timestamp_sec", 0)
        ts_str = format_timestamp(ts_sec)
        if video_url and extract_youtube_id(video_url):
            ts_link = f"[**{ts_str}**]({youtube_timestamp_url(video_url, ts_sec)})"
        else:
            ts_link = f"**{ts_str}**"
        pos_a = pos_map.get(entry.get("player_a_position", ""), {}).get("name", "?")
        pos_b = pos_map.get(entry.get("player_b_position", ""), {}).get("name", "?")
        tech = entry.get("active_technique") or ""
        notes = entry.get("notes", "")
        tip = entry.get("coaching_tip") or ""
        note_text = notes
        if tip:
            note_text += f" *Tip: {tip}*"
        lines.append(f"| {ts_link} | [[{pos_a}]] | [[{pos_b}]] | {tech} | {note_text} |")
    lines.append("")
    if summary.get("overall_notes"):
        lines.extend(["## Overall Notes", "", summary["overall_notes"], ""])

    ROLL_LOG_DIR.mkdir(exist_ok=True)
    filepath = ROLL_LOG_DIR / f"{time.strftime('%Y-%m-%d')} - {video_name} (app).md"
    filepath.write_text("\n".join(lines))
    return str(filepath)


# ─── App ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="BJJ Rolling Analyser", page_icon="🥋", layout="wide")

    st.markdown("""
    <style>
    .stApp { background-color: #0B0C0F; }
    .score-box { background:#12141A; border:1px solid #1E2030; border-radius:12px; padding:16px; text-align:center; }
    .score-value { font-size:36px; font-weight:700; margin:0; }
    .score-label { font-size:12px; color:#9CA3AF; text-transform:uppercase; letter-spacing:0.08em; }
    .score-reason { font-size:12px; color:#6B7280; margin-top:6px; line-height:1.4; }
    .timeline-bar { font-size:24px; letter-spacing:2px; line-height:1.8; }
    .legend-row { display:flex; flex-wrap:wrap; gap:12px; margin-top:6px; }
    .legend-pill { display:inline-flex; align-items:center; gap:4px; font-size:12px; color:#9CA3AF; }
    .seek-btn { color:#4A90D9; cursor:pointer; text-decoration:underline; font-weight:700; font-size:16px; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🥋 BJJ Rolling Analyser")
    st.caption("Analyse rolling footage with AI — free & local")

    taxonomy = load_taxonomy()

    # ─── Sidebar (simplified)
    with st.sidebar:
        st.header("Settings")
        player_name = st.text_input("Player name", value="Greig")
        video_name = st.text_input("Roll name", value="", placeholder="e.g. Tuesday Open Mat")

        with st.expander("Advanced", expanded=False):
            groq_key = st.text_input("Groq API Key", type="password", placeholder="gsk_...")
            st.caption("Free from [console.groq.com/keys](https://console.groq.com/keys)")
            st.divider()
            if st.button("📋 Copy AI Studio Prompt"):
                st.session_state["show_prompt"] = True

    if st.session_state.get("show_prompt"):
        with st.expander("Analysis Prompt (copy to AI Studio)", expanded=True):
            st.code(build_prompt(taxonomy), language=None)

    # ─── State
    json_input = ""
    analyse_btn = False
    video_url = ""

    # ─── Tabs (simplified: main analysis + position map + advanced)
    tab_auto, tab_graph, tab_advanced = st.tabs([
        "🤖 Analyse Video", "🗺️ Position Map", "⚙️ Advanced"
    ])

    # ━━━ TAB: Analyse Video ━━━
    with tab_auto:
        input_method = st.radio("Video source", ["YouTube URL", "Upload file"], horizontal=True)

        yt_url_input = ""
        uploaded_video = None

        if input_method == "YouTube URL":
            yt_url_input = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...", key="yt_auto_url")
            if yt_url_input:
                video_url = yt_url_input
        else:
            uploaded_video = st.file_uploader("Upload video file", type=["mp4", "mov", "avi", "mkv"])

        # Player identification
        st.markdown("#### Identify the Players")
        col_pa, col_pb = st.columns(2)
        with col_pa:
            player_description = st.text_input(
                "Player A (you)",
                placeholder="e.g. 'white gi', 'blue shorts, no shirt'",
                help="Describe your appearance so the model tracks you consistently.",
            )
        with col_pb:
            player_b_description = st.text_input(
                "Player B (opponent)",
                placeholder="e.g. 'black gi', 'red rash guard'",
                help="Describe your training partner.",
            )

        col_int, col_max = st.columns(2)
        with col_int:
            auto_interval = st.slider("Sample every N seconds", 3, 15, 5)
        with col_max:
            auto_max = st.slider("Max frames", 10, 80, 30)

        has_video = bool(uploaded_video) or bool(yt_url_input)
        auto_btn = st.button("🚀 Analyse Video", type="primary", use_container_width=True, disabled=not (has_video and groq_key))

        if not groq_key:
            st.info("Enter your Groq API key in **Settings > Advanced** in the sidebar.")

        if auto_btn and has_video and groq_key:
            import tempfile
            tmp_path = None
            dl_error = None

            if input_method == "YouTube URL" and yt_url_input:
                with st.spinner("Downloading YouTube video..."):
                    try:
                        import subprocess
                        tmp_dir = tempfile.mkdtemp(prefix="bjj_dl_")
                        out_template = os.path.join(tmp_dir, "video.mp4")
                        result = subprocess.run(
                            ["yt-dlp", "-f", "best[height<=480]", "--max-filesize", "50M",
                             "-o", out_template, "--no-warnings", "--quiet", "--force-overwrites",
                             yt_url_input],
                            capture_output=True, text=True, timeout=120)
                        if result.returncode != 0:
                            result = subprocess.run(
                                ["yt-dlp", "-f", "best[height<=480]", "--max-filesize", "50M",
                                 "--cookies-from-browser", "chrome", "-o", out_template,
                                 "--no-warnings", "--quiet", "--force-overwrites", yt_url_input],
                                capture_output=True, text=True, timeout=120)
                        downloaded = [f for f in os.listdir(tmp_dir) if os.path.isfile(os.path.join(tmp_dir, f))]
                        if result.returncode != 0 or not downloaded:
                            dl_error = f"Failed to download video. {result.stderr[:200]}"
                        else:
                            tmp_path = os.path.join(tmp_dir, downloaded[0])
                    except FileNotFoundError:
                        dl_error = "yt-dlp not installed. Run: brew install yt-dlp"
                    except subprocess.TimeoutExpired:
                        dl_error = "Download timed out. Try a shorter video."
            elif uploaded_video:
                video_bytes = uploaded_video.read()
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(video_bytes)
                    tmp_path = tmp.name
                # Save video bytes for playback
                st.session_state["uploaded_video_bytes"] = video_bytes

            if dl_error:
                st.error(dl_error)
            elif tmp_path:
                # Save video bytes for playback before analysis deletes the file
                if not video_url:  # Uploaded file — save bytes for playback
                    with open(tmp_path, "rb") as vf:
                        st.session_state["uploaded_video_bytes"] = vf.read()

                data, error = run_groq_analysis(tmp_path, player_name, auto_interval, auto_max, groq_key, taxonomy, player_description, player_b_description)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                if error:
                    st.error(error)
                if data and data.get("timeline"):
                    json_input = json.dumps(data)
                    analyse_btn = True
                    st.session_state["auto_result"] = json_input
                    st.session_state["video_url"] = video_url

        if st.session_state.get("auto_result") and not analyse_btn:
            json_input = st.session_state["auto_result"]
            analyse_btn = True
            video_url = st.session_state.get("video_url", "")

    # ━━━ TAB: Position Map ━━━
    with tab_graph:
        st.markdown("### BJJ Position Map")
        st.caption(f"{len(taxonomy['positions'])} positions · {len(taxonomy['valid_transitions'])} transitions")

        if not HAS_AGRAPH:
            st.warning("Interactive graph requires `streamlit-agraph`. Install with: `pip install streamlit-agraph`")
            st.info("The position map works locally but may not be available on Streamlit Cloud.")
            # Show a simple text-based position list instead
            for cat_id, cat in taxonomy["categories"].items():
                colour = CAT_COLOURS.get(cat["label"], "#666")
                positions = [p for p in taxonomy["positions"] if p["category"] == cat_id]
                with st.expander(f"{cat['label']} ({len(positions)} positions)"):
                    for p in positions:
                        st.markdown(f"- **{p['name']}** — {p.get('visual_cues', '')}")
        else:

            all_cats = list(taxonomy["categories"].keys())
            cat_labels = {k: v["label"] for k, v in taxonomy["categories"].items()}
            selected_cats = st.multiselect("Filter by category", options=all_cats, default=all_cats,
                                           format_func=lambda x: cat_labels.get(x, x))

            pos_map = {p["id"]: p for p in taxonomy["positions"]}
            jsx_techniques = load_jsx_techniques()
            yt_links = load_jsx_youtube_links()

            analysis_positions = Counter()
            analysis_edges = set()
            if st.session_state.get("auto_result") or st.session_state.get("data"):
                try:
                    adata = st.session_state.get("data") or json.loads(st.session_state.get("auto_result", "{}"))
                    atimeline = adata.get("timeline", [])
                    prev_pos = None
                    for entry in atimeline:
                        pos_a = entry.get("player_a_position", "")
                        if pos_a in pos_map:
                            analysis_positions[pos_a] += 1
                        if prev_pos and pos_a and prev_pos != pos_a:
                            analysis_edges.add((prev_pos, pos_a))
                        prev_pos = pos_a
                except (json.JSONDecodeError, TypeError):
                    pass

            nodes = []
            for pos in taxonomy["positions"]:
                if pos["category"] not in selected_cats:
                    continue
                cat = taxonomy["categories"][pos["category"]]
                colour = CAT_COLOURS.get(cat["label"], "#666")
                is_active = pos["id"] in analysis_positions
                size = 25 + (analysis_positions.get(pos["id"], 0) * 5) if is_active else 20
                size = min(size, 45)
                nodes.append(Node(id=pos["id"], label=pos["name"], size=size,
                    color=colour if is_active or not analysis_positions else f"{colour}44",
                    font={"color": "#E5E7EB" if is_active or not analysis_positions else "#4B5563", "size": 11},
                    borderWidth=3 if is_active else 1, borderWidthSelected=4))

            edges = []
            for a, b in taxonomy["valid_transitions"]:
                if a not in pos_map or b not in pos_map:
                    continue
                if pos_map[a]["category"] not in selected_cats or pos_map[b]["category"] not in selected_cats:
                    continue
                is_traversed = (a, b) in analysis_edges
                edges.append(Edge(source=a, target=b,
                    color="#D4A843" if is_traversed else "#1E2030",
                    width=3 if is_traversed else 1))

            config = Config(width="100%", height=600, directed=True, physics=True,
                hierarchical=False, nodeHighlightBehavior=True, highlightColor="#D4A843",
                collapsible=False, node={"highlightStrokeColor": "#D4A843"},
                link={"highlightColor": "#D4A843"}, backgroundColor="#0B0C0F")

            selected_node = agraph(nodes=nodes, edges=edges, config=config)

            # Legend (clean pill layout)
            legend_html = '<div class="legend-row">'
            for label, colour in CAT_COLOURS.items():
                legend_html += f'<span class="legend-pill"><span style="color:{colour}">●</span> {label}</span>'
            legend_html += '</div>'
            st.markdown(legend_html, unsafe_allow_html=True)

            if analysis_positions:
                st.caption(f"Highlighted: {sum(analysis_positions.values())} frames across {len(analysis_positions)} positions")

            if selected_node and selected_node in pos_map:
                pos = pos_map[selected_node]
                cat = taxonomy["categories"][pos["category"]]
                colour = CAT_COLOURS.get(cat["label"], "#666")

                st.markdown("---")
                st.markdown(f"### <span style='color:{colour}'>{pos['name']}</span>", unsafe_allow_html=True)
                st.caption(f"{cat['label']} · {pos['id']}")

                col_tech, col_trans = st.columns(2)
                with col_tech:
                    techniques = match_position_to_techniques(pos["name"], jsx_techniques)
                    if techniques:
                        st.markdown("**Techniques**")
                        for t in techniques:
                            st.markdown(f"- {t}")
                    else:
                        st.markdown("*No techniques listed*")
                with col_trans:
                    to_pos = [pos_map[b]["name"] for a, b in taxonomy["valid_transitions"] if a == selected_node and b in pos_map]
                    from_pos = [pos_map[a]["name"] for a, b in taxonomy["valid_transitions"] if b == selected_node and a in pos_map]
                    if to_pos:
                        st.markdown("**Transitions to**")
                        st.markdown(", ".join(to_pos))
                    if from_pos:
                        st.markdown("**Transitions from**")
                        st.markdown(", ".join(from_pos))

                yt_id_map = {
                    "standing_neutral": "standing", "standing_clinch": "clinch",
                    "closed_guard_bottom": "closedGuard", "half_guard_bottom": "halfGuard",
                    "open_guard": "openGuard", "butterfly_guard": "butterfly",
                    "de_la_riva": "dlr", "single_leg_x": "singleLegX",
                    "fifty_fifty": "fiftyFifty", "closed_guard_top": "closedGuardTop",
                    "half_guard_top": "halfGuardTop", "headquarters": "hq",
                    "side_control_top": "sideControl", "mount_top": "mount",
                    "back_mount": "backMount", "knee_on_belly": "kneeOnBelly",
                    "north_south_top": "northSouth", "turtle_top": "turtle",
                    "front_headlock": "frontHead", "side_control_bottom": "bottomSide",
                    "mount_bottom": "bottomMount", "turtle_bottom": "turtleBottom",
                    "back_taken": "backTaken",
                }
                jsx_id = yt_id_map.get(selected_node)
                if jsx_id and jsx_id in yt_links:
                    yt = yt_links[jsx_id]
                    st.markdown(f"📺 **[{yt['title']}]({yt['url']})**")

                if selected_node in analysis_positions:
                    st.info(f"Appeared **{analysis_positions[selected_node]}x** in loaded analysis")

    # ━━━ TAB: Advanced ━━━
    with tab_advanced:
        st.markdown("### Advanced Input")
        st.caption("For developers: paste JSON from AI Studio or upload analysis files.")

        adv_tab_paste, adv_tab_upload, adv_tab_prev = st.tabs(["📋 Paste JSON", "📁 Upload JSON", "📂 Previous"])

        with adv_tab_paste:
            pasted = st.text_area("Paste JSON response", height=200, placeholder='{"timeline": [...], "summary": {...}}')
            adv_video_url = st.text_input("Video URL (for timestamps)", placeholder="https://youtube.com/watch?v=...", key="adv_video_url")
            if st.button("🔍 Analyse JSON", type="primary", use_container_width=True) and pasted:
                json_input = pasted
                analyse_btn = True
                if adv_video_url:
                    video_url = adv_video_url

        with adv_tab_upload:
            uploaded = st.file_uploader("Upload JSON file", type=["json"])
            if uploaded:
                json_input = uploaded.read().decode("utf-8")
                analyse_btn = True

        with adv_tab_prev:
            json_files = sorted(Path(__file__).parent.parent.glob("assets/*.json"), reverse=True)
            if json_files:
                selected = st.selectbox("Load previous analysis", [f.name for f in json_files])
                if st.button("Load"):
                    json_input = (Path(__file__).parent.parent / "assets" / selected).read_text()
                    analyse_btn = True
            else:
                st.info("No previous analyses in assets/")

    # ━━━ RESULTS ━━━
    if analyse_btn and json_input:
        raw = json_input.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
            st.stop()

        timeline = data.get("timeline", [])
        summary = data.get("summary", {})
        pos_map = {p["id"]: p for p in taxonomy["positions"]}
        cat_map = taxonomy["categories"]

        if not timeline:
            st.warning("No timeline data found in JSON")
            st.stop()

        st.session_state["data"] = data
        if video_url:
            st.session_state["video_url"] = video_url

        st.markdown("---")

        # ─── Video embed (at top of results)
        vid_id = extract_youtube_id(video_url)
        if vid_id:
            st.video(video_url)
        elif st.session_state.get("uploaded_video_bytes"):
            st.video(st.session_state["uploaded_video_bytes"], format="video/mp4")

        # ─── Summary
        if summary.get("session_overview"):
            st.markdown("### Summary")
            st.markdown(summary["session_overview"])

        # ─── Scores (with reasons)
        st.markdown("### Scores")
        col1, col2, col3 = st.columns(3)
        scores = [
            ("Guard Retention", summary.get("guard_retention_score", "-"), summary.get("guard_retention_reason", "")),
            ("Positional Awareness", summary.get("positional_awareness_score", "-"), summary.get("positional_awareness_reason", "")),
            ("Transition Quality", summary.get("transition_quality_score", "-"), summary.get("transition_quality_reason", "")),
        ]
        for col, (label, score, reason) in zip([col1, col2, col3], scores):
            with col:
                colour = "#34C759" if isinstance(score, (int, float)) and score >= 7 else "#D4A843" if isinstance(score, (int, float)) and score >= 4 else "#E85D4A"
                reason_html = f'<p class="score-reason">{reason}</p>' if reason else ""
                st.markdown(f"""
                <div class="score-box">
                    <p class="score-value" style="color:{colour}">{score}<span style="font-size:16px;color:#6B7280">/10</span></p>
                    <p class="score-label">{label}</p>
                    {reason_html}
                </div>
                """, unsafe_allow_html=True)

        # ─── Top Improvements (prominent, right after scores)
        if summary.get("top_3_improvements"):
            st.markdown("### Top 3 Things to Work On")
            for i, imp in enumerate(summary["top_3_improvements"], 1):
                st.markdown(f"**{i}.** {imp}")

        # ─── Position Timeline Bar (with time markers)
        st.markdown("### Position Timeline")
        bar = ""
        for entry in timeline:
            pos_id = entry.get("player_a_position", "unclear")
            ts_sec = entry.get("timestamp_sec", 0)
            ts_label = format_timestamp(ts_sec)
            if pos_id in pos_map:
                cat_id = pos_map[pos_id]["category"]
                cat_label = cat_map.get(cat_id, {}).get("label", "")
                emoji = CAT_EMOJI.get(cat_label, "⬛")
            else:
                emoji = "⬛"
            bar += f'<span title="{ts_label} — {pos_map.get(pos_id, {}).get("name", pos_id)}">{emoji}</span>'

        st.markdown(f'<div class="timeline-bar">{bar}</div>', unsafe_allow_html=True)

        # Time markers
        if len(timeline) > 1:
            first_ts = timeline[0].get("timestamp_sec", 0)
            last_ts = timeline[-1].get("timestamp_sec", 0)
            mid_ts = timeline[len(timeline) // 2].get("timestamp_sec", 0)
            st.caption(f"{format_timestamp(first_ts)} {'·' * 20} {format_timestamp(mid_ts)} {'·' * 20} {format_timestamp(last_ts)}")

        # Legend
        legend_html = '<div class="legend-row">'
        for label, emoji in CAT_EMOJI.items():
            legend_html += f'<span class="legend-pill">{emoji} {label}</span>'
        legend_html += '</div>'
        st.markdown(legend_html, unsafe_allow_html=True)

        # ─── Position Distribution
        st.markdown("### Position Distribution")
        positions_a = [e.get("player_a_position", "unclear") for e in timeline]
        cat_counts = Counter()
        for pid in positions_a:
            if pid in pos_map:
                cat_id = pos_map[pid]["category"]
                cat_label = cat_map.get(cat_id, {}).get("label", cat_id)
                cat_counts[cat_label] += 1
        total = sum(cat_counts.values())
        for cat_label, count in cat_counts.most_common():
            pct = count / total if total else 0
            st.markdown(f"**{cat_label}** — {count} ({pct:.0%})")
            st.progress(pct)

        # ─── Key Moments
        if summary.get("key_moments"):
            st.markdown("### Key Moments")
            for km in summary["key_moments"]:
                ts = km.get("timestamp", "?")
                ts_sec = safe_parse_timestamp(ts)
                assessment = km.get("assessment", "neutral")
                icon = {"good": "✅", "excellent": "🌟", "perfect": "🏆", "bad": "⚠️", "neutral": "📌"}.get(assessment, "📌")
                if vid_id:
                    link = youtube_timestamp_url(video_url, ts_sec)
                    header = f"{icon} [{format_timestamp(ts_sec)}]({link}) — {km.get('description', '')}"
                else:
                    header = f"{icon} {format_timestamp(ts_sec)} — {km.get('description', '')}"
                st.markdown(header)
                if km.get("suggestion"):
                    st.caption(f"→ {km['suggestion']}")

        # ─── Frame-by-Frame (collapsible by position phase)
        st.markdown("### Frame-by-Frame Analysis")

        # Group frames by position category phase
        phases = []
        current_phase = None
        for entry in timeline:
            pos_id = entry.get("player_a_position", "unclear")
            cat_id = pos_map.get(pos_id, {}).get("category", "scramble")
            cat_label = cat_map.get(cat_id, {}).get("label", "Unknown")
            if cat_label != current_phase:
                phases.append({"label": cat_label, "frames": []})
                current_phase = cat_label
            phases[-1]["frames"].append(entry)

        for phase in phases:
            first_ts = format_timestamp(phase["frames"][0].get("timestamp_sec", 0))
            last_ts = format_timestamp(phase["frames"][-1].get("timestamp_sec", 0))
            colour = CAT_COLOURS.get(phase["label"], "#666")
            header = f'{phase["label"]} ({first_ts} - {last_ts}) · {len(phase["frames"])} frames'

            with st.expander(header, expanded=False):
                for entry in phase["frames"]:
                    ts_sec = entry.get("timestamp_sec", 0)
                    ts_str = format_timestamp(ts_sec)
                    pos_a_id = entry.get("player_a_position", "unclear")
                    pos_b_id = entry.get("player_b_position", "unclear")
                    pos_a = pos_map.get(pos_a_id, {}).get("name", pos_a_id)
                    pos_b = pos_map.get(pos_b_id, {}).get("name", pos_b_id)
                    tech = entry.get("active_technique") or "—"
                    notes = entry.get("notes", "")
                    tip = entry.get("coaching_tip") or ""
                    has_thumb = bool(entry.get("frame_base64"))

                    if has_thumb:
                        col_thumb, col_time, col_pos, col_detail = st.columns([1.5, 1, 2, 3.5])
                    else:
                        col_thumb = None
                        col_time, col_pos, col_detail = st.columns([1, 2, 4])

                    if col_thumb and has_thumb:
                        with col_thumb:
                            st.image(
                                f"data:image/jpeg;base64,{entry['frame_base64']}",
                                width=150,
                                caption=ts_str,
                            )
                    with col_time:
                        if vid_id:
                            link = youtube_timestamp_url(video_url, ts_sec)
                            st.markdown(f"### [{ts_str}]({link})")
                        else:
                            st.markdown(f"### {ts_str}")
                    with col_pos:
                        st.markdown(f"<span style='color:{colour};font-weight:700'>{pos_a}</span>", unsafe_allow_html=True)
                        st.caption(f"vs {pos_b}")
                    with col_detail:
                        st.markdown(f"**{tech}** — {notes}")
                        reasoning = entry.get("visual_reasoning", "")
                        if reasoning:
                            st.caption(f"👁 {reasoning}")
                        if tip:
                            st.info(f"💡 {tip}")
                    st.divider()

        # ─── Strengths
        if summary.get("strengths_observed"):
            st.markdown("### Strengths")
            for s in summary["strengths_observed"]:
                st.markdown(f"✓ {s}")

        # ─── Coach's Notes
        if summary.get("overall_notes"):
            st.markdown("### Coach's Notes")
            st.markdown(summary["overall_notes"])

        # ─── Export
        st.divider()
        col_export, col_download = st.columns(2)
        with col_export:
            vname = video_name or "Analysis"
            if st.button("💾 Export to Obsidian Vault", use_container_width=True):
                path = export_to_obsidian(data, player_name, vname, video_url)
                st.success(f"Saved to: {path}")
        with col_download:
            st.download_button("📥 Download JSON", data=json.dumps(data, indent=2),
                file_name=f"bjj_analysis_{time.strftime('%Y%m%d')}.json",
                mime="application/json", use_container_width=True)


if __name__ == "__main__":
    main()
