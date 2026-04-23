"""Tests for server.eval.cli — argparse wiring."""
from __future__ import annotations

import pytest

from server.eval.cli import _build_parser


def test_cli_parser_section_subcommand_accepts_required_args(tmp_path):
    parser = _build_parser()
    args = parser.parse_args([
        "section",
        "--fixture", str(tmp_path / "f.yaml"),
        "--variants", "m9b-baseline", "m10-grounded",
        "--output", str(tmp_path / "out.md"),
        "--run-name", "smoke",
    ])
    assert args.command == "section"
    assert args.variants == ["m9b-baseline", "m10-grounded"]
    assert args.run_name == "smoke"


def test_cli_parser_summary_subcommand_accepts_required_args(tmp_path):
    parser = _build_parser()
    args = parser.parse_args([
        "summary",
        "--fixture", str(tmp_path / "f.yaml"),
        "--variants", "current",
        "--output", str(tmp_path / "out.md"),
    ])
    assert args.command == "summary"
    assert args.variants == ["current"]


def test_cli_parser_requires_command():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_cli_parser_rejects_unknown_command():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["bogus"])
