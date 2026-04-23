"""Tests for server.eval.judge — LLM-as-judge prompt builders + parsers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.eval.judge import (
    JudgementError,
    build_section_judge_prompt,
    build_summary_judge_prompt,
    parse_section_judgement,
    parse_summary_judgement,
)


def test_build_section_judge_prompt_includes_frames_and_generated_text(tmp_path):
    frames = [tmp_path / f"frame_{i:06d}.jpg" for i in range(2)]
    for f in frames:
        f.write_bytes(b"x")
    prompt = build_section_judge_prompt(
        frame_paths=frames, timestamps=[0.0, 1.0],
        start_s=0.0, end_s=2.0,
        player_a_name="Greig", player_b_name="Sam",
        generated_narrative="A recovers closed guard.",
        generated_coach_tip="Stay elbows in.",
    )
    assert "Greig" in prompt
    assert "Sam" in prompt
    for f in frames:
        assert f"@{f}" in prompt
    assert "A recovers closed guard." in prompt
    assert "Stay elbows in." in prompt


def test_build_section_judge_prompt_lists_all_four_rubric_axes(tmp_path):
    frame = tmp_path / "f.jpg"; frame.write_bytes(b"x")
    prompt = build_section_judge_prompt(
        frame_paths=[frame], timestamps=[0.0],
        start_s=0.0, end_s=1.0,
        player_a_name="A", player_b_name="B",
        generated_narrative="x", generated_coach_tip="y",
    )
    for axis in ("vocabulary", "accuracy", "specificity", "coach_tip"):
        assert axis in prompt


_VALID_SECTION_JUDGEMENT = {
    "scores": {
        "vocabulary": 8, "accuracy": 7, "specificity": 6, "coach_tip": 5,
    },
    "rationale": {
        "vocabulary": "Good canonical terms.",
        "accuracy": "Mostly right.",
        "specificity": "Could be more concrete.",
        "coach_tip": "Actionable.",
    },
    "overall": 7,
    "verdict": "Solid analysis.",
}


def test_parse_section_judgement_happy_path():
    out = parse_section_judgement(json.dumps(_VALID_SECTION_JUDGEMENT))
    assert out["scores"]["vocabulary"] == 8
    assert out["overall"] == 7
    assert out["verdict"] == "Solid analysis."


def test_parse_section_judgement_rejects_malformed_json():
    with pytest.raises(JudgementError):
        parse_section_judgement("not json")


def test_parse_section_judgement_rejects_missing_score_axis():
    payload = json.loads(json.dumps(_VALID_SECTION_JUDGEMENT))
    del payload["scores"]["accuracy"]
    with pytest.raises(JudgementError):
        parse_section_judgement(json.dumps(payload))


def test_parse_section_judgement_backfills_missing_rationale_axis():
    """Claude's rationale is less reliable than scores — a missing axis
    should backfill with a placeholder rather than raise or crash downstream."""
    payload = json.loads(json.dumps(_VALID_SECTION_JUDGEMENT))
    del payload["rationale"]["coach_tip"]
    out = parse_section_judgement(json.dumps(payload))
    assert out["rationale"]["coach_tip"] == "(no rationale)"
    assert out["rationale"]["vocabulary"] == "Good canonical terms."


def test_parse_section_judgement_clamps_scores():
    payload = json.loads(json.dumps(_VALID_SECTION_JUDGEMENT))
    payload["scores"]["vocabulary"] = 15      # → 10
    payload["scores"]["accuracy"] = -3        # → 0
    payload["scores"]["specificity"] = 6.6    # → 7
    payload["overall"] = 99                   # → 10
    out = parse_section_judgement(json.dumps(payload))
    assert out["scores"]["vocabulary"] == 10
    assert out["scores"]["accuracy"] == 0
    assert out["scores"]["specificity"] == 7
    assert out["overall"] == 10


def test_parse_section_judgement_rejects_bool_score():
    payload = json.loads(json.dumps(_VALID_SECTION_JUDGEMENT))
    payload["scores"]["vocabulary"] = True
    with pytest.raises(JudgementError):
        parse_section_judgement(json.dumps(payload))


def test_build_summary_judge_prompt_includes_sections_and_summary_payload():
    roll = {"player_a_name": "Greig", "player_b_name": "Sam"}
    sections = [
        {"id": "sec1", "start_s": 3.0, "end_s": 7.0, "narrative": "A recovers guard."},
    ]
    generated = {
        "summary": "Tight roll.",
        "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["a", "b", "c"],
        "strengths": ["x", "y"],
        "key_moments": [{"section_id": "sec1", "note": "the sweep"}],
    }
    prompt = build_summary_judge_prompt(
        roll_row=roll, sections=sections, generated_summary=generated,
    )
    assert "Greig" in prompt
    assert "A recovers guard." in prompt
    assert "sec1" in prompt
    assert "Tight roll." in prompt


_VALID_SUMMARY_JUDGEMENT = {
    "scores": {
        "faithfulness": 8, "rubric_calibration": 7,
        "improvements_grounding": 6, "strengths_grounding": 7,
        "key_moments_grounding": 5,
    },
    "rationale": {
        "faithfulness": "Summary tracks sections.",
        "rubric_calibration": "Scores calibrated.",
        "improvements_grounding": "Mostly grounded.",
        "strengths_grounding": "Strengths are real.",
        "key_moments_grounding": "One moment is vague.",
    },
    "overall": 7,
    "verdict": "Good summary.",
}


def test_parse_summary_judgement_happy_path():
    out = parse_summary_judgement(json.dumps(_VALID_SUMMARY_JUDGEMENT))
    assert out["scores"]["faithfulness"] == 8
    assert out["overall"] == 7


def test_parse_summary_judgement_rejects_missing_axis():
    payload = json.loads(json.dumps(_VALID_SUMMARY_JUDGEMENT))
    del payload["scores"]["faithfulness"]
    with pytest.raises(JudgementError):
        parse_summary_judgement(json.dumps(payload))
