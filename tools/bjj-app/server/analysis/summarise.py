"""Pure helpers for the summary step — no IO, no subprocess.

- build_summary_prompt: assembles the Claude coach-summary prompt.
- parse_summary_response: validates Claude's JSON output.
- compute_distribution: counts positions + builds the timeline bar data.
"""
from __future__ import annotations

import json


class SummaryResponseError(Exception):
    """Raised when Claude's summary output fails schema or reference validation."""


CATEGORY_EMOJI: dict[str, str] = {
    "standing":          "⬜",
    "guard_bottom":      "🟦",
    "guard_top":         "🟨",
    "dominant_top":      "🟩",
    "inferior_bottom":   "🟥",
    "leg_entanglement":  "🟫",
    "scramble":          "🟪",
}


def compute_distribution(
    analyses: list[dict],
    categories: list[dict],
) -> dict:
    """Compute timeline + category counts + percentages from analyses.

    Only considers rows where `player == "a"` (the person being coached).
    """
    player_a_only = [a for a in analyses if a.get("player") == "a"]
    if not player_a_only:
        return {"timeline": [], "counts": {}, "percentages": {}}

    timeline: list[str] = [a["category"] for a in player_a_only]

    counts: dict[str, int] = {}
    for cat in timeline:
        counts[cat] = counts.get(cat, 0) + 1

    total = sum(counts.values())
    percentages: dict[str, int] = {
        cat: round((n / total) * 100) for cat, n in counts.items()
    }

    return {"timeline": timeline, "counts": counts, "percentages": percentages}


_OUTPUT_SCHEMA_HINT = (
    'Output ONE JSON object with this exact shape — no prose, no markdown fences:\n'
    '{\n'
    '  "summary": "<one-sentence summary>",\n'
    '  "scores": {\n'
    '    "guard_retention": <integer 0..10>,\n'
    '    "positional_awareness": <integer 0..10>,\n'
    '    "transition_quality": <integer 0..10>\n'
    '  },\n'
    '  "top_improvements": ["<sentence>", "<sentence>", "<sentence>"],\n'
    '  "strengths": ["<short phrase>", ...],\n'
    '  "key_moments": [\n'
    '    {"moment_id": "<from the list above>", "note": "<brief pointer sentence>"},\n'
    '    {"moment_id": "<...>", "note": "<...>"},\n'
    '    {"moment_id": "<...>", "note": "<...>"}\n'
    '  ]\n'
    '}'
)


def _format_mm_ss(seconds: float) -> str:
    total = int(round(seconds))
    m = total // 60
    s = total % 60
    return f"{m}:{s:02d}"


def build_summary_prompt(
    roll_row: dict,
    moment_rows: list[dict],
    analyses_by_moment: dict[str, list[dict]],
    annotations_by_moment: dict[str, list[dict]],
) -> str:
    """Construct the summary prompt for Claude."""
    a_name = roll_row["player_a_name"]
    b_name = roll_row["player_b_name"]
    duration_s = roll_row.get("duration_s") or 0.0
    date = roll_row.get("date", "")

    preamble = (
        f"You are a BJJ coach reviewing a roll. Analyse the sequence below and produce "
        f"a concise coaching report. The practitioner is {a_name} (the person being coached); "
        f"{b_name} is their partner."
    )
    meta = (
        f"Roll metadata:\n"
        f"- Duration: {_format_mm_ss(duration_s)}\n"
        f"- Date: {date}\n"
        f"- Total moments analysed: {sum(1 for m in moment_rows if analyses_by_moment.get(m['id']))}"
    )

    moment_lines: list[str] = []
    for m in moment_rows:
        rows = analyses_by_moment.get(m["id"], [])
        if not rows:
            continue
        a_row = next((r for r in rows if r["player"] == "a"), None)
        b_row = next((r for r in rows if r["player"] == "b"), None)
        if a_row is None or b_row is None:
            continue
        mm_ss = _format_mm_ss(m["timestamp_s"])
        a_conf = int(round((a_row.get("confidence") or 0.0) * 100))
        description = (a_row.get("description") or "").strip()
        coach_tip = (a_row.get("coach_tip") or "").strip()
        moment_lines.append(
            f"- {mm_ss} moment_id={m['id']} — "
            f"{a_name}: {a_row['position_id']} ({a_conf}%); "
            f"{b_name}: {b_row['position_id']}."
            + (f"\n  {description}" if description else "")
            + (f"\n  Coach tip: {coach_tip}" if coach_tip else "")
        )

    moments_block = "Per-moment analyses (chronological):\n" + "\n".join(moment_lines) if moment_lines else \
        "Per-moment analyses (chronological):\n(no moments analysed)"

    annotation_lines: list[str] = []
    for m in moment_rows:
        for ann in annotations_by_moment.get(m["id"], []):
            mm_ss = _format_mm_ss(m["timestamp_s"])
            body = ann["body"].replace("\n", " ").strip()
            annotation_lines.append(f"- {mm_ss} moment_id={m['id']}: \"{body}\"")

    annotations_block = "User's own notes on specific moments:\n" + "\n".join(annotation_lines) if annotation_lines else ""

    parts = [preamble, meta, moments_block]
    if annotations_block:
        parts.append(annotations_block)
    parts.append(_OUTPUT_SCHEMA_HINT)

    return "\n\n".join(parts)


def parse_summary_response(raw: str, valid_moment_ids: set[str]) -> dict:
    """Parse + validate Claude's summary JSON output. (stub — full impl in next step)"""
    raise NotImplementedError
