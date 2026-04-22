"""Tests for ordered_positions_from_taxonomy — taxonomy-ordered list builder."""
from __future__ import annotations

from server.analysis.positions_vault import PositionNote, ordered_positions_from_taxonomy


def _note(pid: str, name: str) -> PositionNote:
    return {
        "position_id": pid,
        "name": name,
        "markdown": f"# {name}",
        "vault_path": f"Positions/{name}.md",
        "how_to_identify": None,
    }


def test_ordered_positions_by_taxonomy_returns_list_in_taxonomy_order():
    taxonomy = {
        "positions": [
            {"id": "standing_neutral", "name": "Standing - Neutral", "category": "standing"},
            {"id": "closed_guard_bottom", "name": "Closed Guard (Bottom)", "category": "guard_bottom"},
            {"id": "side_control_top", "name": "Side Control (Top)", "category": "dominant_top"},
        ]
    }
    index = {
        "closed_guard_bottom": _note("closed_guard_bottom", "Closed Guard (Bottom)"),
        "standing_neutral": _note("standing_neutral", "Standing - Neutral"),
        "side_control_top": _note("side_control_top", "Side Control (Top)"),
    }
    out = ordered_positions_from_taxonomy(positions_index=index, taxonomy=taxonomy)
    assert [p["position_id"] for p in out] == [
        "standing_neutral",
        "closed_guard_bottom",
        "side_control_top",
    ]


def test_ordered_positions_skips_taxonomy_positions_missing_from_index():
    taxonomy = {
        "positions": [
            {"id": "a"},
            {"id": "missing"},
            {"id": "c"},
        ]
    }
    index = {"a": _note("a", "A"), "c": _note("c", "C")}
    out = ordered_positions_from_taxonomy(positions_index=index, taxonomy=taxonomy)
    assert [p["position_id"] for p in out] == ["a", "c"]


def test_ordered_positions_skips_index_positions_missing_from_taxonomy():
    taxonomy = {"positions": [{"id": "a"}]}
    index = {
        "a": _note("a", "A"),
        "orphan": _note("orphan", "Orphan"),
    }
    out = ordered_positions_from_taxonomy(positions_index=index, taxonomy=taxonomy)
    assert [p["position_id"] for p in out] == ["a"]
