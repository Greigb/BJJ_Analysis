"""Pure helpers for the summary step — no IO, no subprocess.

- build_summary_prompt: assembles the Claude coach-summary prompt.
- parse_summary_response: validates Claude's JSON output.
- compute_distribution: counts positions + builds the timeline bar data.
"""
from __future__ import annotations

import json


class SummaryResponseError(Exception):
    """Raised when Claude's summary output fails schema or reference validation."""


CATEGORY_EMOJI: dict[str, str] = {
    "standing":          "⬜",
    "guard_bottom":      "🟦",
    "guard_top":         "🟨",
    "dominant_top":      "🟩",
    "inferior_bottom":   "🟥",
    "leg_entanglement":  "🟫",
    "scramble":          "🟪",
}


def compute_distribution(
    analyses: list[dict],
    categories: list[dict],
) -> dict:
    """Compute timeline + category counts + percentages from analyses.

    Only considers rows where `player == "a"` (the person being coached).
    """
    player_a_only = [a for a in analyses if a.get("player") == "a"]
    if not player_a_only:
        return {"timeline": [], "counts": {}, "percentages": {}}

    timeline: list[str] = [a["category"] for a in player_a_only]

    counts: dict[str, int] = {}
    for cat in timeline:
        counts[cat] = counts.get(cat, 0) + 1

    total = sum(counts.values())
    percentages: dict[str, int] = {
        cat: round((n / total) * 100) for cat, n in counts.items()
    }

    return {"timeline": timeline, "counts": counts, "percentages": percentages}


def build_summary_prompt(
    roll_row: dict,
    moment_rows: list[dict],
    analyses_by_moment: dict[str, list[dict]],
    annotations_by_moment: dict[str, list[dict]],
) -> str:
    """Construct the summary prompt for Claude. (stub — full impl in next step)"""
    raise NotImplementedError


def parse_summary_response(raw: str, valid_moment_ids: set[str]) -> dict:
    """Parse + validate Claude's summary JSON output. (stub — full impl in next step)"""
    raise NotImplementedError
