"""SOLE module that writes to Roll Log/*.md.

All vault markdown writes go through `publish`. Pure helpers (`render_your_notes`,
`slugify_filename`) are extracted for easy unit testing.

Security invariant: every write target must resolve under `vault_root/Roll Log/`.
Enforced inside `publish` by Path.resolve().relative_to().
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


def render_your_notes(rows: Iterable) -> str:
    """Render annotation rows as the body of the `## Your Notes` section.

    Input row shape (dict or sqlite3.Row): keys `moment_id`, `timestamp_s`,
    `body`, `created_at`. Ordering is performed here — caller need not sort.
    Returns a string without a trailing newline; the caller adds surrounding
    section framing.
    """
    rows_list: list = list(rows)
    if not rows_list:
        return ""

    # Sort by (timestamp_s, created_at) for moment-groups then bullet order.
    rows_list.sort(key=lambda r: (_row_get(r, "timestamp_s"), _row_get(r, "created_at")))

    # Group consecutive rows with the same moment_id into their H3 section.
    sections: list[str] = []
    current_moment_id: str | None = None
    current_bullets: list[str] = []
    current_header: str = ""

    def flush() -> None:
        if current_moment_id is None:
            return
        sections.append(current_header + "\n" + "\n".join(current_bullets))

    for row in rows_list:
        moment_id = _row_get(row, "moment_id")
        if moment_id != current_moment_id:
            flush()
            current_bullets = []
            current_moment_id = moment_id
            current_header = f"### {_format_mm_ss(_row_get(row, 'timestamp_s'))}"
        ts = _format_created_stamp(_row_get(row, "created_at"))
        body = _row_get(row, "body")
        current_bullets.append(f"- _({ts})_ {body}")
    flush()

    return "\n\n".join(sections)


def _row_get(row, key: str):
    if isinstance(row, dict):
        return row[key]
    return row[key]  # sqlite3.Row supports [key] too


def _format_mm_ss(seconds: float) -> str:
    total = int(round(seconds))
    m = total // 60
    s = total % 60
    return f"{m}:{s:02d}"


def _format_created_stamp(unix_seconds: int) -> str:
    # UTC — deterministic across machines. Obsidian renders this verbatim.
    dt = datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")
