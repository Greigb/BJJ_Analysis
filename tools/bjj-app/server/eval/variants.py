"""Prompt-variant registry for the M11 eval harness.

A variant is a pure function `(context) -> prompt_string` that wraps an
existing prompt builder with a fixed argument profile. New variants (e.g.
for techniques grounding) are added by defining a new function and
registering it in the matching dict below.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, TypedDict

from server.analysis.positions_vault import PositionNote
from server.analysis.prompt import build_section_prompt
from server.analysis.summarise import build_summary_prompt


class SectionEvalContext(TypedDict):
    start_s: float
    end_s: float
    frame_paths: list[Path]
    timestamps: list[float]
    player_a_name: str
    player_b_name: str
    player_a_description: str | None
    player_b_description: str | None
    positions: list[PositionNote]


class SummaryEvalContext(TypedDict):
    roll_row: dict
    sections: list[dict]
    annotations_by_section: dict[str, list[dict]]


SectionVariant = Callable[[SectionEvalContext], str]
SummaryVariant = Callable[[SummaryEvalContext], str]


def _m9b_baseline(ctx: SectionEvalContext) -> str:
    """M9b: section prompt with no vault grounding."""
    return build_section_prompt(
        start_s=ctx["start_s"], end_s=ctx["end_s"],
        frame_paths=ctx["frame_paths"], timestamps=ctx["timestamps"],
        player_a_name=ctx["player_a_name"], player_b_name=ctx["player_b_name"],
        player_a_description=ctx.get("player_a_description"),
        player_b_description=ctx.get("player_b_description"),
        positions=None,
    )


def _m10_grounded(ctx: SectionEvalContext) -> str:
    """M10: section prompt with canonical positions reference block."""
    return build_section_prompt(
        start_s=ctx["start_s"], end_s=ctx["end_s"],
        frame_paths=ctx["frame_paths"], timestamps=ctx["timestamps"],
        player_a_name=ctx["player_a_name"], player_b_name=ctx["player_b_name"],
        player_a_description=ctx.get("player_a_description"),
        player_b_description=ctx.get("player_b_description"),
        positions=ctx.get("positions") or None,
    )


SECTION_VARIANTS: dict[str, SectionVariant] = {
    "m9b-baseline": _m9b_baseline,
    "m10-grounded": _m10_grounded,
}


def _current_summary(ctx: SummaryEvalContext) -> str:
    """The summary prompt as of M9b (section-based, with scoring rubric)."""
    return build_summary_prompt(
        roll_row=ctx["roll_row"],
        sections=ctx["sections"],
        annotations_by_section=ctx["annotations_by_section"],
    )


SUMMARY_VARIANTS: dict[str, SummaryVariant] = {
    "current": _current_summary,
}
