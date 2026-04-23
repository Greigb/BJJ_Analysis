"""Command-line entry point for the eval harness.

Usage:
    python -m server.eval section  \\
        --fixture server/eval/fixtures/sections-smoke.yaml  \\
        --variants m9b-baseline m10-grounded  \\
        --output server/eval/reports/2026-04-22-section-smoke.md

    python -m server.eval summary  \\
        --fixture server/eval/fixtures/summary-smoke.yaml  \\
        --variants current  \\
        --output server/eval/reports/2026-04-22-summary-smoke.md

This runs REAL Claude CLI calls and costs money. Start with 1-2 entries in
the fixture to smoke the flow before doing large runs.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import load_settings
from server.eval.fixtures import load_section_fixture, load_summary_fixture
from server.eval.report import (
    render_section_report_md, render_summary_report_md,
)
from server.eval.runner import (
    evaluate_section_variants, evaluate_summary_variants,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="server.eval",
        description="Run M11 LLM-as-judge eval over section or summary prompts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sec = sub.add_parser("section", help="Evaluate section-prompt variants.")
    sec.add_argument("--fixture", type=Path, required=True)
    sec.add_argument("--variants", nargs="+", required=True,
                     help="Variant names registered in SECTION_VARIANTS.")
    sec.add_argument("--output", type=Path, required=True)
    sec.add_argument("--run-name", default="adhoc",
                     help="Label for the report header (appears in the title).")

    summ = sub.add_parser("summary", help="Evaluate summary-prompt variants.")
    summ.add_argument("--fixture", type=Path, required=True)
    summ.add_argument("--variants", nargs="+", required=True,
                      help="Variant names registered in SUMMARY_VARIANTS.")
    summ.add_argument("--output", type=Path, required=True)
    summ.add_argument("--run-name", default="adhoc")

    return parser


async def _run_section(args: argparse.Namespace) -> int:
    settings = load_settings()
    limiter = SlidingWindowLimiter(
        max_calls=settings.claude_max_calls,
        window_seconds=settings.claude_window_seconds,
    )
    fixture = load_section_fixture(args.fixture)
    print(f"Running {len(fixture)} section fixture entries × "
          f"{len(args.variants)} variants = "
          f"{len(fixture) * len(args.variants) * 2} Claude calls…",
          file=sys.stderr)
    results = await evaluate_section_variants(
        fixture_entries=fixture,
        variant_names=args.variants,
        settings=settings,
        limiter=limiter,
    )
    md = render_section_report_md(results=results, run_name=args.run_name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md)
    errors = sum(1 for r in results if r.error)
    print(f"Wrote {args.output}  ({len(results)} results, {errors} errors).",
          file=sys.stderr)
    return 0


async def _run_summary(args: argparse.Namespace) -> int:
    settings = load_settings()
    limiter = SlidingWindowLimiter(
        max_calls=settings.claude_max_calls,
        window_seconds=settings.claude_window_seconds,
    )
    fixture = load_summary_fixture(args.fixture)
    print(f"Running {len(fixture)} summary fixture entries × "
          f"{len(args.variants)} variants = "
          f"{len(fixture) * len(args.variants) * 2} Claude calls…",
          file=sys.stderr)
    results = await evaluate_summary_variants(
        fixture_entries=fixture,
        variant_names=args.variants,
        settings=settings,
        limiter=limiter,
    )
    md = render_summary_report_md(results=results, run_name=args.run_name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md)
    errors = sum(1 for r in results if r.error)
    print(f"Wrote {args.output}  ({len(results)} results, {errors} errors).",
          file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "section":
        return asyncio.run(_run_section(args))
    if args.command == "summary":
        return asyncio.run(_run_summary(args))
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
