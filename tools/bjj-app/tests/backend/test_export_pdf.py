"""Unit tests for M6b PDF export pure helpers."""
from __future__ import annotations

import pytest

from server.export.pdf import (
    format_mm_ss,
    slugify_report_filename,
)


class TestFormatMmSs:
    def test_zero(self):
        assert format_mm_ss(0) == "00:00"

    def test_under_one_minute(self):
        assert format_mm_ss(37) == "00:37"

    def test_exactly_one_minute(self):
        assert format_mm_ss(60) == "01:00"

    def test_several_minutes(self):
        assert format_mm_ss(185) == "03:05"

    def test_accepts_floats_and_truncates(self):
        assert format_mm_ss(62.9) == "01:02"


class TestSlugifyReportFilename:
    def test_simple_title(self):
        assert slugify_report_filename("Tuesday Roll", "2026-04-21") == "tuesday-roll-2026-04-21.pdf"

    def test_lowercases(self):
        assert slugify_report_filename("Hard ROLL", "2026-04-21") == "hard-roll-2026-04-21.pdf"

    def test_strips_special_chars(self):
        assert slugify_report_filename("Roll #3 (comp!)", "2026-04-21") == "roll-3-comp-2026-04-21.pdf"

    def test_collapses_repeats(self):
        assert slugify_report_filename("A   B—C", "2026-04-21") == "a-b-c-2026-04-21.pdf"

    def test_trims_leading_and_trailing(self):
        assert slugify_report_filename("  hello  ", "2026-04-21") == "hello-2026-04-21.pdf"

    def test_empty_title_fallback(self):
        assert slugify_report_filename("", "2026-04-21") == "match-report-2026-04-21.pdf"

    def test_whitespace_only_title_fallback(self):
        assert slugify_report_filename("   ", "2026-04-21") == "match-report-2026-04-21.pdf"


from datetime import datetime, timezone

from server.export.pdf import build_report_context


def _fixture_roll(**overrides):
    base = {
        "id": "abcdef1234567890abcdef1234567890",
        "title": "Tuesday Roll",
        "date": "2026-04-21",
        "duration_s": 245.0,
        "player_a_name": "Greig",
        "player_b_name": "Partner",
        "finalised_at": 1713700000,
        "scores_json": None,  # unused — caller passes parsed dict separately
    }
    base.update(overrides)
    return base


def _fixture_scores():
    return {
        "summary": "Solid guard retention but limited offence from the bottom.",
        "scores": {
            "guard_retention": 7,
            "positional_awareness": 3,
            "transition_quality": 8,
        },
        "top_improvements": [
            "Chain sweeps from closed guard.",
            "Break grips before shrimping.",
        ],
        "strengths": [
            "Strong guard retention.",
            "Calm under pressure.",
        ],
        "key_moments": [
            {"section_id": "sec1", "note": "First sweep attempt."},
            {"section_id": "sec2", "note": "Passed half guard."},
            {"section_id": "sec3", "note": "Back take attempt."},
        ],
    }


def _fixture_sections():
    return [
        {"id": "sec1", "start_s": 12.5, "end_s": 30.0, "narrative": "some narrative"},
        {"id": "sec2", "start_s": 45.0, "end_s": 60.0, "narrative": "another narrative"},
        {"id": "sec3", "start_s": 130.0, "end_s": 150.0, "narrative": "third narrative"},
    ]


class TestBuildReportContext:
    def test_flattens_header_fields(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            sections=_fixture_sections(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["title"] == "Tuesday Roll"
        assert ctx["date_human"] == "21 April 2026"
        assert ctx["player_a_name"] == "Greig"
        assert ctx["player_b_name"] == "Partner"
        assert ctx["duration_human"] == "04:05"
        assert ctx["moments_analysed_count"] == 3
        assert ctx["summary_sentence"] == "Solid guard retention but limited offence from the bottom."
        assert ctx["generated_at_human"] == "2026-04-21 14:32 UTC"
        assert ctx["roll_id_short"] == "abcdef12"

    def test_scores_are_bucketed_and_widthed(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            sections=_fixture_sections(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["scores"] == [
            {"id": "guard_retention", "label": "Guard Retention", "value": 7, "bar_pct": 70, "color_bucket": "high"},
            {"id": "positional_awareness", "label": "Positional Awareness", "value": 3, "bar_pct": 30, "color_bucket": "low"},
            {"id": "transition_quality", "label": "Transition Quality", "value": 8, "bar_pct": 80, "color_bucket": "high"},
        ]

    def test_distribution_bar_is_always_empty(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            sections=_fixture_sections(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["distribution_bar"] == []

    def test_key_moments_resolve_to_mm_ss_and_section_range_labels(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            sections=_fixture_sections(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["key_moments"] == [
            {"timestamp_human": "00:12", "category_label": "00:12–00:30", "blurb": "First sweep attempt."},
            {"timestamp_human": "00:45", "category_label": "00:45–01:00", "blurb": "Passed half guard."},
            {"timestamp_human": "02:10", "category_label": "02:10–02:30", "blurb": "Back take attempt."},
        ]

    def test_improvements_and_strengths_passthrough(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            sections=_fixture_sections(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["improvements"] == [
            "Chain sweeps from closed guard.",
            "Break grips before shrimping.",
        ]
        assert ctx["strengths"] == [
            "Strong guard retention.",
            "Calm under pressure.",
        ]

    def test_missing_section_id_is_skipped(self):
        scores = _fixture_scores()
        scores["key_moments"].append({"section_id": "does-not-exist", "note": "should be dropped"})
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=scores,
            sections=_fixture_sections(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        # Only the three valid sections come through.
        assert len(ctx["key_moments"]) == 3

    def test_raises_when_scores_missing(self):
        with pytest.raises(ValueError, match="scores"):
            build_report_context(
                roll=_fixture_roll(),
                scores=None,
                sections=_fixture_sections(),
                generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
            )


def test_build_report_context_key_moments_resolve_by_section_id():
    from datetime import datetime, timezone
    from server.export.pdf import build_report_context
    roll = {
        "id": "abcdef0123", "title": "T", "date": "2026-04-22",
        "player_a_name": "A", "player_b_name": "B", "duration_s": 60.0,
    }
    scores = {
        "summary": "S",
        "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 7},
        "top_improvements": ["a", "b", "c"],
        "strengths": ["x", "y"],
        "key_moments": [{"section_id": "sec1", "note": "n1"}],
    }
    sections = [{"id": "sec1", "start_s": 3.0, "end_s": 7.0}]
    ctx = build_report_context(
        roll=roll, scores=scores, sections=sections,
        generated_at=datetime.now(timezone.utc),
    )
    assert ctx["distribution_bar"] == []
    assert ctx["key_moments"][0]["timestamp_human"] == "00:03"


def test_render_report_pdf_omits_distribution_section_when_empty():
    from datetime import datetime, timezone
    from server.export.pdf import build_report_context, render_report_pdf
    ctx = build_report_context(
        roll={
            "id": "x" * 16, "title": "T", "date": "2026-04-22",
            "player_a_name": "A", "player_b_name": "B", "duration_s": 60.0,
        },
        scores={
            "summary": "S",
            "scores": {"guard_retention": 7, "positional_awareness": 6, "transition_quality": 7},
            "top_improvements": ["a", "b", "c"],
            "strengths": ["x", "y"],
            "key_moments": [],
        },
        sections=[],
        generated_at=datetime.now(timezone.utc),
    )
    pdf = render_report_pdf(ctx)
    assert pdf[:4] == b"%PDF"


from server.export.pdf import render_report_pdf


def _render_fixture_context():
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
            {"category_id": "guard_bottom", "label": "Guard bottom", "width_pct": 50, "color_class": "cat-guard-bottom"},
            {"category_id": "guard_top", "label": "Guard top", "width_pct": 50, "color_class": "cat-guard-top"},
        ],
        "improvements": ["Chain sweeps."],
        "strengths": ["Strong retention."],
        "key_moments": [
            {"timestamp_human": "00:12", "category_label": "Guard bottom", "blurb": "First sweep attempt."},
        ],
        "generated_at_human": "2026-04-21 14:32 UTC",
        "roll_id_short": "abcdef12",
    }


class TestRenderReportPdf:
    def test_produces_pdf_magic_number(self):
        pdf_bytes = render_report_pdf(_render_fixture_context())
        assert pdf_bytes.startswith(b"%PDF-")

    def test_size_is_reasonable(self):
        pdf_bytes = render_report_pdf(_render_fixture_context())
        # Text-only Page 1 PDFs are typically 8-50KB; give a wide bound.
        assert 3_000 < len(pdf_bytes) < 500_000


from server.export.pdf import render_report_section_body


class TestRenderReportSectionBody:
    def test_contains_obsidian_link(self):
        body = render_report_section_body(
            roll_id="abcdef1234567890abcdef1234567890",
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert "[[assets/abcdef1234567890abcdef1234567890/report.pdf|Match report PDF]]" in body

    def test_contains_generated_at(self):
        body = render_report_section_body(
            roll_id="abcdef1234567890abcdef1234567890",
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert "*Generated 2026-04-21 14:32 UTC*" in body
