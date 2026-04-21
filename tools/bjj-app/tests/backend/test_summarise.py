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
