"""Render eval-runner results into a human-readable markdown report."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from server.eval.runner import SectionEvalResult, SummaryEvalResult


_SECTION_AXES = ("vocabulary", "accuracy", "specificity", "coach_tip")
_SUMMARY_AXES = (
    "faithfulness", "rubric_calibration", "improvements_grounding",
    "strengths_grounding", "key_moments_grounding",
)


def render_section_report_md(
    *,
    results: list[SectionEvalResult],
    run_name: str,
) -> str:
    """Build a markdown report summarising section-eval results.

    Sections: title + metadata, aggregate-score table per variant, per-entry
    detail with both variants' outputs + judge rationale.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    variants = sorted({r.variant for r in results})

    lines: list[str] = [
        f"# Section eval report — {run_name}",
        "",
        f"_Generated {stamp}_",
        "",
        f"**Variants compared:** {', '.join(variants)}",
        f"**Total results:** {len(results)}  "
        f"(errors: {sum(1 for r in results if r.error)})",
        "",
        "## Aggregate scores (mean per variant, successful results only)",
        "",
        _aggregate_table(results, _SECTION_AXES),
        "",
        "## Per-entry detail",
    ]

    by_entry: dict[tuple[str, str], list[SectionEvalResult]] = defaultdict(list)
    for r in results:
        by_entry[(r.roll_id, r.section_id)].append(r)

    for (roll_id, section_id), entry_results in by_entry.items():
        note = next((r.note for r in entry_results if r.note), None)
        lines.append("")
        lines.append(f"### roll={roll_id}  section={section_id}"
                     + (f"  — _{note}_" if note else ""))
        for r in sorted(entry_results, key=lambda x: x.variant):
            lines.append("")
            lines.append(f"**Variant: `{r.variant}`**")
            if r.error:
                lines.append("")
                lines.append(f"> ❌ {r.error}")
                continue
            lines.append("")
            lines.append(f"- Narrative: {r.narrative}")
            lines.append(f"- Coach tip: {r.coach_tip}")
            if r.judgement is not None:
                s = r.judgement["scores"]
                ratio = r.judgement["rationale"]
                lines.append(f"- Judge overall: **{r.judgement['overall']}/10** "
                             f"— _{r.judgement['verdict']}_")
                for axis in _SECTION_AXES:
                    lines.append(f"  - `{axis}`: {s[axis]}/10 — {ratio[axis]}")
    return "\n".join(lines) + "\n"


def render_summary_report_md(
    *,
    results: list[SummaryEvalResult],
    run_name: str,
) -> str:
    """Build a markdown report summarising summary-eval results."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    variants = sorted({r.variant for r in results})

    lines: list[str] = [
        f"# Summary eval report — {run_name}",
        "",
        f"_Generated {stamp}_",
        "",
        f"**Variants compared:** {', '.join(variants)}",
        f"**Total results:** {len(results)}  "
        f"(errors: {sum(1 for r in results if r.error)})",
        "",
        "## Aggregate scores (mean per variant, successful results only)",
        "",
        _aggregate_table(results, _SUMMARY_AXES),
        "",
        "## Per-roll detail",
    ]

    by_entry: dict[str, list[SummaryEvalResult]] = defaultdict(list)
    for r in results:
        by_entry[r.roll_id].append(r)

    for roll_id, entry_results in by_entry.items():
        note = next((r.note for r in entry_results if r.note), None)
        lines.append("")
        lines.append(f"### roll={roll_id}"
                     + (f"  — _{note}_" if note else ""))
        for r in sorted(entry_results, key=lambda x: x.variant):
            lines.append("")
            lines.append(f"**Variant: `{r.variant}`**")
            if r.error:
                lines.append("")
                lines.append(f"> ❌ {r.error}")
                continue
            payload = r.summary_payload or {}
            lines.append("")
            lines.append(f"- Summary: {payload.get('summary', '')}")
            scores = payload.get("scores", {})
            if scores:
                lines.append(
                    f"- Scores: retention={scores.get('guard_retention')}, "
                    f"awareness={scores.get('positional_awareness')}, "
                    f"transition={scores.get('transition_quality')}"
                )
            if r.judgement is not None:
                s = r.judgement["scores"]
                ratio = r.judgement["rationale"]
                lines.append(f"- Judge overall: **{r.judgement['overall']}/10** "
                             f"— _{r.judgement['verdict']}_")
                for axis in _SUMMARY_AXES:
                    lines.append(f"  - `{axis}`: {s[axis]}/10 — {ratio[axis]}")
    return "\n".join(lines) + "\n"


def _aggregate_table(results, axes: tuple[str, ...]) -> str:
    # Group by variant, ignore errored rows.
    by_variant: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        if r.error or r.judgement is None:
            continue
        by_variant[r.variant].append(r.judgement["scores"])

    header = "| Variant | " + " | ".join(axes) + " | overall |"
    sep = "|---" * (len(axes) + 2) + "|"
    rows = [header, sep]
    for variant in sorted(by_variant):
        group = by_variant[variant]
        n = len(group)
        if n == 0:
            rows.append(f"| `{variant}` " + " | —" * (len(axes) + 1) + " |")
            continue
        cells = [f"`{variant}`"]
        for axis in axes:
            vals = [g[axis] for g in group]
            cells.append(f"{sum(vals) / n:.1f}")
        # Compute overall from the judgement's 'overall' field separately.
        overalls = [
            r.judgement["overall"]
            for r in results
            if r.variant == variant and r.error is None and r.judgement is not None
        ]
        cells.append(f"{sum(overalls) / len(overalls):.1f}" if overalls else "—")
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)
