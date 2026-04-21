"""Tests for summarise.py — pure helpers."""
from __future__ import annotations

import json

import pytest

from server.analysis.summarise import (
    CATEGORY_EMOJI,
    SummaryResponseError,
    build_summary_prompt,
    compute_distribution,
    parse_summary_response,
)


# ---------- compute_distribution ----------


_FIXTURE_CATEGORIES = [
    {"id": "standing", "label": "Standing"},
    {"id": "guard_bottom", "label": "Guard (Bottom)"},
    {"id": "guard_top", "label": "Guard (Top)"},
    {"id": "scramble", "label": "Scramble"},
]

_FIXTURE_POSITION_TO_CATEGORY = {
    "standing_neutral": "standing",
    "closed_guard_bottom": "guard_bottom",
    "closed_guard_top": "guard_top",
    "scramble_entry": "scramble",
}


def _analyses(*position_ids_in_order: str) -> list[dict]:
    rows: list[dict] = []
    for i, pid in enumerate(position_ids_in_order):
        rows.append({
            "position_id": pid,
            "player": "a",
            "timestamp_s": float(i),
            "category": _FIXTURE_POSITION_TO_CATEGORY.get(pid, "scramble"),
        })
    return rows


def test_compute_distribution_returns_timeline_in_chronological_order():
    analyses = _analyses("standing_neutral", "closed_guard_bottom", "scramble_entry")
    dist = compute_distribution(analyses, _FIXTURE_CATEGORIES)
    assert dist["timeline"] == ["standing", "guard_bottom", "scramble"]


def test_compute_distribution_counts_per_category():
    analyses = _analyses(
        "standing_neutral", "closed_guard_bottom", "closed_guard_bottom",
        "closed_guard_bottom", "scramble_entry",
    )
    dist = compute_distribution(analyses, _FIXTURE_CATEGORIES)
    assert dist["counts"] == {"standing": 1, "guard_bottom": 3, "scramble": 1}


def test_compute_distribution_percentages_sum_to_100():
    analyses = _analyses("standing_neutral", "closed_guard_bottom", "scramble_entry")
    dist = compute_distribution(analyses, _FIXTURE_CATEGORIES)
    total = sum(dist["percentages"].values())
    assert 99 <= total <= 100


def test_compute_distribution_handles_empty_analyses():
    dist = compute_distribution([], _FIXTURE_CATEGORIES)
    assert dist == {"timeline": [], "counts": {}, "percentages": {}}


def test_compute_distribution_only_counts_player_a():
    analyses = [
        {"position_id": "standing_neutral", "player": "a", "timestamp_s": 0.0, "category": "standing"},
        {"position_id": "closed_guard_top", "player": "b", "timestamp_s": 0.0, "category": "guard_top"},
        {"position_id": "closed_guard_bottom", "player": "a", "timestamp_s": 1.0, "category": "guard_bottom"},
    ]
    dist = compute_distribution(analyses, _FIXTURE_CATEGORIES)
    assert dist["counts"] == {"standing": 1, "guard_bottom": 1}
    assert dist["timeline"] == ["standing", "guard_bottom"]


def test_category_emoji_covers_canonical_categories():
    expected = {
        "standing", "guard_bottom", "guard_top", "dominant_top",
        "inferior_bottom", "leg_entanglement", "scramble",
    }
    assert expected.issubset(set(CATEGORY_EMOJI.keys()))


# ---------- build_summary_prompt ----------


def _roll(**overrides) -> dict:
    base = {
        "id": "roll-1", "title": "Sample", "date": "2026-04-21", "duration_s": 225.0,
        "player_a_name": "Alice", "player_b_name": "Bob",
    }
    base.update(overrides)
    return base


def _moment(mid: str, frame_idx: int, timestamp_s: float) -> dict:
    return {"id": mid, "frame_idx": frame_idx, "timestamp_s": timestamp_s}


def test_build_summary_prompt_includes_player_names():
    prompt = build_summary_prompt(
        roll_row=_roll(), moment_rows=[], analyses_by_moment={}, annotations_by_moment={},
    )
    assert "Alice" in prompt
    assert "Bob" in prompt
    assert "Greig" not in prompt
    assert "Anthony" not in prompt


def test_build_summary_prompt_lists_analysed_moments_chronologically():
    moments = [_moment("m1", 3, 3.0), _moment("m2", 12, 12.0)]
    analyses = {
        "m1": [
            {"player": "a", "position_id": "closed_guard_bottom", "confidence": 0.8,
             "description": "Greig in guard", "coach_tip": "Break posture"},
            {"player": "b", "position_id": "closed_guard_top", "confidence": 0.75,
             "description": None, "coach_tip": None},
        ],
        "m2": [
            {"player": "a", "position_id": "half_guard_bottom", "confidence": 0.7,
             "description": "Slipped to half", "coach_tip": "Underhook"},
            {"player": "b", "position_id": "half_guard_top", "confidence": 0.68,
             "description": None, "coach_tip": None},
        ],
    }
    prompt = build_summary_prompt(
        roll_row=_roll(), moment_rows=moments,
        analyses_by_moment=analyses, annotations_by_moment={},
    )
    m1_idx = prompt.find("moment_id=m1")
    m2_idx = prompt.find("moment_id=m2")
    assert m1_idx != -1 and m2_idx != -1
    assert m1_idx < m2_idx
    assert "closed_guard_bottom" in prompt
    assert "Break posture" in prompt
    assert "Underhook" in prompt


def test_build_summary_prompt_omits_annotations_block_when_no_annotations():
    moments = [_moment("m1", 3, 3.0)]
    analyses = {
        "m1": [
            {"player": "a", "position_id": "standing_neutral", "confidence": 0.9,
             "description": "Standing", "coach_tip": "Engage"},
            {"player": "b", "position_id": "standing_neutral", "confidence": 0.88,
             "description": None, "coach_tip": None},
        ],
    }
    prompt = build_summary_prompt(
        roll_row=_roll(), moment_rows=moments,
        analyses_by_moment=analyses, annotations_by_moment={"m1": []},
    )
    assert "User's own notes" not in prompt


def test_build_summary_prompt_includes_annotations_when_present():
    moments = [_moment("m1", 3, 3.0)]
    analyses = {
        "m1": [
            {"player": "a", "position_id": "standing_neutral", "confidence": 0.9,
             "description": "Standing", "coach_tip": "Engage"},
            {"player": "b", "position_id": "standing_neutral", "confidence": 0.88,
             "description": None, "coach_tip": None},
        ],
    }
    annotations = {
        "m1": [
            {"id": "a1", "body": "I was too passive here", "created_at": 1},
            {"id": "a2", "body": "could have shot a single", "created_at": 2},
        ],
    }
    prompt = build_summary_prompt(
        roll_row=_roll(), moment_rows=moments,
        analyses_by_moment=analyses, annotations_by_moment=annotations,
    )
    assert "User's own notes" in prompt
    assert "too passive" in prompt
    assert "shot a single" in prompt


def test_build_summary_prompt_includes_output_json_schema_keys():
    prompt = build_summary_prompt(
        roll_row=_roll(), moment_rows=[], analyses_by_moment={}, annotations_by_moment={},
    )
    for key in (
        "summary", "scores", "guard_retention", "positional_awareness",
        "transition_quality", "top_improvements", "strengths", "key_moments",
        "moment_id",
    ):
        assert key in prompt


# ---------- parse_summary_response ----------


def _valid_payload() -> dict:
    return {
        "summary": "A good roll.",
        "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["a", "b", "c"],
        "strengths": ["x", "y"],
        "key_moments": [
            {"moment_id": "m1", "note": "first"},
            {"moment_id": "m2", "note": "second"},
            {"moment_id": "m3", "note": "third"},
        ],
    }


_VALID_IDS = {"m1", "m2", "m3", "m4"}


def test_parse_summary_response_accepts_valid_payload():
    raw = json.dumps(_valid_payload())
    out = parse_summary_response(raw, _VALID_IDS)
    assert out["summary"] == "A good roll."
    assert out["scores"]["guard_retention"] == 8


def test_parse_summary_response_rejects_non_json():
    with pytest.raises(SummaryResponseError):
        parse_summary_response("not json", _VALID_IDS)


def test_parse_summary_response_rejects_missing_top_level_keys():
    payload = _valid_payload()
    del payload["scores"]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_clamps_out_of_range_scores():
    payload = _valid_payload()
    payload["scores"] = {"guard_retention": 42, "positional_awareness": -3, "transition_quality": 7}
    out = parse_summary_response(json.dumps(payload), _VALID_IDS)
    assert out["scores"]["guard_retention"] == 10
    assert out["scores"]["positional_awareness"] == 0
    assert out["scores"]["transition_quality"] == 7


def test_parse_summary_response_rejects_key_moments_length_not_3():
    payload = _valid_payload()
    payload["key_moments"] = payload["key_moments"][:2]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_rejects_hallucinated_moment_id():
    payload = _valid_payload()
    payload["key_moments"][0]["moment_id"] = "not-a-real-id"
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_rejects_duplicate_moment_ids():
    payload = _valid_payload()
    payload["key_moments"][1]["moment_id"] = payload["key_moments"][0]["moment_id"]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_rejects_top_improvements_length_not_3():
    payload = _valid_payload()
    payload["top_improvements"] = ["a", "b"]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)


def test_parse_summary_response_requires_strengths_between_2_and_4_items():
    # 0 items — reject
    payload = _valid_payload()
    payload["strengths"] = []
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)

    # 1 item — reject (spec says 2-4)
    payload = _valid_payload()
    payload["strengths"] = ["only one"]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)

    # 5 items — reject (spec says 2-4)
    payload = _valid_payload()
    payload["strengths"] = ["a", "b", "c", "d", "e"]
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)

    # 2 items — accept
    payload = _valid_payload()
    payload["strengths"] = ["first", "second"]
    out = parse_summary_response(json.dumps(payload), _VALID_IDS)
    assert out["strengths"] == ["first", "second"]

    # 4 items — accept
    payload = _valid_payload()
    payload["strengths"] = ["a", "b", "c", "d"]
    out = parse_summary_response(json.dumps(payload), _VALID_IDS)
    assert len(out["strengths"]) == 4


def test_parse_summary_response_rejects_bool_scores():
    payload = _valid_payload()
    payload["scores"]["guard_retention"] = True  # noqa: disallow bool score
    with pytest.raises(SummaryResponseError):
        parse_summary_response(json.dumps(payload), _VALID_IDS)
