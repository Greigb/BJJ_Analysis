"""Tests for vault_writer's summary-section rendering + per-section splice."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.analysis.vault_writer import render_summary_sections


_FIXTURE_CATEGORIES = [
    {"id": "standing", "label": "Standing"},
    {"id": "guard_bottom", "label": "Guard (Bottom)"},
    {"id": "scramble", "label": "Scramble"},
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
        {"moment_id": "m1", "note": "Perfect triangle entry timing."},
        {"moment_id": "m2", "note": "Got swept here — posture broke first."},
        {"moment_id": "m3", "note": "Clean half-guard recovery."},
    ],
}

_FIXTURE_DISTRIBUTION = {
    "timeline": ["standing", "guard_bottom", "guard_bottom", "scramble"],
    "counts": {"standing": 1, "guard_bottom": 2, "scramble": 1},
    "percentages": {"standing": 25, "guard_bottom": 50, "scramble": 25},
}

_FIXTURE_MOMENTS = [
    {"id": "m1", "timestamp_s": 3.0},
    {"id": "m2", "timestamp_s": 45.0},
    {"id": "m3", "timestamp_s": 125.0},
]


def test_render_summary_sections_returns_all_six_keys():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES, distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES, moments=_FIXTURE_MOMENTS,
    )
    assert set(sections.keys()) == {
        "summary", "scores", "position_distribution",
        "key_moments", "top_improvements", "strengths",
    }


def test_render_summary_sections_summary_is_the_prose_sentence():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES, distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES, moments=_FIXTURE_MOMENTS,
    )
    assert sections["summary"].strip() == "A strong roll with good guard retention."


def test_render_summary_sections_scores_renders_as_table():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES, distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES, moments=_FIXTURE_MOMENTS,
    )
    body = sections["scores"]
    assert "| Metric" in body
    assert "| Guard Retention" in body
    assert "8/10" in body
    assert "6/10" in body
    assert "7/10" in body


def test_render_summary_sections_position_distribution_includes_counts_and_bar():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES, distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES, moments=_FIXTURE_MOMENTS,
    )
    body = sections["position_distribution"]
    assert "| Category" in body
    assert "Guard (Bottom)" in body
    assert "50%" in body
    assert "### Position Timeline Bar" in body
    assert "⬜" in body
    assert "🟦" in body
    assert "🟪" in body
    assert "Legend:" in body
    # Legend uses human labels (not raw ids).
    assert "Standing" in body.split("Legend:")[-1]
    assert "Guard (Bottom)" in body.split("Legend:")[-1]


def test_render_summary_sections_key_moments_cite_timestamps():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES, distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES, moments=_FIXTURE_MOMENTS,
    )
    body = sections["key_moments"]
    assert "- **0:03**" in body
    assert "Perfect triangle entry timing." in body
    assert "- **0:45**" in body
    assert "posture broke first" in body
    assert "- **2:05**" in body


def test_render_summary_sections_top_improvements_is_numbered():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES, distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES, moments=_FIXTURE_MOMENTS,
    )
    body = sections["top_improvements"]
    assert "1. Keep elbows tight" in body
    assert "2. Frame earlier" in body
    assert "3. Don't overcommit" in body


def test_render_summary_sections_strengths_is_bulleted():
    sections = render_summary_sections(
        scores_payload=_FIXTURE_SCORES, distribution=_FIXTURE_DISTRIBUTION,
        categories=_FIXTURE_CATEGORIES, moments=_FIXTURE_MOMENTS,
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
    insert_moments,
    set_summary_state,
)


@pytest.fixture
def db_finalised_roll(tmp_path: Path):
    """A roll with 3 moments, annotations, and set_summary_state already called."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    create_roll(
        conn, id="r-1", title="Sample Roll", date="2026-04-21",
        video_path="assets/r-1/source.mp4", duration_s=225.0, partner="Anthony",
        result="unknown", created_at=1700000000,
    )
    moments = insert_moments(
        conn, roll_id="r-1",
        moments=[
            {"frame_idx": 3, "timestamp_s": 3.0, "pose_delta": 1.2},
            {"frame_idx": 45, "timestamp_s": 45.0, "pose_delta": 0.9},
            {"frame_idx": 125, "timestamp_s": 125.0, "pose_delta": 1.0},
        ],
    )
    insert_annotation(conn, moment_id=moments[0]["id"], body="first note", created_at=1700000100)

    scores_payload = {
        "summary": "A strong roll with good guard retention.",
        "scores": {"guard_retention": 8, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["imp one", "imp two", "imp three"],
        "strengths": ["st one", "st two"],
        "key_moments": [
            {"moment_id": moments[0]["id"], "note": "Perfect entry"},
            {"moment_id": moments[1]["id"], "note": "Where the sweep reversed"},
            {"moment_id": moments[2]["id"], "note": "Clean recovery"},
        ],
    }
    set_summary_state(
        conn, roll_id="r-1", scores_payload=scores_payload, finalised_at=1700000500,
    )
    taxonomy = {
        "categories": [
            {"id": "standing", "label": "Standing"},
            {"id": "guard_bottom", "label": "Guard (Bottom)"},
            {"id": "scramble", "label": "Scramble"},
        ],
        "positions": [],
        "transitions": [],
    }
    try:
        yield conn, tmp_path, taxonomy
    finally:
        conn.close()


def test_publish_finalised_roll_emits_all_summary_sections(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    result = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    text = (vault_root / result.vault_path).read_text()
    assert "## Summary" in text
    assert "## Scores" in text
    assert "## Position Distribution" in text
    assert "## Key Moments" in text
    assert "## Top Improvements" in text
    assert "## Strengths Observed" in text
    assert "## Your Notes" in text
    your_notes_idx = text.index("## Your Notes")
    for section in (
        "## Summary", "## Scores", "## Position Distribution",
        "## Key Moments", "## Top Improvements", "## Strengths Observed",
    ):
        assert text.index(section) < your_notes_idx


def test_publish_unfinalised_roll_has_your_notes_only(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    conn.execute("UPDATE rolls SET scores_json = NULL, finalised_at = NULL WHERE id = 'r-1'")
    conn.commit()
    result = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    text = (vault_root / result.vault_path).read_text()
    assert "## Your Notes" in text
    assert "## Summary" not in text
    assert "## Scores" not in text


def test_publish_second_time_splices_owned_sections_preserves_user_sections(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    full = vault_root / first.vault_path
    existing = full.read_text()
    existing += "\n## Extra thoughts\n\nSomething personal.\n"
    full.write_text(existing)
    publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy, force=True)
    text_after = full.read_text()
    assert "## Extra thoughts" in text_after
    assert "Something personal." in text_after


def test_publish_raises_conflict_when_summary_section_edited_externally(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    full = vault_root / first.vault_path
    text = full.read_text().replace(
        "A strong roll with good guard retention.",
        "EDITED IN OBSIDIAN — a strong roll.",
    )
    full.write_text(text)
    with pytest.raises(ConflictError):
        publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)


def test_publish_force_overrides_summary_section_conflict(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    full = vault_root / first.vault_path
    text = full.read_text().replace("A strong roll", "EDITED IN OBSIDIAN — a strong roll")
    full.write_text(text)
    result = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy, force=True)
    text_after = (vault_root / result.vault_path).read_text()
    assert "EDITED IN OBSIDIAN" not in text_after
    assert "A strong roll with good guard retention." in text_after


def test_publish_conflict_does_not_fire_on_unrelated_section_edit(db_finalised_roll):
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    full = vault_root / first.vault_path
    text = full.read_text() + "\n## Extra thoughts\n\nUser added this, not owned.\n"
    full.write_text(text)
    publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)


def test_publish_unfinalised_then_finalised_emits_sections_in_canonical_order(db_finalised_roll):
    """Regression: a file first published without scores, then finalised,
    must end up with summary sections BEFORE Your Notes (canonical order)."""
    conn, vault_root, taxonomy = db_finalised_roll
    # Un-finalise for the first publish.
    conn.execute("UPDATE rolls SET scores_json = NULL, finalised_at = NULL WHERE id = 'r-1'")
    conn.commit()
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    text_first = (vault_root / first.vault_path).read_text()
    assert "## Summary" not in text_first
    assert "## Your Notes" in text_first

    # Re-finalise (restore scores_json + finalised_at).
    scores_payload = {
        "summary": "A second-pass roll.",
        "scores": {"guard_retention": 7, "positional_awareness": 7, "transition_quality": 7},
        "top_improvements": ["x", "y", "z"],
        "strengths": ["s1", "s2"],
        "key_moments": [
            {"moment_id": m["id"], "note": f"n{i}"}
            for i, m in enumerate(
                conn.execute(
                    "SELECT id FROM moments WHERE roll_id='r-1' ORDER BY timestamp_s"
                ).fetchall()[:3]
            )
        ],
    }
    set_summary_state(conn, roll_id="r-1", scores_payload=scores_payload, finalised_at=1700000500)

    second = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
    text_second = (vault_root / second.vault_path).read_text()

    # All six summary sections present, and all before Your Notes.
    your_notes_idx = text_second.index("## Your Notes")
    for heading in (
        "## Summary", "## Scores", "## Position Distribution",
        "## Key Moments", "## Top Improvements", "## Strengths Observed",
    ):
        assert heading in text_second
        assert text_second.index(heading) < your_notes_idx


def test_publish_after_user_deletes_summary_section_reinserts_in_order(db_finalised_roll):
    """Regression: if the user deletes one summary section in Obsidian, the next
    (force) publish must reinsert it at its canonical position — NOT at EOF."""
    conn, vault_root, taxonomy = db_finalised_roll
    first = publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy)
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
    publish(conn, roll_id="r-1", vault_root=vault_root, taxonomy=taxonomy, force=True)
    text_after = full.read_text()

    # Summary is back AND before Scores AND before Your Notes.
    assert "## Summary" in text_after
    assert text_after.index("## Summary") < text_after.index("## Scores")
    assert text_after.index("## Summary") < text_after.index("## Your Notes")
