"""M9 pure helpers for user-picked section timestamp generation.

Deterministic, no IO. Tests hit these directly; the pipeline consumes
them in `run_section_analysis`.
"""
from __future__ import annotations


def build_sample_timestamps(
    start_s: float,
    end_s: float,
    interval_s: float,
) -> list[float]:
    """Return timestamps in [start_s, end_s) stepped by interval_s.

    Inclusive at start_s, strictly less than end_s. Values are rounded to
    3 decimal places to avoid floating-point drift across section boundaries.

    Raises ValueError for invalid input: negative start, end < start, or
    interval <= 0.
    """
    if start_s < 0:
        raise ValueError(f"start_s must be >= 0, got {start_s}")
    if end_s < start_s:
        raise ValueError(f"end_s ({end_s}) must be >= start_s ({start_s})")
    if interval_s <= 0:
        raise ValueError(f"interval_s must be > 0, got {interval_s}")

    out: list[float] = []
    # Use integer step counter to avoid accumulating float error.
    n = 0
    while True:
        t = round(start_s + n * interval_s, 3)
        if t >= end_s:
            break
        out.append(t)
        n += 1
    return out
