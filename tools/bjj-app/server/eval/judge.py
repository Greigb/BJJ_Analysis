"""LLM-as-judge prompt builders + response parsers.

Each judge is a second Claude call that scores a generated prompt output
against a fixed rubric, returning a strict JSON shape. The runner in
server.eval.runner fires the judge after each generation and attaches the
judgement to the result.
"""
from __future__ import annotations

import json
from pathlib import Path


class JudgementError(Exception):
    """Raised when a judge's output fails schema or type validation."""


# ---------- section judge ----------


_SECTION_JUDGE_AXES = ("vocabulary", "accuracy", "specificity", "coach_tip")


def build_section_judge_prompt(
    *,
    frame_paths: list[Path],
    timestamps: list[float],
    start_s: float,
    end_s: float,
    player_a_name: str,
    player_b_name: str,
    generated_narrative: str,
    generated_coach_tip: str,
) -> str:
    """Construct the LLM-as-judge prompt for a section analysis output.

    The judge sees the original frames + the generated narrative + coach_tip,
    then scores on four axes (0-10 each) with one-sentence rationales.
    """
    duration = round(end_s - start_s, 2)
    frame_lines = [
        f"Frame {i + 1} @t={timestamps[i]}s: @{frame_paths[i]}"
        for i in range(len(frame_paths))
    ]
    preamble = (
        f"You are evaluating a generated analysis of a BJJ sequence between "
        f"{player_a_name} (player_a) and {player_b_name} (player_b). The "
        f"sequence spans {duration}s, sampled into {len(frame_paths)} "
        f"chronologically ordered frames."
    )
    generated_block = (
        f"Another model was asked to produce a narrative + coach_tip from "
        f"these frames. Its output:\n\n"
        f"Narrative: {generated_narrative}\n\n"
        f"Coach tip: {generated_coach_tip}"
    )
    rubric = (
        "Score the output on four axes (0-10 integer each):\n"
        "- vocabulary: Does it use standard BJJ position names "
        "(e.g. \"closed guard bottom\", \"side control top\") rather than "
        "vague descriptions of what bodies are doing?\n"
        "- accuracy: Does the narrative match what actually happens in the "
        "frames? (Penalise hallucinated moves or wrong positions.)\n"
        "- specificity: Is it concrete about who initiates, where contact is, "
        "and what's being set up, or is it generic?\n"
        "- coach_tip: Is the coach tip actionable for player_a in this "
        "specific situation, or is it generic advice?"
    )
    schema = (
        "Output ONE JSON object and nothing else. No prose outside JSON. "
        "No markdown fences.\n"
        "{\n"
        '  "scores": {"vocabulary": <0..10>, "accuracy": <0..10>, '
        '"specificity": <0..10>, "coach_tip": <0..10>},\n'
        '  "rationale": {"vocabulary": "<one sentence>", '
        '"accuracy": "<one sentence>", '
        '"specificity": "<one sentence>", '
        '"coach_tip": "<one sentence>"},\n'
        '  "overall": <0..10>,\n'
        '  "verdict": "<one-sentence overall judgement>"\n'
        "}"
    )
    return "\n\n".join([
        preamble,
        "\n".join(frame_lines),
        generated_block,
        rubric,
        schema,
    ])


def _clamp_score(value) -> int:
    if isinstance(value, bool):
        raise JudgementError(f"score must not be bool: {value!r}")
    if not isinstance(value, (int, float)):
        raise JudgementError(f"score must be number: {value!r}")
    return max(0, min(10, int(round(value))))


def parse_section_judgement(raw: str) -> dict:
    """Parse + validate section-judge JSON output. Raises JudgementError."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgementError(f"not valid JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise JudgementError(f"expected object, got {type(data).__name__}")
    for key in ("scores", "rationale", "overall", "verdict"):
        if key not in data:
            raise JudgementError(f"missing required key: {key}")
    scores = data["scores"]
    if not isinstance(scores, dict):
        raise JudgementError("scores must be an object")
    for axis in _SECTION_JUDGE_AXES:
        if axis not in scores:
            raise JudgementError(f"missing score axis: {axis}")
    data["scores"] = {a: _clamp_score(scores[a]) for a in _SECTION_JUDGE_AXES}
    data["overall"] = _clamp_score(data["overall"])
    if not isinstance(data["verdict"], str) or not data["verdict"].strip():
        raise JudgementError("verdict must be a non-empty string")
    return data


# ---------- summary judge ----------


_SUMMARY_JUDGE_AXES = (
    "faithfulness",
    "rubric_calibration",
    "improvements_grounding",
    "strengths_grounding",
    "key_moments_grounding",
)


def _format_mm_ss(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def build_summary_judge_prompt(
    *,
    roll_row: dict,
    sections: list[dict],
    generated_summary: dict,
) -> str:
    """Construct the LLM-as-judge prompt for a generated summary payload.

    The judge sees the section narratives + the generated summary JSON, and
    scores on five axes covering faithfulness, score calibration, and the
    grounding of improvements / strengths / key_moments in actual sections.
    """
    a_name = roll_row.get("player_a_name", "player_a")
    b_name = roll_row.get("player_b_name", "player_b")

    section_blocks: list[str] = []
    for s in sections:
        narrative = (s.get("narrative") or "").strip()
        if not narrative:
            continue
        section_blocks.append(
            f"Section section_id={s['id']} "
            f"({_format_mm_ss(s['start_s'])} – {_format_mm_ss(s['end_s'])}):\n"
            f"  Narrative: {narrative}"
        )
    sections_block = (
        "Section narratives (chronological):\n" + "\n\n".join(section_blocks)
        if section_blocks else
        "Section narratives (chronological):\n(no sections analysed)"
    )

    preamble = (
        f"You are evaluating a generated BJJ coaching summary for {a_name} "
        f"(vs {b_name}). The summary was produced from the section narratives "
        f"below."
    )
    generated_block = (
        "Generated summary JSON:\n" + json.dumps(generated_summary, indent=2)
    )
    rubric = (
        "Score on five axes (0-10 integer each):\n"
        "- faithfulness: Does the summary sentence reflect what the section "
        "narratives actually say, or does it invent details?\n"
        "- rubric_calibration: Are the three 0-10 scores calibrated against "
        "the footage (0-3 needs work, 4-6 developing, 7-10 reliable)?\n"
        "- improvements_grounding: Are the top_improvements grounded in real "
        "weaknesses that the sections show?\n"
        "- strengths_grounding: Are the strengths grounded in real wins that "
        "the sections show?\n"
        "- key_moments_grounding: Do the key_moments reference pivotal "
        "sections, not arbitrary ones?"
    )
    schema = (
        "Output ONE JSON object and nothing else. No prose outside JSON. "
        "No markdown fences.\n"
        "{\n"
        '  "scores": {"faithfulness": <0..10>, "rubric_calibration": <0..10>, '
        '"improvements_grounding": <0..10>, "strengths_grounding": <0..10>, '
        '"key_moments_grounding": <0..10>},\n'
        '  "rationale": {"faithfulness": "<sentence>", '
        '"rubric_calibration": "<sentence>", '
        '"improvements_grounding": "<sentence>", '
        '"strengths_grounding": "<sentence>", '
        '"key_moments_grounding": "<sentence>"},\n'
        '  "overall": <0..10>,\n'
        '  "verdict": "<one-sentence overall judgement>"\n'
        "}"
    )
    return "\n\n".join([preamble, sections_block, generated_block, rubric, schema])


def parse_summary_judgement(raw: str) -> dict:
    """Parse + validate summary-judge JSON output. Raises JudgementError."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgementError(f"not valid JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise JudgementError(f"expected object, got {type(data).__name__}")
    for key in ("scores", "rationale", "overall", "verdict"):
        if key not in data:
            raise JudgementError(f"missing required key: {key}")
    scores = data["scores"]
    if not isinstance(scores, dict):
        raise JudgementError("scores must be an object")
    for axis in _SUMMARY_JUDGE_AXES:
        if axis not in scores:
            raise JudgementError(f"missing score axis: {axis}")
    data["scores"] = {a: _clamp_score(scores[a]) for a in _SUMMARY_JUDGE_AXES}
    data["overall"] = _clamp_score(data["overall"])
    if not isinstance(data["verdict"], str) or not data["verdict"].strip():
        raise JudgementError("verdict must be a non-empty string")
    return data
