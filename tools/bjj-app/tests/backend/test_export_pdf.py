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
