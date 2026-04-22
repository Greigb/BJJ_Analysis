"""Snapshot test for the M6b Jinja HTML template.

The test passes a known context through the template and asserts on key
markers. If the template changes intentionally, update the asserted strings.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import jinja2


TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "server" / "export" / "templates"


def _render(context: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    return env.get_template("report.html.j2").render(**context)


def _fixture_context():
    return {
        "title": "Tuesday Roll",
        "date_human": "21 April 2026",
        "player_a_name": "Greig",
        "player_b_name": "Partner",
        "duration_human": "04:05",
        "moments_analysed_count": 3,
        "summary_sentence": "Solid guard retention but limited offence.",
        "scores": [
            {"id": "guard_retention", "label": "Guard Retention", "value": 7, "bar_pct": 70, "color_bucket": "high"},
            {"id": "positional_awareness", "label": "Positional Awareness", "value": 3, "bar_pct": 30, "color_bucket": "low"},
            {"id": "transition_quality", "label": "Transition Quality", "value": 8, "bar_pct": 80, "color_bucket": "high"},
        ],
        "distribution_bar": [
            {"category_id": "guard_bottom", "label": "Guard bottom", "width_pct": 33, "color_class": "cat-guard-bottom"},
            {"category_id": "guard_top", "label": "Guard top", "width_pct": 34, "color_class": "cat-guard-top"},
            {"category_id": "scramble", "label": "Scramble", "width_pct": 33, "color_class": "cat-scramble"},
        ],
        "improvements": ["Chain sweeps.", "Break grips early."],
        "strengths": ["Strong retention.", "Calm under pressure."],
        "key_moments": [
            {"timestamp_human": "00:12", "category_label": "Guard bottom", "blurb": "First sweep attempt."},
            {"timestamp_human": "00:45", "category_label": "Guard top", "blurb": "Passed half guard."},
            {"timestamp_human": "02:10", "category_label": "Scramble", "blurb": "Back take attempt."},
        ],
        "generated_at_human": "2026-04-21 14:32 UTC",
        "roll_id_short": "abcdef12",
    }


def test_template_renders_title_and_subtitle():
    html = _render(_fixture_context())
    assert "Tuesday Roll" in html
    assert "Greig vs Partner" in html
    assert "04:05" in html
    assert "3 moments analysed" in html


def test_template_renders_summary_sentence():
    html = _render(_fixture_context())
    assert "Solid guard retention" in html


def test_template_renders_three_score_boxes_with_buckets():
    html = _render(_fixture_context())
    assert 'class="score-box bucket-high"' in html  # first score
    assert 'class="score-box bucket-low"' in html   # second score
    assert ">7<" in html
    assert "Guard Retention" in html
    assert "width: 70%" in html


def test_template_renders_distribution_segments():
    html = _render(_fixture_context())
    assert 'class="dist-seg cat-guard-bottom"' in html
    assert "width: 33%" in html
    # Segment label appears inline.
    assert "Guard bottom 33%" in html


def test_template_renders_improvements_as_ordered_list():
    html = _render(_fixture_context())
    # Ordered list for improvements, unordered for strengths.
    assert "<ol" in html and "Chain sweeps." in html
    assert "<ul" in html and "Strong retention." in html


def test_template_renders_key_moments_table_rows():
    html = _render(_fixture_context())
    assert "<td" in html
    assert "00:12" in html
    assert "Guard bottom" in html
    assert "First sweep attempt." in html


def test_template_renders_footer():
    html = _render(_fixture_context())
    assert "2026-04-21 14:32 UTC" in html
    assert "abcdef12" in html
