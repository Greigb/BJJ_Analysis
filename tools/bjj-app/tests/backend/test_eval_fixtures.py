"""Tests for server.eval.fixtures — YAML fixture loaders."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.eval.fixtures import (
    FixtureError,
    load_section_fixture,
    load_summary_fixture,
)


def test_load_section_fixture_returns_list_of_entries(tmp_path):
    path = tmp_path / "sections.yaml"
    path.write_text(
        "sections:\n"
        "  - roll_id: roll-1\n"
        "    section_id: sec-1\n"
        "    note: first\n"
        "  - roll_id: roll-1\n"
        "    section_id: sec-2\n"
    )
    out = load_section_fixture(path)
    assert len(out) == 2
    assert out[0] == {"roll_id": "roll-1", "section_id": "sec-1", "note": "first"}
    assert out[1]["section_id"] == "sec-2"
    assert out[1]["note"] is None


def test_load_section_fixture_rejects_missing_sections_key(tmp_path):
    path = tmp_path / "sections.yaml"
    path.write_text("not_sections: []\n")
    with pytest.raises(FixtureError):
        load_section_fixture(path)


def test_load_section_fixture_rejects_entry_without_roll_id(tmp_path):
    path = tmp_path / "sections.yaml"
    path.write_text(
        "sections:\n"
        "  - section_id: sec-1\n"
    )
    with pytest.raises(FixtureError):
        load_section_fixture(path)


def test_load_section_fixture_rejects_entry_without_section_id(tmp_path):
    path = tmp_path / "sections.yaml"
    path.write_text(
        "sections:\n"
        "  - roll_id: roll-1\n"
    )
    with pytest.raises(FixtureError):
        load_section_fixture(path)


def test_load_section_fixture_returns_empty_list_for_empty_sections(tmp_path):
    path = tmp_path / "sections.yaml"
    path.write_text("sections: []\n")
    assert load_section_fixture(path) == []


def test_load_summary_fixture_returns_list_of_entries(tmp_path):
    path = tmp_path / "summary.yaml"
    path.write_text(
        "rolls:\n"
        "  - roll_id: roll-1\n"
        "    note: a note\n"
        "  - roll_id: roll-2\n"
    )
    out = load_summary_fixture(path)
    assert len(out) == 2
    assert out[0] == {"roll_id": "roll-1", "note": "a note"}
    assert out[1]["note"] is None


def test_load_summary_fixture_rejects_missing_rolls_key(tmp_path):
    path = tmp_path / "summary.yaml"
    path.write_text("not_rolls: []\n")
    with pytest.raises(FixtureError):
        load_summary_fixture(path)


def test_load_summary_fixture_rejects_entry_without_roll_id(tmp_path):
    path = tmp_path / "summary.yaml"
    path.write_text(
        "rolls:\n"
        "  - note: oops\n"
    )
    with pytest.raises(FixtureError):
        load_summary_fixture(path)
