"""Tests for the Positions/ vault index."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.analysis.positions_vault import get_position, load_positions_index


def _write_position(root: Path, filename: str, frontmatter_lines: list[str], body: str) -> None:
    pos_dir = root / "Positions"
    pos_dir.mkdir(exist_ok=True)
    text = "---\n" + "\n".join(frontmatter_lines) + "\n---\n\n" + body
    (pos_dir / filename).write_text(text)


def test_load_positions_index_returns_empty_when_positions_dir_missing(tmp_path: Path):
    assert load_positions_index(tmp_path) == {}


def test_load_positions_index_includes_position_with_position_id_frontmatter(tmp_path: Path):
    _write_position(
        tmp_path,
        "Closed Guard (Bottom).md",
        ['category: "Guard (Bottom)"', "position_id: closed_guard_bottom"],
        "# Closed Guard (Bottom)\n\nBody text.\n",
    )
    idx = load_positions_index(tmp_path)
    assert "closed_guard_bottom" in idx
    entry = idx["closed_guard_bottom"]
    assert entry["name"] == "Closed Guard (Bottom)"
    assert "Body text." in entry["markdown"]
    assert entry["vault_path"] == "Positions/Closed Guard (Bottom).md"


def test_load_positions_index_skips_position_without_position_id(tmp_path: Path):
    _write_position(
        tmp_path,
        "Nameless.md",
        ['category: "Other"'],
        "# Nameless\n",
    )
    assert load_positions_index(tmp_path) == {}


def test_load_positions_index_name_falls_back_to_first_h1(tmp_path: Path):
    _write_position(
        tmp_path,
        "fallback.md",
        ["position_id: abc"],
        "# My Cool Position\n\nDetails.\n",
    )
    idx = load_positions_index(tmp_path)
    assert idx["abc"]["name"] == "My Cool Position"


def test_load_positions_index_name_falls_back_to_stem_if_no_h1(tmp_path: Path):
    _write_position(tmp_path, "stem-name.md", ["position_id: abc"], "No header.\n")
    idx = load_positions_index(tmp_path)
    assert idx["abc"]["name"] == "stem-name"


def test_get_position_returns_entry_for_known_id(tmp_path: Path):
    _write_position(
        tmp_path,
        "A.md",
        ["position_id: a"],
        "# A\nbody",
    )
    idx = load_positions_index(tmp_path)
    entry = get_position(idx, "a")
    assert entry is not None
    assert entry["position_id"] == "a"


def test_get_position_returns_none_for_unknown_id(tmp_path: Path):
    idx: dict = {}
    assert get_position(idx, "nope") is None


def test_load_positions_index_markdown_body_includes_frontmatter_removed(tmp_path: Path):
    _write_position(
        tmp_path,
        "body.md",
        ["position_id: b"],
        "# B\n\nSecond line.\n",
    )
    idx = load_positions_index(tmp_path)
    md = idx["b"]["markdown"]
    # frontmatter delimiters should not be present in the markdown body
    assert md.strip().startswith("# B")
    assert "---" not in md.split("\n")[0]


# ---------- M10: how_to_identify extraction ----------


def test_load_positions_index_extracts_how_to_identify_single_paragraph(tmp_path: Path):
    _write_position(
        tmp_path,
        "CG.md",
        ["position_id: closed_guard_bottom"],
        (
            "# Closed Guard\n\n"
            "## How to Identify\n\n"
            "Ankles LOCKED behind the top person's back.\n\n"
            "## Transitions\n\nStuff.\n"
        ),
    )
    entry = load_positions_index(tmp_path)["closed_guard_bottom"]
    assert entry["how_to_identify"] == "Ankles LOCKED behind the top person's back."


def test_load_positions_index_extracts_how_to_identify_multi_paragraph(tmp_path: Path):
    _write_position(
        tmp_path,
        "SC.md",
        ["position_id: side_control_top"],
        (
            "# Side Control\n\n"
            "## How to Identify\n\n"
            "First paragraph describing the position.\n\n"
            "Second paragraph with more cues.\n\n"
            "## Transitions\n\nFoo.\n"
        ),
    )
    entry = load_positions_index(tmp_path)["side_control_top"]
    assert entry["how_to_identify"] == (
        "First paragraph describing the position.\n\n"
        "Second paragraph with more cues."
    )


def test_load_positions_index_returns_none_when_how_to_identify_missing(tmp_path: Path):
    _write_position(
        tmp_path,
        "Scramble.md",
        ["position_id: scramble_generic"],
        "# Scramble\n\n## Techniques\n\nSome techniques.\n",
    )
    entry = load_positions_index(tmp_path)["scramble_generic"]
    assert entry["how_to_identify"] is None


def test_load_positions_index_how_to_identify_stops_at_next_heading_without_blank_line(
    tmp_path: Path,
):
    """A `## ` immediately after the body (no blank line) must still terminate."""
    _write_position(
        tmp_path,
        "X.md",
        ["position_id: x"],
        (
            "# X\n\n"
            "## How to Identify\n\n"
            "One-liner identification.\n"
            "## Techniques\n\nFoo.\n"
        ),
    )
    entry = load_positions_index(tmp_path)["x"]
    assert entry["how_to_identify"] == "One-liner identification."
