"""Prompt construction for Claude single-frame BJJ analysis.

Kept separate from `claude_cli.py` so prompt changes are testable without
spawning subprocesses, and so the cache key (prompt_hash) is stable across
changes that don't affect the prompt text.
"""
from __future__ import annotations

import json
from pathlib import Path

_SYSTEM_PREAMBLE = (
    "You are a BJJ (Brazilian Jiu-Jitsu) position classifier. "
    "You will be shown one frame from a grappling roll between two practitioners: "
    "Greig (the white belt we are coaching) and Anthony (his training partner). "
    "Identify each player's current position using ONLY the position ids listed in "
    "the taxonomy below. If you are unsure between two positions, pick the more "
    "specific one. Confidence is a float in [0, 1] reflecting how confident you "
    "are that the chosen position id is correct.\n\n"
    "Output ONE JSON object and nothing else. No prose, no markdown fences."
)

_SCHEMA_HINT = (
    'Output JSON schema:\n'
    '{\n'
    '  "timestamp": <float, seconds>,\n'
    '  "greig":   {"position": "<taxonomy position id>", "confidence": <0..1>},\n'
    '  "anthony": {"position": "<taxonomy position id>", "confidence": <0..1>},\n'
    '  "description": "<one paragraph describing the moment>",\n'
    '  "coach_tip":   "<one actionable sentence for Greig>"\n'
    '}'
)


def compress_taxonomy(taxonomy_path: Path) -> str:
    """Return a short human-readable description of categories + positions.

    Deterministic — same input file produces identical output.
    """
    data = json.loads(taxonomy_path.read_text())

    lines: list[str] = ["Categories:"]
    for cat_id, cat in sorted(data["categories"].items()):
        lines.append(f"  {cat_id} ({cat['label']}): {cat['visual_cues']}")

    lines.append("")
    lines.append("Positions (use these ids exactly):")
    for p in sorted(data["positions"], key=lambda x: x["id"]):
        lines.append(f"  {p['id']} — {p['name']} [{p['category']}]: {p['visual_cues']}")

    return "\n".join(lines)


def build_prompt(
    frame_path: Path,
    taxonomy_path: Path,
    timestamp_s: float,
) -> str:
    """Construct the single-frame classification prompt. Deterministic."""
    if not frame_path.exists():
        raise FileNotFoundError(frame_path)

    taxonomy = compress_taxonomy(taxonomy_path)
    return (
        f"{_SYSTEM_PREAMBLE}\n\n"
        f"{taxonomy}\n\n"
        f"Frame timestamp (seconds into the roll): {timestamp_s}\n"
        f"Image to analyse: @{frame_path}\n\n"
        f"{_SCHEMA_HINT}"
    )
