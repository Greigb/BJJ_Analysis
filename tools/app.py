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
from streamlit_agraph import agraph, Node, Edge, Config

# Add tools dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"
ROLL_LOG_DIR = Path(__file__).parent.parent / "Roll Log"

# ─── Taxonomy ─────────────────────────────────────────────────────────────────

@st.cache_data
def load_taxonomy():
    with open(TAXONOMY_PATH) as f:
        return json.load(f)


def get_position_ids(taxonomy):
    """Build formatted position ID list for the prompt."""
    groups = {}
    for pos in taxonomy["positions"]:
        cat = taxonomy["categories"][pos["category"]]["label"]
        groups.setdefault(cat, []).append(pos["id"])
    lines = []
    for cat, ids in groups.items():
        lines.append(f"**{cat}:** {', '.join(ids)}")
    return "\n".join(lines)


# ─── YouTube Helpers ──────────────────────────────────────────────────────────

def extract_youtube_id(url):
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


def youtube_embed_url(video_url, start_sec=0):
    vid_id = extract_youtube_id(video_url)
    if vid_id:
        return f"https://www.youtube.com/embed/{vid_id}?start={int(start_sec)}&autoplay=1"
    return None


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

def run_groq_analysis(video_path, player_name, interval, max_frames, groq_key, taxonomy):
    """Run fully automated Groq analysis on a video file. Returns (data, error)."""
    try:
        import cv2
        from PIL import Image
        from groq import Groq
    except ImportError as e:
        return None, f"Missing dependency: {e}. Install with: pip install groq opencv-python Pillow"

    taxonomy_str = build_taxonomy_string(taxonomy)
    system_prompt = f"""You are an expert Brazilian Jiu-Jitsu analyst with black belt-level knowledge.
You are analysing keyframes extracted from a rolling/sparring session.

POSITION TAXONOMY — use ONLY these position IDs:
{taxonomy_str}

For EACH frame image provided, return a JSON object:
{{
  "frame_number": <int>,
  "timestamp_sec": <float>,
  "player_a_position": "<position_id from taxonomy>",
  "player_b_position": "<position_id from taxonomy>",
  "confidence": <float 0.0-1.0>,
  "active_technique": "<technique being attempted or null>",
  "notes": "<brief observation>",
  "coaching_tip": "<one actionable suggestion or null>"
}}

Be SPECIFIC with leg entanglements — identify the exact ashi garami / sankaku position."""

    batch_prompt_tpl = """Analyse these {{count}} sequential frames from a BJJ rolling session.
The frames are {{interval}} seconds apart, starting at timestamp {{start_time}}s.
Player A: {{player_name}}
Context: {{context}}
Return a JSON array with one object per frame. Return ONLY valid JSON, no markdown, no backticks."""

    summary_prompt_tpl = """You are a BJJ black belt coach. Here is position data from a rolling session:
{{timeline_json}}
Session duration: {{duration}}. Player: {{player_name}}.

Return a JSON object:
{{
  "session_overview": "<2-3 sentences>",
  "key_moments": [{{"timestamp": "<mm:ss>", "description": "<what>", "assessment": "<good/bad/neutral>", "suggestion": "<advice>"}}],
  "top_3_improvements": ["<1>", "<2>", "<3>"],
  "strengths_observed": ["<1>", "<2>"],
  "guard_retention_score": <1-10>,
  "positional_awareness_score": <1-10>,
  "transition_quality_score": <1-10>,
  "overall_notes": "<remarks>"
}}
Return ONLY valid JSON, no markdown, no backticks."""

    # Extract frames
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

    # Analyse in batches
    client = Groq(api_key=groq_key)
    model = "meta-llama/llama-4-scout-17b-16e-instruct"
    batch_size = 4
    timeline = []
    context = "This is the start of the session."
    progress = st.progress(0, text="Analysing frames...")

    for batch_start in range(0, len(frames), batch_size):
        batch = frames[batch_start:batch_start + batch_size]
        pct = (batch_start + len(batch)) / len(frames)
        progress.progress(pct, text=f"Analysing frames {batch[0]['frame_num']}-{batch[-1]['frame_num']}...")

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
            timeline.extend(results)
            if results:
                last = results[-1]
                context = f"At {last.get('timestamp_sec', '?')}s: Player A in {last.get('player_a_position', '?')}, Player B in {last.get('player_b_position', '?')}. {last.get('notes', '')}"
        except Exception as e:
            st.warning(f"Batch error: {str(e)[:100]}")

        if batch_start + batch_size < len(frames):
            time.sleep(3)

    progress.progress(1.0, text="Generating summary...")

    # Summary
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": summary_prompt_tpl
                .replace("{{timeline_json}}", json.dumps(timeline, indent=2))
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
    except Exception:
        summary = {"session_overview": "Summary generation failed", "overall_notes": ""}

    progress.empty()
    return {"timeline": timeline, "summary": summary, "duration_sec": duration}, None


def build_taxonomy_string(taxonomy):
    lines = []
    for pos in taxonomy["positions"]:
        cat = taxonomy["categories"][pos["category"]]["label"]
        lines.append(f'  "{pos["id"]}" — {pos["name"]} [{cat}]')
    return "\n".join(lines)


# ─── Graph Data Helpers ───────────────────────────────────────────────────────

@st.cache_data
def load_jsx_techniques():
    """Parse technique lists from the JSX taxonomy component."""
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
    """Parse YouTube links from the JSX graph component."""
    jsx_path = Path(__file__).parent / "components" / "bjj-position-graph.jsx"
    if not jsx_path.exists():
        return {}
    text = jsx_path.read_text()
    result = {}
    # Match: id: "xxx", ... yt: "url", ytTitle: "title"
    node_pattern = r'id:\s*"([^"]+)".*?yt:\s*"([^"]+)".*?ytTitle:\s*"([^"]+)"'
    for match in re.finditer(node_pattern, text, re.DOTALL):
        result[match.group(1)] = {"url": match.group(2), "title": match.group(3)}
    return result


def match_position_to_techniques(pos_name, jsx_techniques):
    """Fuzzy match a taxonomy position name to JSX technique list."""
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


# ─── Analysis Prompt ──────────────────────────────────────────────────────────

def build_prompt(taxonomy):
    position_ids = ", ".join(p["id"] for p in taxonomy["positions"])
    return f"""You are a BJJ black belt analyst. Analyse this rolling/sparring video.

Return ONLY a valid JSON object (no markdown, no backticks, no explanation), in this exact format:

{{
  "timeline": [
    {{
      "timestamp": "0:00",
      "timestamp_sec": 0,
      "player_a_position": "standing_neutral",
      "player_b_position": "standing_neutral",
      "active_technique": null,
      "notes": "Both players standing",
      "coaching_tip": null
    }}
  ],
  "summary": {{
    "session_overview": "2-3 sentence summary",
    "key_moments": [
      {{
        "timestamp": "0:00",
        "description": "what happened",
        "assessment": "good",
        "suggestion": "what to do differently"
      }}
    ],
    "top_3_improvements": ["improvement 1", "improvement 2", "improvement 3"],
    "strengths_observed": ["strength 1", "strength 2"],
    "guard_retention_score": 7,
    "positional_awareness_score": 6,
    "transition_quality_score": 5,
    "overall_notes": "coaching remarks"
  }}
}}

POSITION IDS — use ONLY these:

{get_position_ids(taxonomy)}

Be SPECIFIC with leg entanglements — identify the exact ashi garami / sankaku position.

Sample a moment every 10-15 seconds throughout the video. Track both players."""


# ─── Export to Obsidian ───────────────────────────────────────────────────────

def export_to_obsidian(data, player_name, video_name, video_url):
    """Export analysis to Obsidian vault Roll Log."""
    taxonomy = load_taxonomy()
    pos_map = {p["id"]: p for p in taxonomy["positions"]}
    cat_map = taxonomy["categories"]

    timeline = data.get("timeline", [])
    summary = data.get("summary", {})
    today = time.strftime("%Y-%m-%d")

    if timeline:
        last_ts = max(e.get("timestamp_sec", 0) for e in timeline)
        duration_str = f"{int(last_ts // 60)}:{int(last_ts % 60):02d}"
    else:
        duration_str = "unknown"

    lines = [
        "---",
        f"date: {today}",
        f"partner: ",
        f'duration: "{duration_str}"',
        f"frames_analysed: {len(timeline)}",
        f"guard_retention: {summary.get('guard_retention_score', '')}",
        f"positional_awareness: {summary.get('positional_awareness_score', '')}",
        f"transition_quality: {summary.get('transition_quality_score', '')}",
        f"method: streamlit-app",
        f"tags: [roll, app-analysis]",
        "---",
        "",
        f"# Roll Analysis - {video_name}",
        "",
        f"**Player:** {player_name}",
        f"**Duration:** {duration_str}",
        f"**Moments analysed:** {len(timeline)}",
    ]
    if video_url:
        lines.append(f"**Video:** [{video_url}]({video_url})")
    lines.append("")

    if summary.get("session_overview"):
        lines.extend(["## Summary", "", summary["session_overview"], ""])

    lines.extend([
        "## Scores", "",
        "| Metric | Score |",
        "|--------|-------|",
        f"| Guard Retention | {summary.get('guard_retention_score', '-')}/10 |",
        f"| Positional Awareness | {summary.get('positional_awareness_score', '-')}/10 |",
        f"| Transition Quality | {summary.get('transition_quality_score', '-')}/10 |",
        "",
    ])

    # Timeline
    lines.extend([
        "## Position Timeline", "",
        "| Time | Player A | Player B | Technique | Notes |",
        "|------|----------|----------|-----------|-------|",
    ])
    for entry in timeline:
        ts = entry.get("timestamp", "?")
        ts_sec = entry.get("timestamp_sec", 0)
        if video_url and extract_youtube_id(video_url):
            ts_link = f"[**{ts}**]({youtube_timestamp_url(video_url, ts_sec)})"
        else:
            ts_link = f"**{ts}**"
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

    if summary.get("overall_notes"):
        lines.extend(["## Overall Notes", "", summary["overall_notes"], ""])

    ROLL_LOG_DIR.mkdir(exist_ok=True)
    filename = f"{today} - {video_name} (app).md"
    filepath = ROLL_LOG_DIR / filename
    filepath.write_text("\n".join(lines))
    return str(filepath)


# ─── App ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="BJJ Rolling Analyser",
        page_icon="🥋",
        layout="wide",
    )

    # Custom CSS
    st.markdown("""
    <style>
    .stApp { background-color: #0B0C0F; }
    .score-box {
        background: #12141A;
        border: 1px solid #1E2030;
        border-radius: 12px;
        padding: 16px;
        text-align: center;
    }
    .score-value {
        font-size: 36px;
        font-weight: 700;
        margin: 0;
    }
    .score-label {
        font-size: 12px;
        color: #9CA3AF;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .timeline-bar {
        font-size: 24px;
        letter-spacing: 2px;
        line-height: 1.8;
    }
    .moment-card {
        background: #12141A;
        border: 1px solid #1E2030;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("🥋 BJJ Rolling Analyser")
    st.caption("Analyse rolling footage with AI — free & local")

    taxonomy = load_taxonomy()

    # ─── Sidebar
    with st.sidebar:
        st.header("Settings")
        player_name = st.text_input("Player name", value="Greig")
        video_name = st.text_input("Roll name", value="", placeholder="e.g. Tuesday Open Mat")
        video_url = st.text_input("YouTube URL (optional)", value="", placeholder="https://youtube.com/watch?v=...")

        st.divider()
        st.header("Groq API (free)")
        groq_key = st.text_input("Groq API Key", type="password", placeholder="gsk_...")
        st.caption("Free key from [console.groq.com/keys](https://console.groq.com/keys)")

        st.divider()
        if st.button("📋 Copy AI Studio Prompt"):
            st.session_state["show_prompt"] = True

    # ─── Prompt display
    if st.session_state.get("show_prompt"):
        with st.expander("Analysis Prompt (copy this to AI Studio)", expanded=True):
            st.code(build_prompt(taxonomy), language=None)

    # ─── Main input
    json_input = ""
    analyse_btn = False

    tab_auto, tab_graph, tab_paste, tab_upload, tab_previous = st.tabs([
        "🤖 Auto-Analyse Video", "🗺️ Position Map", "📋 Paste JSON", "📁 Upload JSON", "📂 Previous"
    ])

    with tab_auto:
        st.markdown("**Upload a video file** or **paste a YouTube link** — fully automated analysis with Groq (free).")

        input_method = st.radio("Video source", ["YouTube URL", "Upload file"], horizontal=True)

        yt_url_input = ""
        uploaded_video = None

        if input_method == "YouTube URL":
            yt_url_input = st.text_input(
                "YouTube URL",
                placeholder="https://www.youtube.com/watch?v=...",
                key="yt_auto_url",
            )
            if yt_url_input and not video_url:
                video_url = yt_url_input
        else:
            uploaded_video = st.file_uploader("Upload video file", type=["mp4", "mov", "avi", "mkv"])

        col_int, col_max = st.columns(2)
        with col_int:
            auto_interval = st.slider("Sample interval (seconds)", 3, 15, 5)
        with col_max:
            auto_max = st.slider("Max frames", 10, 80, 30)

        has_video = bool(uploaded_video) or bool(yt_url_input)
        auto_btn = st.button("🚀 Analyse Video", type="primary", use_container_width=True, disabled=not (has_video and groq_key))

        if not groq_key:
            st.info("Enter your free Groq API key in the sidebar to enable auto-analysis.")

        if auto_btn and has_video and groq_key:
            import tempfile
            tmp_path = None
            dl_error = None

            if input_method == "YouTube URL" and yt_url_input:
                # Download YouTube video
                with st.spinner("Downloading YouTube video..."):
                    try:
                        import subprocess
                        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                            tmp_path = tmp.name
                        result = subprocess.run(
                            ["yt-dlp", "-f", "best[height<=480]",
                             "--max-filesize", "50M",
                             "-o", tmp_path,
                             "--no-warnings", "--quiet",
                             yt_url_input],
                            capture_output=True, text=True, timeout=120,
                        )
                        if result.returncode != 0:
                            # Try with cookies from browser
                            result = subprocess.run(
                                ["yt-dlp", "-f", "best[height<=480]",
                                 "--max-filesize", "50M",
                                 "--cookies-from-browser", "chrome",
                                 "-o", tmp_path,
                                 "--no-warnings", "--quiet",
                                 yt_url_input],
                                capture_output=True, text=True, timeout=120,
                            )
                        if result.returncode != 0:
                            dl_error = f"Failed to download video. Error: {result.stderr[:200]}"
                            if tmp_path and os.path.exists(tmp_path):
                                os.unlink(tmp_path)
                            tmp_path = None
                    except FileNotFoundError:
                        dl_error = "yt-dlp not installed. Run: brew install yt-dlp"
                        tmp_path = None
                    except subprocess.TimeoutExpired:
                        dl_error = "Download timed out. Try a shorter video."
                        tmp_path = None

                if not video_url:
                    video_url = yt_url_input

            elif uploaded_video:
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(uploaded_video.read())
                    tmp_path = tmp.name

            if dl_error:
                st.error(dl_error)
            elif tmp_path:
                data, error = run_groq_analysis(tmp_path, player_name, auto_interval, auto_max, groq_key, taxonomy)
                os.unlink(tmp_path)

                if error:
                    st.error(error)
                elif data:
                    json_input = json.dumps(data)
                    analyse_btn = True
                    st.session_state["auto_result"] = json_input
                    if yt_url_input:
                        st.session_state["video_url"] = yt_url_input

        # Restore previous auto result
        if st.session_state.get("auto_result") and not analyse_btn:
            json_input = st.session_state["auto_result"]
            analyse_btn = True
            if st.session_state.get("video_url"):
                video_url = st.session_state["video_url"]

    with tab_graph:
        st.markdown("### BJJ Position Map")
        st.caption(f"{len(taxonomy['positions'])} positions · {len(taxonomy['valid_transitions'])} transitions")

        # Category filter
        all_cats = list(taxonomy["categories"].keys())
        cat_labels = {k: v["label"] for k, v in taxonomy["categories"].items()}

        selected_cats = st.multiselect(
            "Filter by category",
            options=all_cats,
            default=all_cats,
            format_func=lambda x: cat_labels.get(x, x),
        )

        # Build graph
        pos_map = {p["id"]: p for p in taxonomy["positions"]}
        jsx_techniques = load_jsx_techniques()
        yt_links = load_jsx_youtube_links()

        # Check if we have analysis data to highlight
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

        # Build nodes
        nodes = []
        for pos in taxonomy["positions"]:
            if pos["category"] not in selected_cats:
                continue
            cat = taxonomy["categories"][pos["category"]]
            colour = CAT_COLOURS.get(cat["label"], "#666")
            is_active = pos["id"] in analysis_positions
            size = 25 + (analysis_positions.get(pos["id"], 0) * 5) if is_active else 20
            size = min(size, 45)

            nodes.append(Node(
                id=pos["id"],
                label=pos["name"],
                size=size,
                color=colour if is_active or not analysis_positions else f"{colour}44",
                font={"color": "#E5E7EB" if is_active or not analysis_positions else "#4B5563", "size": 11},
                borderWidth=3 if is_active else 1,
                borderWidthSelected=4,
            ))

        # Build edges
        edges = []
        for a, b in taxonomy["valid_transitions"]:
            if a not in pos_map or b not in pos_map:
                continue
            if pos_map[a]["category"] not in selected_cats or pos_map[b]["category"] not in selected_cats:
                continue
            is_traversed = (a, b) in analysis_edges
            edges.append(Edge(
                source=a,
                target=b,
                color="#D4A843" if is_traversed else "#1E2030",
                width=3 if is_traversed else 1,
            ))

        # Graph config
        config = Config(
            width="100%",
            height=600,
            directed=True,
            physics=True,
            hierarchical=False,
            nodeHighlightBehavior=True,
            highlightColor="#D4A843",
            collapsible=False,
            node={"highlightStrokeColor": "#D4A843"},
            link={"highlightColor": "#D4A843"},
            backgroundColor="#0B0C0F",
        )

        # Render graph
        selected_node = agraph(nodes=nodes, edges=edges, config=config)

        # Legend
        legend_cols = st.columns(len(CAT_COLOURS))
        for col, (label, colour) in zip(legend_cols, CAT_COLOURS.items()):
            col.markdown(f"<span style='color:{colour}'>●</span> {label}", unsafe_allow_html=True)

        # Analysis overlay info
        if analysis_positions:
            st.caption(f"Highlighted: {sum(analysis_positions.values())} frames across {len(analysis_positions)} positions from loaded analysis")

        # Detail panel for selected node
        if selected_node and selected_node in pos_map:
            pos = pos_map[selected_node]
            cat = taxonomy["categories"][pos["category"]]
            colour = CAT_COLOURS.get(cat["label"], "#666")

            st.markdown("---")
            st.markdown(f"### <span style='color:{colour}'>{pos['name']}</span>", unsafe_allow_html=True)
            st.caption(f"Category: {cat['label']} · Position ID: {pos['id']}")

            col_tech, col_trans = st.columns(2)

            with col_tech:
                techniques = match_position_to_techniques(pos["name"], jsx_techniques)
                if techniques:
                    st.markdown("**Techniques**")
                    for t in techniques:
                        st.markdown(f"- {t}")
                else:
                    st.markdown("*No techniques listed yet*")

            with col_trans:
                # Transitions
                to_positions = [pos_map[b]["name"] for a, b in taxonomy["valid_transitions"]
                                if a == selected_node and b in pos_map]
                from_positions = [pos_map[a]["name"] for a, b in taxonomy["valid_transitions"]
                                  if b == selected_node and a in pos_map]

                if to_positions:
                    st.markdown("**Transitions to**")
                    st.markdown(", ".join(to_positions))
                if from_positions:
                    st.markdown("**Transitions from**")
                    st.markdown(", ".join(from_positions))

            # YouTube link
            # Try matching by node ID patterns
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
                st.markdown(f"**📺 [{yt['title']}]({yt['url']})**")

            # Analysis count
            if selected_node in analysis_positions:
                count = analysis_positions[selected_node]
                st.info(f"This position appeared **{count} time(s)** in the loaded analysis")

    with tab_paste:
        pasted = st.text_area(
            "Paste JSON response from AI Studio or other source",
            height=200,
            placeholder='{"timeline": [...], "summary": {...}}',
        )
        paste_btn = st.button("🔍 Analyse JSON", type="primary", use_container_width=True)
        if paste_btn and pasted:
            json_input = pasted
            analyse_btn = True

    with tab_upload:
        uploaded = st.file_uploader("Upload a JSON analysis file", type=["json"])
        if uploaded:
            json_input = uploaded.read().decode("utf-8")
            analyse_btn = True

    with tab_previous:
        json_files = sorted(Path(__file__).parent.parent.glob("assets/*.json"), reverse=True)
        if json_files:
            selected = st.selectbox("Load previous analysis", [f.name for f in json_files])
            if st.button("Load"):
                sel_path = Path(__file__).parent.parent / "assets" / selected
                json_input = sel_path.read_text()
                analyse_btn = True
        else:
            st.info("No previous analyses found in assets/")

    # ─── Process
    if analyse_btn and json_input:
        # Clean markdown fences
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

        # Store in session
        st.session_state["data"] = data
        st.session_state["video_url"] = video_url

        # ─── Video embed
        if video_url:
            vid_id = extract_youtube_id(video_url)
            if vid_id:
                st.video(video_url)

        # ─── Summary
        if summary.get("session_overview"):
            st.markdown(f"### Summary")
            st.markdown(summary["session_overview"])

        # ─── Scores
        st.markdown("### Scores")
        col1, col2, col3 = st.columns(3)
        scores = [
            ("Guard Retention", summary.get("guard_retention_score", "-")),
            ("Positional Awareness", summary.get("positional_awareness_score", "-")),
            ("Transition Quality", summary.get("transition_quality_score", "-")),
        ]
        for col, (label, score) in zip([col1, col2, col3], scores):
            with col:
                colour = "#34C759" if isinstance(score, (int, float)) and score >= 7 else "#D4A843" if isinstance(score, (int, float)) and score >= 4 else "#E85D4A"
                st.markdown(f"""
                <div class="score-box">
                    <p class="score-value" style="color:{colour}">{score}<span style="font-size:16px;color:#6B7280">/10</span></p>
                    <p class="score-label">{label}</p>
                </div>
                """, unsafe_allow_html=True)

        # ─── Position Timeline Bar
        st.markdown("### Position Timeline")
        bar = ""
        for entry in timeline:
            pos_id = entry.get("player_a_position", "unclear")
            if pos_id in pos_map:
                cat_id = pos_map[pos_id]["category"]
                cat_label = cat_map.get(cat_id, {}).get("label", "")
                bar += CAT_EMOJI.get(cat_label, "⬛")
            else:
                bar += "⬛"

        st.markdown(f'<div class="timeline-bar">{bar}</div>', unsafe_allow_html=True)

        legend_parts = [f'{emoji} {label}' for label, emoji in CAT_EMOJI.items()]
        st.caption(" · ".join(legend_parts))

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
            colour = CAT_COLOURS.get(cat_label, "#666")
            st.markdown(f"**{cat_label}** — {count} ({pct:.0%})")
            st.progress(pct)

        # ─── Timeline Detail
        st.markdown("### Frame-by-Frame")

        for i, entry in enumerate(timeline):
            ts = entry.get("timestamp", "?")
            ts_sec = entry.get("timestamp_sec", 0)
            pos_a_id = entry.get("player_a_position", "unclear")
            pos_b_id = entry.get("player_b_position", "unclear")
            pos_a = pos_map.get(pos_a_id, {}).get("name", pos_a_id)
            pos_b = pos_map.get(pos_b_id, {}).get("name", pos_b_id)
            cat_a = pos_map.get(pos_a_id, {}).get("category", "scramble")
            cat_label = cat_map.get(cat_a, {}).get("label", "")
            colour = CAT_COLOURS.get(cat_label, "#666")
            tech = entry.get("active_technique") or "—"
            notes = entry.get("notes", "")
            tip = entry.get("coaching_tip") or ""

            with st.container():
                col_time, col_pos, col_detail = st.columns([1, 2, 4])

                with col_time:
                    if video_url and extract_youtube_id(video_url):
                        link = youtube_timestamp_url(video_url, ts_sec)
                        st.markdown(f"### [{ts}]({link})")
                    else:
                        st.markdown(f"### {ts}")

                with col_pos:
                    st.markdown(f"<span style='color:{colour};font-weight:700'>{pos_a}</span>", unsafe_allow_html=True)
                    st.caption(f"vs {pos_b}")

                with col_detail:
                    st.markdown(f"**{tech}** — {notes}")
                    if tip:
                        st.info(f"💡 {tip}")

                st.divider()

        # ─── Key Moments
        if summary.get("key_moments"):
            st.markdown("### Key Moments")
            for km in summary["key_moments"]:
                ts = km.get("timestamp", "?")
                assessment = km.get("assessment", "neutral")
                icon = {"good": "✅", "excellent": "🌟", "perfect": "🏆", "bad": "⚠️", "neutral": "📌"}.get(assessment, "📌")
                if video_url and extract_youtube_id(video_url):
                    parts = ts.split(":")
                    ts_sec = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 0
                    link = youtube_timestamp_url(video_url, ts_sec)
                    header = f"{icon} [{ts}]({link}) — {km.get('description', '')}"
                else:
                    header = f"{icon} {ts} — {km.get('description', '')}"
                st.markdown(header)
                if km.get("suggestion"):
                    st.caption(f"→ {km['suggestion']}")

        # ─── Improvements & Strengths
        col_imp, col_str = st.columns(2)
        with col_imp:
            if summary.get("top_3_improvements"):
                st.markdown("### Top Improvements")
                for i, imp in enumerate(summary["top_3_improvements"], 1):
                    st.markdown(f"{i}. {imp}")

        with col_str:
            if summary.get("strengths_observed"):
                st.markdown("### Strengths")
                for s in summary["strengths_observed"]:
                    st.markdown(f"✓ {s}")

        # ─── Overall Notes
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
            st.download_button(
                "📥 Download JSON",
                data=json.dumps(data, indent=2),
                file_name=f"bjj_analysis_{time.strftime('%Y%m%d')}.json",
                mime="application/json",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
