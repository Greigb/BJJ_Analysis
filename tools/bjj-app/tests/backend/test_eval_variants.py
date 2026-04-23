"""Tests for server.eval.variants — prompt variant registry."""
from __future__ import annotations

from pathlib import Path

from server.eval.variants import (
    SECTION_VARIANTS,
    SUMMARY_VARIANTS,
    SectionEvalContext,
    SummaryEvalContext,
)


def _section_ctx(
    tmp_path: Path,
    *,
    with_positions: bool,
    with_techniques: bool = False,
    technique_body: str | None = None,
) -> SectionEvalContext:
    frame = tmp_path / "frame_000000.jpg"
    frame.write_bytes(b"x")
    positions = []
    if with_positions:
        positions = [{
            "position_id": "closed_guard_bottom",
            "name": "Closed Guard (Bottom)",
            "markdown": "# Closed Guard",
            "vault_path": "Positions/Closed Guard (Bottom).md",
            "how_to_identify": "Ankles LOCKED behind the top person's back.",
        }]
    techniques = []
    if with_techniques:
        techniques = [{
            "technique_id": "armbar",
            "name": "Armbar",
            "markdown": "# Armbar",
            "vault_path": "Techniques/Armbar.md",
            "how_to_identify": technique_body,
            "used_from_position_ids": ["closed_guard_bottom"],
        }]
    return {
        "start_s": 0.0, "end_s": 1.0,
        "frame_paths": [frame], "timestamps": [0.0],
        "player_a_name": "A", "player_b_name": "B",
        "player_a_description": None, "player_b_description": None,
        "positions": positions,
        "techniques": techniques,
    }


def test_section_variants_registry_has_m9b_baseline_and_m10_grounded():
    assert "m9b-baseline" in SECTION_VARIANTS
    assert "m10-grounded" in SECTION_VARIANTS
    assert callable(SECTION_VARIANTS["m9b-baseline"])
    assert callable(SECTION_VARIANTS["m10-grounded"])


def test_m9b_baseline_variant_builds_prompt_without_positions_block(tmp_path):
    prompt = SECTION_VARIANTS["m9b-baseline"](
        _section_ctx(tmp_path, with_positions=True)
    )
    # Even when ctx carries positions, baseline variant ignores them.
    assert "Canonical BJJ positions" not in prompt


def test_m10_grounded_variant_builds_prompt_with_positions_block(tmp_path):
    prompt = SECTION_VARIANTS["m10-grounded"](
        _section_ctx(tmp_path, with_positions=True)
    )
    assert "Canonical BJJ positions" in prompt
    assert "Ankles LOCKED" in prompt


def test_m10_grounded_variant_gracefully_skips_block_when_no_positions(tmp_path):
    """If ctx has empty positions, m10-grounded produces a block-less prompt
    identical in spirit to the M9b baseline."""
    prompt = SECTION_VARIANTS["m10-grounded"](
        _section_ctx(tmp_path, with_positions=False)
    )
    assert "Canonical BJJ positions" not in prompt


def test_section_variants_registry_has_m12_variants():
    assert "m10-techniques-names" in SECTION_VARIANTS
    assert "m10-techniques-bodies" in SECTION_VARIANTS
    assert callable(SECTION_VARIANTS["m10-techniques-names"])
    assert callable(SECTION_VARIANTS["m10-techniques-bodies"])


def test_m10_techniques_names_variant_renders_nested_technique(tmp_path):
    prompt = SECTION_VARIANTS["m10-techniques-names"](
        _section_ctx(tmp_path, with_positions=True, with_techniques=True)
    )
    assert "Canonical BJJ positions" in prompt
    assert "Ankles LOCKED" in prompt
    assert "Techniques from here: Armbar" in prompt
    # Names-only mode: no detail body even if supplied (here supplied as None anyway).
    assert "Technique detail" not in prompt


def test_m10_techniques_bodies_variant_renders_detail_block(tmp_path):
    prompt = SECTION_VARIANTS["m10-techniques-bodies"](
        _section_ctx(
            tmp_path, with_positions=True, with_techniques=True,
            technique_body="Isolate the arm, break grip, finish.",
        )
    )
    assert "Techniques from here: Armbar" in prompt
    assert "Technique detail" in prompt
    assert "Isolate the arm, break grip, finish." in prompt


def _summary_ctx() -> SummaryEvalContext:
    return {
        "roll_row": {
            "player_a_name": "Greig", "player_b_name": "Sam",
            "duration_s": 60.0, "date": "2026-04-22",
        },
        "sections": [
            {
                "id": "sec1", "start_s": 3.0, "end_s": 7.0,
                "narrative": "A recovers closed guard.", "coach_tip": "Elbows tight.",
            },
        ],
        "annotations_by_section": {"sec1": []},
    }


def test_summary_variants_registry_has_current():
    assert "current" in SUMMARY_VARIANTS
    assert callable(SUMMARY_VARIANTS["current"])


def test_current_summary_variant_renders_summary_prompt():
    prompt = SUMMARY_VARIANTS["current"](_summary_ctx())
    assert "BJJ coach" in prompt
    assert "A recovers closed guard." in prompt
