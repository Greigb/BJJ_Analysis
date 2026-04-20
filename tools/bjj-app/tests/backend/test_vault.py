from pathlib import Path

import pytest

from server.analysis.vault import RollSummary, list_rolls


def test_list_rolls_returns_summaries_sorted_newest_first(sample_vault: Path):
    rolls = list_rolls(sample_vault)

    assert len(rolls) == 2
    assert all(isinstance(r, RollSummary) for r in rolls)

    assert rolls[0].date == "2026-04-14"
    assert rolls[0].partner == "Anthony"
    assert rolls[0].duration == "2:23"
    assert rolls[0].result == "win_submission"
    assert rolls[0].title == "Roll 1: Greig vs Anthony — WIN by Submission"
    assert rolls[0].path.name == "2026-04-14 - sample roll (win).md"

    assert rolls[1].date == "2026-04-01"
    assert rolls[1].partner == "Bob"


def test_list_rolls_handles_missing_roll_log_dir(tmp_path: Path):
    # No Roll Log/ subdir — should return empty list, not raise.
    rolls = list_rolls(tmp_path)
    assert rolls == []


def test_list_rolls_skips_files_without_frontmatter(tmp_path: Path):
    roll_log = tmp_path / "Roll Log"
    roll_log.mkdir()
    (roll_log / "no_frontmatter.md").write_text("# Just a markdown file\n")
    (roll_log / "has_frontmatter.md").write_text(
        "---\ndate: 2026-01-01\nresult: draw\n---\n# Has frontmatter\n"
    )

    rolls = list_rolls(tmp_path)
    assert len(rolls) == 1
    assert rolls[0].title == "Has frontmatter"
