"""Runner — orchestrates (fixture entry × variant) evaluation.

Section flow (per fixture entry, per variant):
    build section_ctx from DB + disk
    variant(ctx) → prompt
    run_claude(prompt) → raw JSON
    parse_section_response(raw) → narrative + coach_tip
    build_section_judge_prompt(…, narrative, coach_tip) → judge prompt
    run_claude(judge prompt) → raw JSON
    parse_section_judgement(raw) → judgement dict
    → SectionEvalResult

Summary flow lands in Task 5.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from server.analysis.claude_cli import (
    ClaudeProcessError,
    ClaudeResponseError,
    RateLimitedError,
    run_claude,
)
from server.analysis.positions_vault import (
    PositionNote,
    load_positions_index,
    ordered_positions_from_taxonomy,
)
from server.analysis.prompt import SectionResponseError, parse_section_response
from server.analysis.rate_limit import SlidingWindowLimiter
from server.analysis.taxonomy import load_taxonomy
from server.config import Settings
from server.db import connect, get_moments, get_roll, get_sections_by_roll
from server.eval.fixtures import SectionFixtureEntry
from server.eval.judge import (
    JudgementError,
    build_section_judge_prompt,
    parse_section_judgement,
)
from server.eval.variants import SECTION_VARIANTS, SectionEvalContext


@dataclass
class SectionEvalResult:
    roll_id: str
    section_id: str
    note: str | None
    variant: str
    narrative: str | None
    coach_tip: str | None
    judgement: dict | None
    error: str | None


async def evaluate_section_variants(
    *,
    fixture_entries: list[SectionFixtureEntry],
    variant_names: list[str],
    settings: Settings,
    limiter: SlidingWindowLimiter,
) -> list[SectionEvalResult]:
    """For each (entry, variant) pair, generate + judge. Never raises on per-
    entry or per-variant failure — surface the error in the result. Does
    raise ValueError up front if a variant name is unknown."""
    for name in variant_names:
        if name not in SECTION_VARIANTS:
            raise ValueError(
                f"unknown section variant: {name!r}. "
                f"Known: {sorted(SECTION_VARIANTS)}"
            )

    positions_index = load_positions_index(settings.vault_root)
    taxonomy = (
        load_taxonomy(settings.taxonomy_path)
        if settings.taxonomy_path.exists()
        else {"positions": []}
    )
    positions = ordered_positions_from_taxonomy(
        positions_index=positions_index, taxonomy=taxonomy
    )

    results: list[SectionEvalResult] = []
    conn = connect(settings.db_path)
    try:
        for entry in fixture_entries:
            ctx = _build_section_context(
                conn=conn,
                roll_id=entry["roll_id"],
                section_id=entry["section_id"],
                settings=settings,
                positions=positions,
            )
            if ctx is None:
                for name in variant_names:
                    results.append(SectionEvalResult(
                        roll_id=entry["roll_id"],
                        section_id=entry["section_id"],
                        note=entry["note"],
                        variant=name,
                        narrative=None, coach_tip=None, judgement=None,
                        error="section or roll not found in local DB",
                    ))
                continue
            for name in variant_names:
                results.append(await _run_one_section_variant(
                    ctx=ctx, entry=entry, variant_name=name,
                    settings=settings, limiter=limiter,
                ))
    finally:
        conn.close()
    return results


def _build_section_context(
    *,
    conn,
    roll_id: str,
    section_id: str,
    settings: Settings,
    positions: list[PositionNote],
) -> SectionEvalContext | None:
    roll = get_roll(conn, roll_id)
    if roll is None:
        return None
    sections = get_sections_by_roll(conn, roll_id)
    section = next((s for s in sections if s["id"] == section_id), None)
    if section is None:
        return None
    all_moments = get_moments(conn, roll_id)
    section_moments = sorted(
        [m for m in all_moments if m["section_id"] == section_id],
        key=lambda m: m["timestamp_s"],
    )
    if not section_moments:
        return None
    frames_dir = settings.project_root / "assets" / roll_id / "frames"
    frame_paths = [
        frames_dir / f"frame_{m['frame_idx']:06d}.jpg" for m in section_moments
    ]
    timestamps = [float(m["timestamp_s"]) for m in section_moments]
    try:
        a_desc = roll["player_a_description"]
        b_desc = roll["player_b_description"]
    except (IndexError, KeyError):
        a_desc = None
        b_desc = None
    return {
        "start_s": float(section["start_s"]),
        "end_s": float(section["end_s"]),
        "frame_paths": frame_paths,
        "timestamps": timestamps,
        "player_a_name": roll["player_a_name"] or "Player A",
        "player_b_name": roll["player_b_name"] or "Player B",
        "player_a_description": a_desc,
        "player_b_description": b_desc,
        "positions": positions,
    }


async def _run_one_section_variant(
    *,
    ctx: SectionEvalContext,
    entry: SectionFixtureEntry,
    variant_name: str,
    settings: Settings,
    limiter: SlidingWindowLimiter,
) -> SectionEvalResult:
    variant = SECTION_VARIANTS[variant_name]
    prompt = variant(ctx)

    # Generation
    try:
        raw = await run_claude(prompt, settings=settings, limiter=limiter)
        parsed = parse_section_response(raw)
    except (SectionResponseError, RateLimitedError, ClaudeProcessError,
            ClaudeResponseError) as exc:
        return SectionEvalResult(
            roll_id=entry["roll_id"], section_id=entry["section_id"],
            note=entry["note"], variant=variant_name,
            narrative=None, coach_tip=None, judgement=None,
            error=f"generation failed: {type(exc).__name__}: {exc}",
        )

    # Judgement
    judge_prompt = build_section_judge_prompt(
        frame_paths=ctx["frame_paths"], timestamps=ctx["timestamps"],
        start_s=ctx["start_s"], end_s=ctx["end_s"],
        player_a_name=ctx["player_a_name"], player_b_name=ctx["player_b_name"],
        generated_narrative=parsed["narrative"],
        generated_coach_tip=parsed["coach_tip"],
    )
    try:
        raw_j = await run_claude(judge_prompt, settings=settings, limiter=limiter)
        judgement = parse_section_judgement(raw_j)
    except (JudgementError, RateLimitedError, ClaudeProcessError,
            ClaudeResponseError) as exc:
        return SectionEvalResult(
            roll_id=entry["roll_id"], section_id=entry["section_id"],
            note=entry["note"], variant=variant_name,
            narrative=parsed["narrative"], coach_tip=parsed["coach_tip"],
            judgement=None,
            error=f"judgement failed: {type(exc).__name__}: {exc}",
        )

    return SectionEvalResult(
        roll_id=entry["roll_id"], section_id=entry["section_id"],
        note=entry["note"], variant=variant_name,
        narrative=parsed["narrative"], coach_tip=parsed["coach_tip"],
        judgement=judgement, error=None,
    )


# ---------- summary runner ----------


from server.analysis.summarise import (  # noqa: E402
    SummaryResponseError, parse_summary_response,
)
from server.db import get_annotations_by_section  # noqa: E402
from server.eval.fixtures import SummaryFixtureEntry  # noqa: E402
from server.eval.judge import (  # noqa: E402
    build_summary_judge_prompt, parse_summary_judgement,
)
from server.eval.variants import SUMMARY_VARIANTS, SummaryEvalContext  # noqa: E402


@dataclass
class SummaryEvalResult:
    roll_id: str
    note: str | None
    variant: str
    summary_payload: dict | None
    judgement: dict | None
    error: str | None


async def evaluate_summary_variants(
    *,
    fixture_entries: list[SummaryFixtureEntry],
    variant_names: list[str],
    settings: Settings,
    limiter: SlidingWindowLimiter,
) -> list[SummaryEvalResult]:
    """For each (entry, variant), regenerate the summary from the roll's
    currently-persisted sections + annotations, then judge it."""
    for name in variant_names:
        if name not in SUMMARY_VARIANTS:
            raise ValueError(
                f"unknown summary variant: {name!r}. "
                f"Known: {sorted(SUMMARY_VARIANTS)}"
            )

    results: list[SummaryEvalResult] = []
    conn = connect(settings.db_path)
    try:
        for entry in fixture_entries:
            ctx = _build_summary_context(conn=conn, roll_id=entry["roll_id"])
            if ctx is None:
                for name in variant_names:
                    results.append(SummaryEvalResult(
                        roll_id=entry["roll_id"], note=entry["note"],
                        variant=name, summary_payload=None, judgement=None,
                        error="roll not found in local DB",
                    ))
                continue
            if not any(s.get("narrative") for s in ctx["sections"]):
                for name in variant_names:
                    results.append(SummaryEvalResult(
                        roll_id=entry["roll_id"], note=entry["note"],
                        variant=name, summary_payload=None, judgement=None,
                        error="roll has no analysed sections",
                    ))
                continue
            for name in variant_names:
                results.append(await _run_one_summary_variant(
                    ctx=ctx, entry=entry, variant_name=name,
                    settings=settings, limiter=limiter,
                ))
    finally:
        conn.close()
    return results


def _build_summary_context(*, conn, roll_id: str) -> SummaryEvalContext | None:
    roll = get_roll(conn, roll_id)
    if roll is None:
        return None
    sections = [dict(s) for s in get_sections_by_roll(conn, roll_id)]
    annotations_by_section = {
        s["id"]: [dict(a) for a in get_annotations_by_section(conn, s["id"])]
        for s in sections
    }
    return {
        "roll_row": dict(roll),
        "sections": sections,
        "annotations_by_section": annotations_by_section,
    }


async def _run_one_summary_variant(
    *,
    ctx: SummaryEvalContext,
    entry: SummaryFixtureEntry,
    variant_name: str,
    settings: Settings,
    limiter: SlidingWindowLimiter,
) -> SummaryEvalResult:
    variant = SUMMARY_VARIANTS[variant_name]
    prompt = variant(ctx)

    valid_section_ids = {s["id"] for s in ctx["sections"]}

    try:
        raw = await run_claude(prompt, settings=settings, limiter=limiter)
        payload = parse_summary_response(raw, valid_section_ids)
    except (SummaryResponseError, RateLimitedError, ClaudeProcessError,
            ClaudeResponseError) as exc:
        return SummaryEvalResult(
            roll_id=entry["roll_id"], note=entry["note"], variant=variant_name,
            summary_payload=None, judgement=None,
            error=f"generation failed: {type(exc).__name__}: {exc}",
        )

    judge_prompt = build_summary_judge_prompt(
        roll_row=ctx["roll_row"],
        sections=ctx["sections"],
        generated_summary=payload,
    )
    try:
        raw_j = await run_claude(judge_prompt, settings=settings, limiter=limiter)
        judgement = parse_summary_judgement(raw_j)
    except (JudgementError, RateLimitedError, ClaudeProcessError,
            ClaudeResponseError) as exc:
        return SummaryEvalResult(
            roll_id=entry["roll_id"], note=entry["note"], variant=variant_name,
            summary_payload=payload, judgement=None,
            error=f"judgement failed: {type(exc).__name__}: {exc}",
        )

    return SummaryEvalResult(
        roll_id=entry["roll_id"], note=entry["note"], variant=variant_name,
        summary_payload=payload, judgement=judgement, error=None,
    )
