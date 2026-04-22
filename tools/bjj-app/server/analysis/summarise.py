"""Pure helpers for the summary step — no IO, no subprocess.

- build_summary_prompt: assembles the Claude coach-summary prompt (sections in).
- parse_summary_response: validates Claude's JSON output.
"""
from __future__ import annotations

import json


class SummaryResponseError(Exception):
    """Raised when Claude's summary output fails schema or reference validation."""


_SCORING_RUBRIC = (
    "Scoring rubric (calibrate each score against the footage provided, not against BJJ "
    "practice as a whole — 10 means execution was reliable throughout THIS roll):\n"
    "- 0–3: needs focused work; frequent positional loss or stalled execution.\n"
    "- 4–6: developing; skill is emerging but inconsistent under pressure.\n"
    "- 7–10: reliable; consistent, technical execution against the partner in this footage.\n"
    "\n"
    "Per-metric definitions:\n"
    "- guard_retention: ability to recover / hold guard when pressured.\n"
    "- positional_awareness: reads the partner's posture and responds with the right frame / grip / shape.\n"
    "- transition_quality: technical fluency moving between positions (passes, sweeps, escapes)."
)


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
    '    {"section_id": "<from the list above>", "note": "<brief pointer sentence>"},\n'
    '    {"section_id": "<...>", "note": "<...>"},\n'
    '    {"section_id": "<...>", "note": "<...>"}\n'
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
    sections: list[dict],
    annotations_by_section: dict[str, list[dict]],
) -> str:
    """Construct the summary prompt for Claude (M9b section-based)."""
    a_name = roll_row["player_a_name"]
    b_name = roll_row["player_b_name"]
    duration_s = roll_row.get("duration_s") or 0.0
    date = roll_row.get("date", "")

    preamble = (
        f"You are a BJJ coach reviewing a roll. Analyse the sections below and produce "
        f"a concise coaching report. The practitioner is {a_name} (the person being coached); "
        f"{b_name} is their partner."
    )
    analysed_count = sum(1 for s in sections if (s.get("narrative") or "").strip())
    meta = (
        f"Roll metadata:\n"
        f"- Duration: {_format_mm_ss(duration_s)}\n"
        f"- Date: {date}\n"
        f"- Total sections analysed: {analysed_count}"
    )

    section_blocks: list[str] = []
    for s in sections:
        narrative = (s.get("narrative") or "").strip()
        if not narrative:
            continue
        start = _format_mm_ss(s["start_s"])
        end = _format_mm_ss(s["end_s"])
        coach_tip = (s.get("coach_tip") or "").strip()
        notes = annotations_by_section.get(s["id"], [])
        block = [
            f"Section section_id={s['id']} ({start} – {end}):",
            f"  Narrative: {narrative}",
        ]
        if coach_tip:
            block.append(f"  Coach tip: {coach_tip}")
        if notes:
            block.append(f"  {a_name}'s notes:")
            for note in notes:
                body = (note["body"] or "").replace("\n", " ").strip()
                block.append(f"    - {body}")
        section_blocks.append("\n".join(block))

    if section_blocks:
        sections_block = "Per-section analyses (chronological):\n" + "\n\n".join(section_blocks)
    else:
        sections_block = "Per-section analyses (chronological):\n(no sections analysed)"

    return "\n\n".join([preamble, meta, sections_block, _SCORING_RUBRIC, _OUTPUT_SCHEMA_HINT])


_REQUIRED_SCORES = ("guard_retention", "positional_awareness", "transition_quality")


def _clamp_score(value) -> int:
    if isinstance(value, bool):
        raise SummaryResponseError(f"score must not be a bool: {value!r}")
    if not isinstance(value, (int, float)):
        raise SummaryResponseError(f"score is not a number: {value!r}")
    return max(0, min(10, int(round(value))))


def parse_summary_response(raw: str, valid_section_ids: set[str]) -> dict:
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
        sid = entry.get("section_id")
        note = entry.get("note")
        if not isinstance(sid, str) or not sid:
            raise SummaryResponseError("key_moments[*].section_id must be a non-empty string")
        if sid in seen:
            raise SummaryResponseError(f"duplicate key_moments section_id: {sid}")
        if sid not in valid_section_ids:
            raise SummaryResponseError(f"key_moments references unknown section_id: {sid}")
        if not isinstance(note, str) or not note.strip():
            raise SummaryResponseError("key_moments[*].note must be a non-empty string")
        seen.add(sid)

    return data
