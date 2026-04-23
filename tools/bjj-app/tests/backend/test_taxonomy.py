"""Tests for taxonomy loading + tint attachment."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.analysis.taxonomy import TINTS, load_taxonomy


@pytest.fixture
def tiny_taxonomy(tmp_path: Path) -> Path:
    data = {
        "events": {},
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "x"},
            "guard_bottom": {"label": "Guard (Bottom)", "dominance": 1, "visual_cues": "y"},
        },
        "positions": [
            {"id": "standing_neutral", "name": "Standing - Neutral",
             "category": "standing", "visual_cues": "a"},
            {"id": "closed_guard_bottom", "name": "Closed Guard (Bottom)",
             "category": "guard_bottom", "visual_cues": "b"},
        ],
        "valid_transitions": [
            ["standing_neutral", "closed_guard_bottom"],
            ["closed_guard_bottom", "standing_neutral"],
        ],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data))
    return path


def test_tints_cover_all_canonical_categories():
    # The real taxonomy has 7 canonical categories — each must have a tint.
    expected = {
        "standing", "guard_bottom", "guard_top", "dominant_top",
        "inferior_bottom", "leg_entanglement", "scramble",
    }
    assert expected.issubset(set(TINTS.keys()))


def test_load_taxonomy_returns_categories_positions_transitions(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    assert set(tax.keys()) == {"categories", "positions", "techniques", "transitions"}
    # `techniques` key is new in M12; absent in a taxonomy without that key,
    # it round-trips as an empty list.
    assert tax["techniques"] == []


def test_load_taxonomy_attaches_tint_to_each_category(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    for cat in tax["categories"]:
        assert "tint" in cat
        assert isinstance(cat["tint"], str)
        assert cat["tint"].startswith("#")


def test_load_taxonomy_category_shape(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    standing = next(c for c in tax["categories"] if c["id"] == "standing")
    assert standing["label"] == "Standing"
    assert standing["dominance"] == 0


def test_load_taxonomy_positions_shape(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    sn = next(p for p in tax["positions"] if p["id"] == "standing_neutral")
    assert sn["name"] == "Standing - Neutral"
    assert sn["category"] == "standing"


def test_load_taxonomy_transitions_shape(tiny_taxonomy: Path):
    tax = load_taxonomy(tiny_taxonomy)
    assert {"from": "standing_neutral", "to": "closed_guard_bottom"} in tax["transitions"]
    assert {"from": "closed_guard_bottom", "to": "standing_neutral"} in tax["transitions"]


def test_load_taxonomy_raises_when_file_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_taxonomy(tmp_path / "nope.json")


def test_load_taxonomy_real_file_has_44_positions_and_7_categories():
    # Integration: against the real tools/taxonomy.json shipped in the repo.
    real = Path(__file__).parent.parent.parent.parent / "taxonomy.json"
    if not real.exists():
        pytest.skip("real taxonomy.json not present at expected path")
    tax = load_taxonomy(real)
    assert len(tax["positions"]) == 44
    assert len(tax["categories"]) == 7
