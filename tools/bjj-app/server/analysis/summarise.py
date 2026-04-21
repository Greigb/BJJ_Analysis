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


_REQUIRED_SCORES = ("guard_retention", "positional_awareness", "transition_quality")


def _clamp_score(value) -> int:
    # Reject bool explicitly — isinstance(True, int) is True in Python, and
    # silently interpreting True as score=1 is surprising.
    if isinstance(value, bool):
        raise SummaryResponseError(f"score must not be a bool: {value!r}")
    if not isinstance(value, (int, float)):
        raise SummaryResponseError(f"score is not a number: {value!r}")
    return max(0, min(10, int(round(value))))


def parse_summary_response(raw: str, valid_moment_ids: set[str]) -> dict:
    """Parse + validate Claude's summary JSON output. Raises SummaryResponseError."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SummaryResponseError(f"not valid JSON: {raw[:200]!r}") from exc

    if not isinstance(data, dict):
        raise SummaryResponseError(f"expected an object, got {type(data).__name__}")

    for key in ("summary", "scores", "top_improvements", "strengths", "key_moments"):
        if key not in data:
            raise SummaryResponseError(f"missing required key: {key}")

    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise SummaryResponseError("summary must be a non-empty string")

    scores = data["scores"]
    if not isinstance(scores, dict):
        raise SummaryResponseError("scores must be an object")
    for metric in _REQUIRED_SCORES:
        if metric not in scores:
            raise SummaryResponseError(f"missing score metric: {metric}")
    data["scores"] = {m: _clamp_score(scores[m]) for m in _REQUIRED_SCORES}

    ti = data["top_improvements"]
    if not isinstance(ti, list) or len(ti) != 3:
        raise SummaryResponseError("top_improvements must be a list of exactly 3 items")
    for item in ti:
        if not isinstance(item, str) or not item.strip():
            raise SummaryResponseError("each top_improvements item must be a non-empty string")

    st = data["strengths"]
    if not isinstance(st, list) or len(st) < 2 or len(st) > 4:
        raise SummaryResponseError("strengths must be a list of 2 to 4 items")
    for item in st:
        if not isinstance(item, str) or not item.strip():
            raise SummaryResponseError("each strengths item must be a non-empty string")

    km = data["key_moments"]
    if not isinstance(km, list) or len(km) != 3:
        raise SummaryResponseError("key_moments must be a list of exactly 3 items")
    seen: set[str] = set()
    for entry in km:
        if not isinstance(entry, dict):
            raise SummaryResponseError("each key_moments entry must be an object")
        mid = entry.get("moment_id")
        note = entry.get("note")
        if not isinstance(mid, str) or not mid:
            raise SummaryResponseError("key_moments[*].moment_id must be a non-empty string")
        if mid in seen:
            raise SummaryResponseError(f"duplicate key_moments moment_id: {mid}")
        if mid not in valid_moment_ids:
            raise SummaryResponseError(f"key_moments references unknown moment_id: {mid}")
        if not isinstance(note, str) or not note.strip():
            raise SummaryResponseError("key_moments[*].note must be a non-empty string")
        seen.add(mid)

    return data
