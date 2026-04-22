"""Tests for summarise.py — pure helpers (M9b section-based)."""
from __future__ import annotations

import json

import pytest

from server.analysis.summarise import (
    SummaryResponseError,
    build_summary_prompt,
    parse_summary_response,
)


# ---------- build_summary_prompt ----------


def _roll() -> dict:
    return {
        "player_a_name": "Greig", "player_b_name": "Sam",
        "duration_s": 60.0, "date": "2026-04-22",
    }


def test_build_summary_prompt_includes_section_narratives_and_annotations():
    sections = [
        {
            "id": "sec1", "start_s": 3.0, "end_s": 7.0,
            "narrative": "Greig recovers closed guard.",
            "coach_tip": "Stay elbows in.",
        },
        {
            "id": "sec2", "start_s": 15.0, "end_s": 22.0,
            "narrative": "Sam passes half guard.",
            "coach_tip": "Frame on hips.",
        },
    ]
    annotations_by_section = {
        "sec1": [{"body": "triangle was there", "created_at": 1713700000}],
        "sec2": [],
    }
    out = build_summary_prompt(
        roll_row=_roll(), sections=sections,
        annotations_by_section=annotations_by_section,
    )
    assert "Greig recovers closed guard." in out
    assert "Sam passes half guard." in out
    assert "triangle was there" in out
    assert "sec1" in out
    assert "0:03" in out
    assert "0:15" in out


def test_build_summary_prompt_skips_sections_without_narrative():
    sections = [
        {"id": "s1", "start_s": 0.0, "end_s": 2.0, "narrative": "", "coach_tip": ""},
        {"id": "s2", "start_s": 5.0, "end_s": 10.0,
         "narrative": "Passes to mount.", "coach_tip": "Drive the knee across."},
    ]
    out = build_summary_prompt(
        roll_row=_roll(), sections=sections, annotations_by_section={},
    )
    assert "Passes to mount." in out
    assert "s1" not in out  # unanalysed section not referenced


def test_build_summary_prompt_handles_no_analysed_sections():
    out = build_summary_prompt(
        roll_row=_roll(), sections=[], annotations_by_section={},
    )
    assert "(no sections analysed)" in out


# ---------- parse_summary_response ----------


_VALID_PAYLOAD_TEMPLATE = {
    "summary": "ok",
    "scores": {
        "guard_retention": 7,
        "positional_awareness": 6,
        "transition_quality": 7,
    },
    "top_improvements": ["a", "b", "c"],
    "strengths": ["x", "y"],
    "key_moments": [
        {"section_id": "sec1", "note": "first"},
        {"section_id": "sec2", "note": "second"},
        {"section_id": "sec3", "note": "third"},
    ],
}


def test_parse_summary_response_happy_path():
    raw = json.dumps(_VALID_PAYLOAD_TEMPLATE)
    out = parse_summary_response(raw, {"sec1", "sec2", "sec3"})
    assert out["key_moments"][0]["section_id"] == "sec1"
    assert out["scores"]["guard_retention"] == 7


def test_parse_summary_response_rejects_unknown_section_id():
    raw = json.dumps(_VALID_PAYLOAD_TEMPLATE)
    with pytest.raises(SummaryResponseError):
        parse_summary_response(raw, {"sec1", "sec2"})  # sec3 unknown


def test_parse_summary_response_rejects_duplicate_section_id():
    payload = dict(_VALID_PAYLOAD_TEMPLATE)
    payload["key_moments"] = [
        {"section_id": "sec1", "note": "a"},
        {"section_id": "sec1", "note": "b"},
        {"section_id": "sec2", "note": "c"},
    ]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), {"sec1", "sec2"})


def test_parse_summary_response_rejects_malformed_json():
    with pytest.raises(SummaryResponseError):
        parse_summary_response("{ not json", {"sec1"})


def test_parse_summary_response_clamps_scores():
    payload = dict(_VALID_PAYLOAD_TEMPLATE)
    payload["scores"] = {
        "guard_retention": 15,        # clamps to 10
        "positional_awareness": -2,   # clamps to 0
        "transition_quality": 7.6,    # rounds to 8
    }
    out = parse_summary_response(json.dumps(payload), {"sec1", "sec2", "sec3"})
    assert out["scores"] == {
        "guard_retention": 10,
        "positional_awareness": 0,
        "transition_quality": 8,
    }


def test_parse_summary_response_rejects_bool_as_score():
    payload = dict(_VALID_PAYLOAD_TEMPLATE)
    payload["scores"] = {
        "guard_retention": True,
        "positional_awareness": 5,
        "transition_quality": 5,
    }
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), {"sec1", "sec2", "sec3"})


def test_parse_summary_response_rejects_missing_required_key():
    payload = {k: v for k, v in _VALID_PAYLOAD_TEMPLATE.items() if k != "strengths"}
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), {"sec1", "sec2", "sec3"})
