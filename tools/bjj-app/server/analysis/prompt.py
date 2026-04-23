"""Prompt construction for Claude single-frame BJJ analysis.

Kept separate from `claude_cli.py` so prompt changes are testable without
spawning subprocesses, and so the cache key (prompt_hash) is stable across
changes that don't affect the prompt text.
"""
from __future__ import annotations

import json
from pathlib import Path

from server.analysis.positions_vault import PositionNote
from server.analysis.techniques_vault import TechniqueNote


def _system_preamble(player_a_name: str, player_b_name: str) -> str:
    return (
        "You are a BJJ (Brazilian Jiu-Jitsu) position classifier. "
        "You will be shown one frame from a grappling roll between two practitioners: "
        f"{player_a_name} (referred to as player_a in the output) and "
        f"{player_b_name} (referred to as player_b in the output). "
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
    '  "player_a": {"position": "<taxonomy position id>", "confidence": <0..1>},\n'
    '  "player_b": {"position": "<taxonomy position id>", "confidence": <0..1>},\n'
    '  "description": "<one paragraph describing the moment>",\n'
    '  "coach_tip":   "<one actionable sentence for player_a>"\n'
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
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
) -> str:
    """Construct the single-frame classification prompt. Deterministic."""
    if not frame_path.exists():
        raise FileNotFoundError(frame_path)

    taxonomy = compress_taxonomy(taxonomy_path)
    return (
        f"{_system_preamble(player_a_name, player_b_name)}\n\n"
        f"{taxonomy}\n\n"
        f"Frame timestamp (seconds into the roll): {timestamp_s}\n"
        f"Image to analyse: @{frame_path}\n\n"
        f"{_SCHEMA_HINT}"
    )


class SectionResponseError(Exception):
    """Raised when Claude's section narrative output fails schema validation."""


_SECTION_SCHEMA_HINT = (
    'Output ONE JSON object and nothing else. No prose outside JSON. No markdown fences.\n'
    '{\n'
    '  "narrative": "<one paragraph, 2-5 sentences>",\n'
    '  "coach_tip": "<one actionable sentence for player_a>"\n'
    '}'
)


_GROUNDING_HEADER_POSITIONS_ONLY = (
    "Canonical BJJ positions — use this exact vocabulary and these visual cues "
    "when identifying what you see in the frames:"
)

_GROUNDING_HEADER_WITH_TECHNIQUES = (
    "Canonical BJJ positions — use this exact vocabulary when identifying "
    "what you see in the frames. Techniques commonly seen from each position "
    "are listed inline under their source position:"
)

_TECHNIQUE_DETAIL_HEADER = (
    "Technique detail — how to recognise each mid-execution:"
)


def _build_grounding_block(
    positions: list[PositionNote],
    techniques: list[TechniqueNote] | None = None,
    techniques_mode: str = "names",
) -> str:
    """Render a combined positions + techniques reference block for the section prompt.

    Positions preserve input order (caller controls taxonomy sort). Each
    position bullet optionally gets a nested sub-line listing technique names
    whose `used_from_position_ids` contains that position. Empty `positions`
    with no renderable `how_to_identify` returns an empty string — caller uses
    that as the signal to omit the whole block.

    `techniques_mode="names"` emits only the inline names sub-line.
    `techniques_mode="names+bodies"` appends a second block with each
    technique's `how_to_identify` body (heavier token cost; used by the eval
    harness's m10-techniques-bodies variant).
    """
    techniques = techniques or []

    # Index techniques by position for O(1) lookup per bullet.
    by_position: dict[str, list[TechniqueNote]] = {}
    for t in techniques:
        for pid in t["used_from_position_ids"]:
            by_position.setdefault(pid, []).append(t)

    position_bullets: list[str] = []
    for p in positions:
        body = (p.get("how_to_identify") or "").strip()
        if not body:
            continue
        flat = " ".join(body.split())
        position_bullets.append(f"- {p['name']} ({p['position_id']}): {flat}")
        nested = by_position.get(p["position_id"], [])
        if nested:
            names = ", ".join(t["name"] for t in nested)
            position_bullets.append(f"  Techniques from here: {names}")

    if not position_bullets:
        return ""

    header = (
        _GROUNDING_HEADER_WITH_TECHNIQUES if any(by_position.values())
        else _GROUNDING_HEADER_POSITIONS_ONLY
    )
    parts = [header + "\n" + "\n".join(position_bullets)]

    if techniques_mode == "names+bodies" and techniques:
        detail_lines: list[str] = []
        seen: set[str] = set()
        for t in techniques:
            if t["technique_id"] in seen:
                continue
            body = (t.get("how_to_identify") or "").strip()
            if not body:
                continue
            seen.add(t["technique_id"])
            flat = " ".join(body.split())
            detail_lines.append(f"- {t['name']} ({t['technique_id']}): {flat}")
        if detail_lines:
            parts.append(_TECHNIQUE_DETAIL_HEADER + "\n" + "\n".join(detail_lines))

    return "\n\n".join(parts)


def build_section_prompt(
    *,
    start_s: float,
    end_s: float,
    frame_paths: list[Path],
    timestamps: list[float],
    player_a_name: str,
    player_b_name: str,
    player_a_description: str | None = None,
    player_b_description: str | None = None,
    positions: list[PositionNote] | None = None,
    techniques: list[TechniqueNote] | None = None,
    techniques_mode: str = "names",
) -> str:
    """Build the multi-image section narrative prompt.

    Caller must have already written the frames to disk. `frame_paths` and
    `timestamps` are parallel lists in chronological order.

    `player_a_description` / `player_b_description`, when provided, are short
    visual-identification hints (gi colour, hair, build) that help Claude
    consistently tag the same person as player_a across frames.

    `positions`, when provided, is an ordered list of canonical BJJ positions
    (typically taxonomy-category-ordered). Their `how_to_identify` bodies are
    rendered into a reference block inserted BEFORE the guidance sentence so
    Claude has the canonical vocabulary in front of it when the instruction
    "use standard BJJ vocabulary" is given. `None` or `[]` means M9b behaviour
    (no grounding block).
    """
    if len(frame_paths) != len(timestamps):
        raise ValueError(
            f"frame_paths ({len(frame_paths)}) and timestamps "
            f"({len(timestamps)}) must be same length"
        )
    if not frame_paths:
        raise ValueError("build_section_prompt requires at least one frame")

    duration_s = round(end_s - start_s, 2)
    preamble = (
        f"You are analysing a Brazilian Jiu-Jitsu sequence between "
        f"{player_a_name} (player_a in output) and {player_b_name} (player_b in output)."
    )

    ident_lines: list[str] = []
    a_desc = (player_a_description or "").strip()
    b_desc = (player_b_description or "").strip()
    if a_desc or b_desc:
        ident_lines.append(
            "Use these appearance hints to keep player tagging consistent across frames:"
        )
        if a_desc:
            ident_lines.append(f"- player_a ({player_a_name}): {a_desc}")
        if b_desc:
            ident_lines.append(f"- player_b ({player_b_name}): {b_desc}")
    identification = "\n".join(ident_lines)

    intro = (
        f"Below are {len(frame_paths)} chronologically ordered frames spanning "
        f"{duration_s}s of footage. Review all frames as one continuous sequence "
        f"and describe what happens."
    )
    frame_lines = [
        f"Frame {i + 1} @t={timestamps[i]}s: @{frame_paths[i]}"
        for i in range(len(frame_paths))
    ]
    guidance = (
        "Describe the positions, transitions, who initiates what, and where the "
        "sequence ends. Use standard BJJ vocabulary (e.g. \"closed guard bottom\", "
        "\"passes half guard to side control\", \"triangle attempt\"). Follow with "
        "one actionable coach tip directed at player_a."
    )
    parts = [preamble]
    if identification:
        parts.append(identification)
    parts.extend([intro, "\n".join(frame_lines)])
    if positions:
        reference = _build_grounding_block(positions, techniques, techniques_mode)
        if reference:
            parts.append(reference)
    parts.extend([guidance, _SECTION_SCHEMA_HINT])
    return "\n\n".join(parts)


def parse_section_response(raw: str) -> dict:
    """Strict JSON parse + schema validation. Raises SectionResponseError on bad input."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SectionResponseError(f"not valid JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise SectionResponseError(
            f"expected an object, got {type(data).__name__}"
        )
    for key in ("narrative", "coach_tip"):
        if key not in data:
            raise SectionResponseError(f"missing required key: {key}")
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            raise SectionResponseError(f"{key} must be a non-empty string")
    return {"narrative": data["narrative"].strip(), "coach_tip": data["coach_tip"].strip()}
