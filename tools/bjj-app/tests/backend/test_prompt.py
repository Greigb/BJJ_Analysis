"""Tests for build_prompt / compress_taxonomy.

Uses a tiny fixture taxonomy — we don't want to pin these tests to the real
taxonomy.json, which evolves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.analysis.prompt import build_prompt, compress_taxonomy


@pytest.fixture
def tiny_taxonomy(tmp_path: Path) -> Path:
    data = {
        "categories": {
            "standing": {"label": "Standing", "dominance": 0, "visual_cues": "Upright."},
            "guard_bottom": {
                "label": "Guard (Bottom)", "dominance": 1, "visual_cues": "On back."
            },
        },
        "positions": [
            {
                "id": "standing_neutral",
                "name": "Standing - Neutral",
                "category": "standing",
                "visual_cues": "Athletic stance.",
            },
            {
                "id": "closed_guard_bottom",
                "name": "Closed Guard (Bottom)",
                "category": "guard_bottom",
                "visual_cues": "Ankles crossed behind opponent's back.",
            },
        ],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data))
    return path


def test_compress_taxonomy_includes_every_position_id_and_name(tiny_taxonomy: Path):
    compressed = compress_taxonomy(tiny_taxonomy)
    assert "standing_neutral" in compressed
    assert "Standing - Neutral" in compressed
    assert "closed_guard_bottom" in compressed
    assert "Closed Guard (Bottom)" in compressed


def test_compress_taxonomy_includes_category_labels(tiny_taxonomy: Path):
    compressed = compress_taxonomy(tiny_taxonomy)
    assert "Standing" in compressed
    assert "Guard (Bottom)" in compressed


def test_compress_taxonomy_is_deterministic(tiny_taxonomy: Path):
    a = compress_taxonomy(tiny_taxonomy)
    b = compress_taxonomy(tiny_taxonomy)
    assert a == b


def test_build_prompt_references_the_frame_path(tiny_taxonomy: Path, tmp_path: Path):
    frame = tmp_path / "frame_000017.jpg"
    frame.write_bytes(b"\xff\xd8\xff")  # fake JPEG magic — existence is all we need

    prompt = build_prompt(frame_path=frame, taxonomy_path=tiny_taxonomy, timestamp_s=17.0)
    assert str(frame) in prompt
    # Output schema keys must be spelled in the prompt so the model learns them.
    for key in ("timestamp", "greig", "anthony", "position", "confidence",
                "description", "coach_tip"):
        assert key in prompt


def test_build_prompt_includes_the_timestamp(tiny_taxonomy: Path, tmp_path: Path):
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff")
    prompt = build_prompt(frame_path=frame, taxonomy_path=tiny_taxonomy, timestamp_s=42.5)
    assert "42.5" in prompt


def test_build_prompt_is_deterministic(tiny_taxonomy: Path, tmp_path: Path):
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff")
    a = build_prompt(frame_path=frame, taxonomy_path=tiny_taxonomy, timestamp_s=3.0)
    b = build_prompt(frame_path=frame, taxonomy_path=tiny_taxonomy, timestamp_s=3.0)
    assert a == b


def test_build_prompt_raises_if_frame_missing(tiny_taxonomy: Path, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        build_prompt(
            frame_path=tmp_path / "nope.jpg",
            taxonomy_path=tiny_taxonomy,
            timestamp_s=0.0,
        )
