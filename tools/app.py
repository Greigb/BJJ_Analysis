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
from pathlib import Path
from collections import Counter
from datetime import timedelta

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
        st.header("How to use")
        st.markdown("""
        1. Paste a **YouTube link** above
        2. Copy the **analysis prompt** below
        3. Go to [AI Studio](https://aistudio.google.com), link the video, paste the prompt
        4. Copy Gemini's **JSON response**
        5. Paste it in the JSON box and click **Analyse**
        """)

        st.divider()
        if st.button("📋 Copy Analysis Prompt"):
            st.session_state["show_prompt"] = True

    # ─── Prompt display
    if st.session_state.get("show_prompt"):
        with st.expander("Analysis Prompt (copy this to AI Studio)", expanded=True):
            st.code(build_prompt(taxonomy), language=None)

    # ─── Main input
    tab_paste, tab_upload, tab_previous = st.tabs(["📋 Paste JSON", "📁 Upload JSON File", "📂 Previous Analyses"])

    with tab_paste:
        json_input = st.text_area(
            "Paste Gemini JSON response here",
            height=200,
            placeholder='{"timeline": [...], "summary": {...}}',
        )
        analyse_btn = st.button("🔍 Analyse", type="primary", use_container_width=True)

    with tab_upload:
        uploaded = st.file_uploader("Upload a JSON analysis file", type=["json"])
        if uploaded:
            json_input = uploaded.read().decode("utf-8")
            analyse_btn = True

    with tab_previous:
        if ROLL_LOG_DIR.exists():
            json_files = sorted(Path(__file__).parent.parent.glob("assets/*.json"), reverse=True)
            if json_files:
                selected = st.selectbox("Load previous analysis", [f.name for f in json_files])
                if st.button("Load"):
                    sel_path = Path(__file__).parent.parent / "assets" / selected
                    json_input = sel_path.read_text()
                    analyse_btn = True
            else:
                st.info("No previous analyses found in assets/")
        else:
            st.info("No Roll Log directory found")

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
