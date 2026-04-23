"""Tests for server.eval.report — markdown report rendering."""
from __future__ import annotations

from server.eval.report import (
    render_section_report_md,
    render_summary_report_md,
)
from server.eval.runner import SectionEvalResult, SummaryEvalResult


def _section_result(variant: str, vocab: int = 7) -> SectionEvalResult:
    return SectionEvalResult(
        roll_id="r1", section_id="s1", note="smoke",
        variant=variant,
        narrative="A recovers guard.", coach_tip="Elbows tight.",
        judgement={
            "scores": {
                "vocabulary": vocab, "accuracy": 8,
                "specificity": 6, "coach_tip": 7,
            },
            "rationale": {
                "vocabulary": "Good.", "accuracy": "Right.",
                "specificity": "OK.", "coach_tip": "Actionable.",
            },
            "overall": 7,
            "verdict": "Solid.",
        },
        error=None,
    )


def test_section_report_includes_header_with_variant_names():
    md = render_section_report_md(
        results=[_section_result("m9b-baseline"), _section_result("m10-grounded")],
        run_name="smoke",
    )
    assert "# Section eval report" in md
    assert "m9b-baseline" in md
    assert "m10-grounded" in md


def test_section_report_shows_aggregate_scores_per_variant():
    md = render_section_report_md(
        results=[
            _section_result("m9b-baseline", vocab=5),
            _section_result("m9b-baseline", vocab=7),
            _section_result("m10-grounded", vocab=9),
        ],
        run_name="smoke",
    )
    # Aggregate = mean; m9b-baseline vocabulary = 6.0, m10-grounded = 9.0
    assert "6.0" in md
    assert "9.0" in md


def test_section_report_includes_per_section_detail():
    md = render_section_report_md(
        results=[_section_result("m9b-baseline")],
        run_name="smoke",
    )
    assert "A recovers guard." in md
    assert "Elbows tight." in md
    assert "Solid." in md


def test_section_report_surfaces_error_entries():
    failed = SectionEvalResult(
        roll_id="r1", section_id="s1", note=None, variant="m9b-baseline",
        narrative=None, coach_tip=None, judgement=None,
        error="generation failed: ClaudeProcessError: boom",
    )
    md = render_section_report_md(results=[failed], run_name="smoke")
    assert "generation failed" in md
    assert "boom" in md


def _summary_result(variant: str, overall: int = 7) -> SummaryEvalResult:
    return SummaryEvalResult(
        roll_id="r1", note=None, variant=variant,
        summary_payload={
            "summary": "Tight roll.",
            "scores": {
                "guard_retention": 7, "positional_awareness": 6,
                "transition_quality": 7,
            },
            "top_improvements": ["a", "b", "c"],
            "strengths": ["x", "y"],
            "key_moments": [],
        },
        judgement={
            "scores": {
                "faithfulness": 8, "rubric_calibration": 7,
                "improvements_grounding": 6, "strengths_grounding": 7,
                "key_moments_grounding": 5,
            },
            "rationale": {
                "faithfulness": "OK.", "rubric_calibration": "OK.",
                "improvements_grounding": "OK.",
                "strengths_grounding": "OK.",
                "key_moments_grounding": "OK.",
            },
            "overall": overall, "verdict": "Good summary.",
        },
        error=None,
    )


def test_summary_report_includes_header_and_variant():
    md = render_summary_report_md(
        results=[_summary_result("current")], run_name="smoke",
    )
    assert "# Summary eval report" in md
    assert "current" in md
    assert "Tight roll." in md
    assert "Good summary." in md
