"""M6b PDF report rendering — pure helpers + WeasyPrint wrapper.

No IO except inside `render_report_pdf`. Tests hit the helpers directly;
rendering gets a smoke test for PDF-magic-number output.
"""
from __future__ import annotations

import re


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def format_mm_ss(seconds: float | int) -> str:
    """Format a duration in seconds as `mm:ss` (zero-padded, truncated to int)."""
    total = int(seconds)
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"


def slugify_report_filename(title: str, date: str) -> str:
    """Return a safe filename like `tuesday-roll-2026-04-21.pdf`.

    Lowercases, strips non-alphanumerics, collapses repeats, and trims leading
    and trailing hyphens. Empty / whitespace-only titles fall back to
    `match-report-<date>.pdf`.
    """
    slug = _SLUG_STRIP_RE.sub("-", title.lower()).strip("-")
    if not slug:
        slug = "match-report"
    return f"{slug}-{date}.pdf"
