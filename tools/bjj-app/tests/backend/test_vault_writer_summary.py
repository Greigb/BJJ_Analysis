"""Tests for vault_writer's summary-section rendering + per-section splice."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.analysis.vault_writer import render_summary_sections


_FIXTURE_SECTIONS = [
    {"id": "s1", "start_s": 3.0, "end_s": 9.0},
    {"id": "s2", "start_s": 45.0, "end_s": 60.0},
    {"id": "s3", "start_s": 125.0, "end_s": 140.0},
]

_FIXTURE_SCORES = {
    "summary": "A strong roll with good guard retention.",
    "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
    "top_improvements": [
        "Keep elbows tight when posture is broken.",
        "Frame earlier when the pass shot fires.",
        "Don't overcommit to hip-bump sweeps.",
    ],
    "strengths": ["Patient grips", "Strong closed guard"],
    "key_moments": [
        {"section_id": "s1", "note": "Perfect triangle entry timing."},
        {"section_id": "s2", "note": "Got swept here — posture broke first."},
        {"section_id": "s3", "note": "Clean half-guard recovery."},
    ],
}


def test_render_summary_sections_returns_all_five_keys():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        sections=_FIXTURE_SECTIONS,
    )
    assert set(sections.keys()) == {
        "summary", "scores",
        "key_moments", "top_improvements", "strengths",
    }


def test_render_summary_sections_summary_is_the_prose_sentence():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        sections=_FIXTURE_SECTIONS,
    )
    assert sections["summary"].strip() == "A strong roll with good guard retention."


def test_render_summary_sections_scores_renders_as_table():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        sections=_FIXTURE_SECTIONS,
    )
    body = sections["scores"]
    assert "| Metric" in body
    assert "| Guard Retention" in body
    assert "8/10" in body
    assert "6/10" in body
    assert "7/10" in body


def test_render_summary_sections_key_moments_cite_section_ranges():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        sections=_FIXTURE_SECTIONS,
    )
    body = sections["key_moments"]
    # s1: 3s – 9s  →  "0:03 – 0:09"
    assert "0:03 – 0:09" in body
    assert "Perfect triangle entry timing." in body
    # s2: 45s – 60s  →  "0:45 – 1:00"
    assert "0:45 – 1:00" in body
    assert "posture broke first" in body
    # s3: 125s – 140s  →  "2:05 – 2:20"
    assert "2:05 – 2:20" in body


def test_render_summary_sections_key_moments_unknown_section_id():
    payload = dict(_FIXTURE_SCORES)
    payload["key_moments"] = [{"section_id": "missing-id", "note": "fallback note"}]
    sections = render_summary_sections(
        scores_payload=payload,
        sections=_FIXTURE_SECTIONS,
    )
    body = sections["key_moments"]
    assert "?:??" in body
    assert "fallback note" in body


def test_render_summary_sections_top_improvements_is_numbered():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        sections=_FIXTURE_SECTIONS,
    )
    body = sections["top_improvements"]
    assert "1. Keep elbows tight" in body
    assert "2. Frame earlier" in body
    assert "3. Don't overcommit" in body


def test_render_summary_sections_strengths_is_bulleted():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES,
        sections=_FIXTURE_SECTIONS,
    )
    body = sections["strengths"]
    assert "- Patient grips" in body
    assert "- Strong closed guard" in body


# ---------- publish() extended with summary sections ----------


import json  # noqa: E402
import time  # noqa: E402

from server.analysis.vault_writer import ConflictError, publish  # noqa: E402
from server.db import (  # noqa: E402
    connect,
    create_roll,
    init_db,
    insert_annotation,
    insert_section,
    set_summary_state,
)


@pytest.fixture
def db_finalised_roll(tmp_path: Path):
    """A roll with 3 sections, annotations, and set_summary_state already called."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn, id="r-1", title="Sample Roll", date="2026-04-21",
        video_path="assets/r-1/source.mp4", duration_s=225.0, partner="Anthony",
        result="unknown", created_at=1700000000,
    )
    sec1 = insert_section(conn, roll_id="r-1", start_s=3.0, end_s=9.0, sample_interval_s=1.0)
    sec2 = insert_section(conn, roll_id="r-1", start_s=45.0, end_s=55.0, sample_interval_s=1.0)
    sec3 = insert_section(conn, roll_id="r-1", start_s=125.0, end_s=135.0, sample_interval_s=1.0)
    insert_annotation(conn, section_id=sec1["id"], body="first note", created_at=1700000100)

    scores_payload = {
        "summary": "A strong roll with good guard retention.",
        "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["imp one", "imp two", "imp three"],
        "strengths": ["st one", "st two"],
        "key_moments": [
            {"section_id": sec1["id"], "note": "Perfect entry"},
            {"section_id": sec2["id"], "note": "Where the sweep reversed"},
            {"section_id": sec3["id"], "note": "Clean recovery"},
        ],
    }
    set_summary_state(
        conn, roll_id="r-1", scores_payload=scores_payload, finalised_at=1700000500,
    )
    try:
        yield conn, tmp_path
    finally:
        conn.close()


def test_publish_finalised_roll_emits_all_summary_sections(db_finalised_roll):
    conn, vault_root = db_finalised_roll
    result = publish(conn, roll_id="r-1", vault_root=vault_root)
    text = (vault_root / result.vault_path).read_text()
    assert "## Summary" in text
    assert "## Scores" in text
    assert "## Key Moments" in text
    assert "## Top Improvements" in text
    assert "## Strengths Observed" in text
    assert "## Your Notes" in text
    # Position Distribution should NOT be present post-M9b
    assert "## Position Distribution" not in text
    your_notes_idx = text.index("## Your Notes")
    for section in (
        "## Summary", "## Scores",
        "## Key Moments", "## Top Improvements", "## Strengths Observed",
    ):
        assert text.index(section) < your_notes_idx


def test_publish_unfinalised_roll_has_your_notes_only(db_finalised_roll):
    conn, vault_root = db_finalised_roll
    conn.execute("UPDATE rolls SET scores_json = NULL, finalised_at = NULL WHERE id = 'r-1'")
    conn.commit()
    result = publish(conn, roll_id="r-1", vault_root=vault_root)
    text = (vault_root / result.vault_path).read_text()
    assert "## Your Notes" in text
    assert "## Summary" not in text
    assert "## Scores" not in text


def test_publish_second_time_splices_owned_sections_preserves_user_sections(db_finalised_roll):
    conn, vault_root = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path
    existing = full.read_text()
    existing += "\n## Extra thoughts\n\nSomething personal.\n"
    full.write_text(existing)
    publish(conn, roll_id="r-1", vault_root=vault_root, force=True)
    text_after = full.read_text()
    assert "## Extra thoughts" in text_after
    assert "Something personal." in text_after


def test_publish_raises_conflict_when_summary_section_edited_externally(db_finalised_roll):
    conn, vault_root = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path
    text = full.read_text().replace(
        "A strong roll with good guard retention.",
        "EDITED IN OBSIDIAN — a strong roll.",
    )
    full.write_text(text)
    with pytest.raises(ConflictError):
        publish(conn, roll_id="r-1", vault_root=vault_root)


def test_publish_force_overrides_summary_section_conflict(db_finalised_roll):
    conn, vault_root = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path
    text = full.read_text().replace("A strong roll", "EDITED IN OBSIDIAN — a strong roll")
    full.write_text(text)
    result = publish(conn, roll_id="r-1", vault_root=vault_root, force=True)
    text_after = (vault_root / result.vault_path).read_text()
    assert "EDITED IN OBSIDIAN" not in text_after
    assert "A strong roll with good guard retention." in text_after


def test_publish_conflict_does_not_fire_on_unrelated_section_edit(db_finalised_roll):
    conn, vault_root = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path
    text = full.read_text() + "\n## Extra thoughts\n\nUser added this, not owned.\n"
    full.write_text(text)
    publish(conn, roll_id="r-1", vault_root=vault_root)


def test_publish_unfinalised_then_finalised_emits_sections_in_canonical_order(db_finalised_roll):
    """Regression: a file first published without scores, then finalised,
    must end up with summary sections BEFORE Your Notes (canonical order)."""
    conn, vault_root = db_finalised_roll
    # Un-finalise for the first publish.
    conn.execute("UPDATE rolls SET scores_json = NULL, finalised_at = NULL WHERE id = 'r-1'")
    conn.commit()
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    text_first = (vault_root / first.vault_path).read_text()
    assert "## Summary" not in text_first
    assert "## Your Notes" in text_first

    # Re-finalise (restore scores_json + finalised_at).
    section_rows = conn.execute(
        "SELECT id FROM sections WHERE roll_id='r-1' ORDER BY start_s"
    ).fetchall()
    scores_payload = {
        "summary": "A second-pass roll.",
        "scores": {"guard_retention": 7, "positional_awareness": 7, "transition_quality": 7},
        "top_improvements": ["x", "y", "z"],
        "strengths": ["s1", "s2"],
        "key_moments": [
            {"section_id": r["id"], "note": f"n{i}"}
            for i, r in enumerate(section_rows[:3])
        ],
    }
    set_summary_state(conn, roll_id="r-1", scores_payload=scores_payload, finalised_at=1700000500)

    second = publish(conn, roll_id="r-1", vault_root=vault_root)
    text_second = (vault_root / second.vault_path).read_text()

    # All five summary sections present, and all before Your Notes.
    your_notes_idx = text_second.index("## Your Notes")
    for heading in (
        "## Summary", "## Scores",
        "## Key Moments", "## Top Improvements", "## Strengths Observed",
    ):
        assert heading in text_second
        assert text_second.index(heading) < your_notes_idx


def test_publish_after_user_deletes_summary_section_reinserts_in_order(db_finalised_roll):
    """Regression: if the user deletes one summary section in Obsidian, the next
    (force) publish must reinsert it at its canonical position — NOT at EOF."""
    conn, vault_root = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root)
    full = vault_root / first.vault_path
    text = full.read_text()

    # Delete the `## Summary` section block (from `## Summary` line through the next `## `).
    import re as _re
    text_minus_summary = _re.sub(
        r"## Summary\n\n.*?(?=\n## )", "", text, count=1, flags=_re.DOTALL
    )
    full.write_text(text_minus_summary)
    assert "## Summary" not in full.read_text()

    # Re-publish with force (hash changed because section removed).
    publish(conn, roll_id="r-1", vault_root=vault_root, force=True)
    text_after = full.read_text()

    # Summary is back AND before Scores AND before Your Notes.
    assert "## Summary" in text_after
    assert text_after.index("## Summary") < text_after.index("## Scores")
    assert text_after.index("## Summary") < text_after.index("## Your Notes")
