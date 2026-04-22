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


def _fixture_taxonomy():
    return {
        "categories": [
            {"id": "guard_top", "label": "Guard top"},
            {"id": "guard_bottom", "label": "Guard bottom"},
            {"id": "standing", "label": "Standing"},
            {"id": "scramble", "label": "Scramble"},
        ],
        "positions": [
            {"id": "closed_guard_bottom", "category": "guard_bottom"},
            {"id": "closed_guard_top", "category": "guard_top"},
        ],
    }


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
            {"moment_id": "m1", "note": "First sweep attempt."},
            {"moment_id": "m2", "note": "Passed half guard."},
            {"moment_id": "m3", "note": "Back take attempt."},
        ],
    }


def _fixture_moments():
    return [
        {"id": "m1", "frame_idx": 30, "timestamp_s": 12.5, "category": "guard_bottom"},
        {"id": "m2", "frame_idx": 60, "timestamp_s": 45.0, "category": "guard_top"},
        {"id": "m3", "frame_idx": 90, "timestamp_s": 130.0, "category": "scramble"},
    ]


def _fixture_distribution():
    return {
        "timeline": ["guard_bottom", "guard_top", "scramble"],
        "counts": {"guard_bottom": 1, "guard_top": 1, "scramble": 1},
        "percentages": {"guard_bottom": 33, "guard_top": 34, "scramble": 33},
    }


class TestBuildReportContext:
    def test_flattens_header_fields(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
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
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["scores"] == [
            {"id": "guard_retention", "label": "Guard Retention", "value": 7, "bar_pct": 70, "color_bucket": "high"},
            {"id": "positional_awareness", "label": "Positional Awareness", "value": 3, "bar_pct": 30, "color_bucket": "low"},
            {"id": "transition_quality", "label": "Transition Quality", "value": 8, "bar_pct": 80, "color_bucket": "high"},
        ]

    def test_distribution_bar_uses_human_labels(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        # Every segment maps category id → human label, carries width + a CSS color variable name.
        labels = {seg["label"]: seg["width_pct"] for seg in ctx["distribution_bar"]}
        assert labels == {"Guard bottom": 33, "Guard top": 34, "Scramble": 33}
        for seg in ctx["distribution_bar"]:
            assert seg["color_class"].startswith("cat-")

    def test_key_moments_resolve_to_mm_ss_and_category_labels(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["key_moments"] == [
            {"timestamp_human": "00:12", "category_label": "Guard bottom", "blurb": "First sweep attempt."},
            {"timestamp_human": "00:45", "category_label": "Guard top", "blurb": "Passed half guard."},
            {"timestamp_human": "02:10", "category_label": "Scramble", "blurb": "Back take attempt."},
        ]

    def test_improvements_and_strengths_passthrough(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
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

    def test_missing_key_moment_id_is_skipped(self):
        scores = _fixture_scores()
        scores["key_moments"].append({"moment_id": "does-not-exist", "note": "should be dropped"})
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=scores,
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        # Only the three valid moments come through.
        assert len(ctx["key_moments"]) == 3

    def test_raises_when_scores_missing(self):
        with pytest.raises(ValueError, match="scores"):
            build_report_context(
                roll=_fixture_roll(),
                scores=None,
                distribution=_fixture_distribution(),
                moments=_fixture_moments(),
                taxonomy=_fixture_taxonomy(),
                generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
            )


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
