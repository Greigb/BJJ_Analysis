"""Tests for server.analysis.techniques_vault."""
from __future__ import annotations

import logging
from pathlib import Path

from server.analysis.positions_vault import load_positions_index
from server.analysis.techniques_vault import (
    load_techniques_index,
    techniques_for_positions,
)


def _make_position(tmp_path: Path, pid: str, name: str, how_to: str) -> None:
    positions_dir = tmp_path / "Positions"
    positions_dir.mkdir(exist_ok=True)
    (positions_dir / f"{name}.md").write_text(
        f"---\nposition_id: {pid}\n---\n\n# {name}\n\n## How to Identify\n\n{how_to}\n"
    )


def _make_technique(
    tmp_path: Path,
    filename: str,
    tid: str,
    used_from: list[str],
    how_to: str | None = None,
) -> None:
    techniques_dir = tmp_path / "Techniques"
    techniques_dir.mkdir(exist_ok=True)
    used_from_block = "\n".join(f"- [[{u}]]" for u in used_from)
    how_to_block = f"\n## How to Identify\n\n{how_to}\n\n" if how_to else ""
    (techniques_dir / filename).write_text(
        f"---\ntags: [technique]\ntechnique_id: {tid}\n---\n\n"
        f"# {filename[:-3]}\n\n"
        f"## Used from\n\n{used_from_block}\n\n"
        f"{how_to_block}"
        f"## Description\n\nfoo\n"
    )


def test_load_techniques_index_parses_basic_note(tmp_path):
    _make_position(tmp_path, "closed_guard_bottom", "Closed Guard (Bottom)", "Ankles LOCKED.")
    _make_technique(
        tmp_path, "Armbar.md", "armbar",
        used_from=["Closed Guard (Bottom)"],
        how_to="Isolate the arm, break grip, finish.",
    )
    positions = load_positions_index(tmp_path)
    techniques = load_techniques_index(tmp_path, positions)

    assert "armbar" in techniques
    t = techniques["armbar"]
    assert t["technique_id"] == "armbar"
    assert t["name"] == "Armbar"
    assert t["used_from_position_ids"] == ["closed_guard_bottom"]
    assert t["how_to_identify"] == "Isolate the arm, break grip, finish."
    assert t["vault_path"] == "Techniques/Armbar.md"


def test_load_techniques_index_skips_notes_without_technique_id(tmp_path):
    techniques_dir = tmp_path / "Techniques"
    techniques_dir.mkdir()
    (techniques_dir / "NoId.md").write_text("---\ntags: [technique]\n---\n\n# NoId\n")
    assert load_techniques_index(tmp_path, {}) == {}


def test_load_techniques_index_missing_directory_returns_empty(tmp_path):
    assert load_techniques_index(tmp_path, {}) == {}


def test_load_techniques_index_drops_unresolved_wikilinks_with_warning(tmp_path, caplog):
    _make_position(tmp_path, "closed_guard_bottom", "Closed Guard (Bottom)", "Ankles LOCKED.")
    _make_technique(
        tmp_path, "Armbar.md", "armbar",
        used_from=["Closed Guard (Bottom)", "Nonexistent Position"],
    )
    positions = load_positions_index(tmp_path)

    with caplog.at_level(logging.WARNING, logger="server.analysis.techniques_vault"):
        techniques = load_techniques_index(tmp_path, positions)

    assert techniques["armbar"]["used_from_position_ids"] == ["closed_guard_bottom"]
    assert any("Nonexistent Position" in r.message for r in caplog.records)


def test_load_techniques_index_accepts_alias_wikilink_form(tmp_path):
    """`[[Closed Guard (Bottom)|guard]]` should resolve via the pre-pipe text."""
    _make_position(tmp_path, "closed_guard_bottom", "Closed Guard (Bottom)", "Ankles LOCKED.")
    techniques_dir = tmp_path / "Techniques"
    techniques_dir.mkdir(exist_ok=True)
    (techniques_dir / "Armbar.md").write_text(
        "---\ntechnique_id: armbar\n---\n\n"
        "# Armbar\n\n"
        "## Used from\n\n- [[Closed Guard (Bottom)|guard]]\n"
    )
    positions = load_positions_index(tmp_path)
    techniques = load_techniques_index(tmp_path, positions)
    assert techniques["armbar"]["used_from_position_ids"] == ["closed_guard_bottom"]


def test_techniques_for_positions_filters_and_orders_by_taxonomy(tmp_path):
    _make_position(tmp_path, "p1", "P One", "...")
    _make_position(tmp_path, "p2", "P Two", "...")
    _make_technique(tmp_path, "T1.md", "t1", ["P One"])
    _make_technique(tmp_path, "T2.md", "t2", ["P Two"])
    _make_technique(tmp_path, "T3.md", "t3", ["P One"])
    positions = load_positions_index(tmp_path)
    techniques = load_techniques_index(tmp_path, positions)

    # Taxonomy order [t3, t1, t2]; only t3 + t1 link to p1.
    out = techniques_for_positions(
        techniques_index=techniques,
        position_ids={"p1"},
        taxonomy={"techniques": [{"id": "t3"}, {"id": "t1"}, {"id": "t2"}]},
    )
    assert [t["technique_id"] for t in out] == ["t3", "t1"]


def test_techniques_for_positions_caps_output(tmp_path):
    _make_position(tmp_path, "p1", "P One", "...")
    for i in range(10):
        _make_technique(tmp_path, f"T{i}.md", f"t{i}", ["P One"])
    positions = load_positions_index(tmp_path)
    techniques = load_techniques_index(tmp_path, positions)
    out = techniques_for_positions(
        techniques_index=techniques,
        position_ids={"p1"},
        taxonomy={"techniques": [{"id": f"t{i}"} for i in range(10)]},
        max_per_position=3,
    )
    assert len(out) == 3


def test_techniques_for_positions_drops_missing_vault_entries(tmp_path):
    _make_position(tmp_path, "p1", "P One", "...")
    _make_technique(tmp_path, "T1.md", "t1", ["P One"])
    positions = load_positions_index(tmp_path)
    techniques = load_techniques_index(tmp_path, positions)
    # Taxonomy lists t2 but vault doesn't have it — silently dropped.
    out = techniques_for_positions(
        techniques_index=techniques,
        position_ids={"p1"},
        taxonomy={"techniques": [{"id": "t1"}, {"id": "t2"}]},
    )
    assert [t["technique_id"] for t in out] == ["t1"]
