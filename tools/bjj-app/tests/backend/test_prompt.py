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
    for key in ("timestamp", "player_a", "player_b", "position", "confidence",
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


def test_build_section_prompt_contains_frame_refs_and_names(tmp_path):
    from server.analysis.prompt import build_section_prompt

    frames = [tmp_path / f"frame_{i:06d}.jpg" for i in range(3)]
    for f in frames:
        f.write_bytes(b"x")

    prompt = build_section_prompt(
        start_s=3.0,
        end_s=7.0,
        frame_paths=frames,
        timestamps=[3.0, 4.0, 5.0],
        player_a_name="Greig",
        player_b_name="Sam",
    )
    assert "Greig" in prompt
    assert "Sam" in prompt
    assert "4" in prompt  # duration
    for f in frames:
        assert f"@{f}" in prompt
    assert '"narrative"' in prompt
    assert '"coach_tip"' in prompt


def test_build_section_prompt_includes_player_descriptions_when_provided(tmp_path):
    from server.analysis.prompt import build_section_prompt

    frames = [tmp_path / "frame_000000.jpg"]
    frames[0].write_bytes(b"x")

    prompt = build_section_prompt(
        start_s=0.0, end_s=1.0,
        frame_paths=frames, timestamps=[0.0],
        player_a_name="Greig", player_b_name="Sam",
        player_a_description="navy gi, bald",
        player_b_description="white gi, long hair",
    )
    assert "navy gi, bald" in prompt
    assert "white gi, long hair" in prompt
    assert "appearance hints" in prompt.lower()


def test_build_section_prompt_omits_identification_when_no_descriptions(tmp_path):
    from server.analysis.prompt import build_section_prompt

    frames = [tmp_path / "frame_000000.jpg"]
    frames[0].write_bytes(b"x")

    prompt = build_section_prompt(
        start_s=0.0, end_s=1.0,
        frame_paths=frames, timestamps=[0.0],
        player_a_name="Greig", player_b_name="Sam",
    )
    assert "appearance hints" not in prompt.lower()


def test_build_section_prompt_omits_reference_block_when_positions_is_none(tmp_path):
    from server.analysis.prompt import build_section_prompt
    frames = [tmp_path / "frame_000000.jpg"]
    frames[0].write_bytes(b"x")
    prompt = build_section_prompt(
        start_s=0.0, end_s=1.0,
        frame_paths=frames, timestamps=[0.0],
        player_a_name="A", player_b_name="B",
    )
    assert "Canonical BJJ positions" not in prompt


def test_build_section_prompt_includes_reference_block_when_positions_provided(tmp_path):
    from server.analysis.prompt import build_section_prompt
    frames = [tmp_path / "frame_000000.jpg"]
    frames[0].write_bytes(b"x")
    prompt = build_section_prompt(
        start_s=0.0, end_s=1.0,
        frame_paths=frames, timestamps=[0.0],
        player_a_name="A", player_b_name="B",
        positions=[
            _fake_position("closed_guard_bottom", "Closed Guard (Bottom)", "Ankles LOCKED."),
            _fake_position("mount_top", "Mount (Top)", "Sitting astride torso."),
        ],
    )
    assert "Closed Guard (Bottom)" in prompt
    assert "Mount (Top)" in prompt
    assert "Canonical BJJ positions" in prompt
    # Schema hint must remain last so JSON adherence is unaffected.
    assert prompt.rstrip().endswith("}")
    schema_idx = prompt.index('"narrative"')
    ref_idx = prompt.index("Canonical BJJ positions")
    assert ref_idx < schema_idx, "reference block must precede schema hint"


def test_build_section_prompt_reference_block_precedes_guidance(tmp_path):
    from server.analysis.prompt import build_section_prompt
    frames = [tmp_path / "frame_000000.jpg"]
    frames[0].write_bytes(b"x")
    prompt = build_section_prompt(
        start_s=0.0, end_s=1.0,
        frame_paths=frames, timestamps=[0.0],
        player_a_name="A", player_b_name="B",
        positions=[_fake_position("a", "A Position", "Cue.")],
    )
    ref_idx = prompt.index("Canonical BJJ positions")
    guidance_idx = prompt.index("standard BJJ vocabulary")
    assert ref_idx < guidance_idx, (
        "reference block must appear before the 'standard BJJ vocabulary' guidance"
    )


def test_parse_section_response_happy_path():
    from server.analysis.prompt import parse_section_response

    raw = '{"narrative": "Player A passes to side control.", "coach_tip": "Stay heavy."}'
    out = parse_section_response(raw)
    assert out["narrative"] == "Player A passes to side control."
    assert out["coach_tip"] == "Stay heavy."


def _fake_position(pid: str, name: str, how: str | None) -> dict:
    return {
        "position_id": pid,
        "name": name,
        "markdown": f"# {name}",
        "vault_path": f"Positions/{name}.md",
        "how_to_identify": how,
    }


def test_positions_reference_block_empty_list_returns_empty_string():
    from server.analysis.prompt import _build_positions_reference_block
    assert _build_positions_reference_block([]) == ""


def test_positions_reference_block_includes_each_position_name_and_body():
    from server.analysis.prompt import _build_positions_reference_block
    out = _build_positions_reference_block([
        _fake_position("closed_guard_bottom", "Closed Guard (Bottom)", "Ankles LOCKED."),
        _fake_position("mount_top", "Mount (Top)", "Sitting astride torso."),
    ])
    assert "Closed Guard (Bottom)" in out
    assert "Mount (Top)" in out
    assert "Ankles LOCKED." in out
    assert "Sitting astride torso." in out
    assert "closed_guard_bottom" in out
    assert "mount_top" in out


def test_positions_reference_block_skips_positions_without_how_to_identify():
    from server.analysis.prompt import _build_positions_reference_block
    out = _build_positions_reference_block([
        _fake_position("a", "A", "Has body."),
        _fake_position("b", "B", None),
        _fake_position("c", "C", "Also has body."),
    ])
    assert "Has body." in out
    assert "Also has body." in out
    # Only A and C produce bullets; B (no how_to_identify) must not appear
    # as a bullet entry.
    bullets = [line for line in out.splitlines() if line.startswith("- ")]
    assert len(bullets) == 2
    assert not any("(b):" in line for line in bullets)


def test_positions_reference_block_preserves_input_order():
    from server.analysis.prompt import _build_positions_reference_block
    out = _build_positions_reference_block([
        _fake_position("second", "Second", "Second cue."),
        _fake_position("first", "First", "First cue."),
    ])
    # Second's cue appears before First's cue in output (input order preserved).
    assert out.index("Second cue.") < out.index("First cue.")


def test_parse_section_response_rejects_malformed_json():
    import pytest
    from server.analysis.prompt import parse_section_response, SectionResponseError
    with pytest.raises(SectionResponseError):
        parse_section_response("not json")


def test_parse_section_response_rejects_missing_field():
    import pytest
    from server.analysis.prompt import parse_section_response, SectionResponseError
    with pytest.raises(SectionResponseError):
        parse_section_response('{"narrative": "x"}')


def test_parse_section_response_rejects_empty_string_field():
    import pytest
    from server.analysis.prompt import parse_section_response, SectionResponseError
    with pytest.raises(SectionResponseError):
        parse_section_response('{"narrative": "", "coach_tip": "x"}')
