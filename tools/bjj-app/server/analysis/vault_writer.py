"""SOLE module that writes to Roll Log/*.md.

All vault markdown writes go through `publish`. Pure helpers (`render_your_notes`,
`slugify_filename`) are extracted for easy unit testing.

Security invariant: every write target must resolve under `vault_root/Roll Log/`.
Enforced inside `publish` by Path.resolve().relative_to().
"""
from __future__ import annotations

import re
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


_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def slugify_filename(title: str, date: str, vault_root: Path) -> Path:
    """Return a collision-safe path under `<vault_root>/Roll Log/`.

    Filename template: `YYYY-MM-DD - <sanitised title>.md`.
    Sanitisation: collapses runs of whitespace, strips filesystem-unsafe
    characters (/\\:*?"<>|), drops leading dots so ".." or "./" can't escape.

    On collision, appends ` (2)`, ` (3)` etc. until unique.
    """
    roll_log = vault_root / "Roll Log"
    roll_log.mkdir(parents=True, exist_ok=True)

    clean_title = _UNSAFE_CHARS.sub("", title).strip()
    clean_title = re.sub(r"\s+", " ", clean_title)
    # Prevent leading dot (hidden file, or ".." remnants).
    clean_title = clean_title.lstrip(". ")
    if not clean_title:
        clean_title = "Roll"

    base = f"{date} - {clean_title}"
    candidate = roll_log / f"{base}.md"
    if not candidate.exists():
        return candidate

    n = 2
    while True:
        candidate = roll_log / f"{base} ({n}).md"
        if not candidate.exists():
            return candidate
        n += 1


# ---------- publish orchestration ----------


import hashlib
import os
import re as _re  # re is already imported at top, alias to avoid shadowing any later additions
import time

from server.db import get_annotations_by_roll, get_roll, get_vault_state, set_vault_state


@dataclass(frozen=True)
class PublishResult:
    vault_path: str            # relative to vault_root, e.g. "Roll Log/2026-04-21 - T.md"
    your_notes_hash: str       # sha256 of the new Your Notes body
    vault_published_at: int    # unix seconds when this publish completed


class ConflictError(Exception):
    """Raised by publish() when `## Your Notes` hash in the file disagrees with stored hash."""

    def __init__(self, *, current_hash: str, stored_hash: str) -> None:
        super().__init__(
            f"Your Notes section hash mismatch: current={current_hash[:8]} "
            f"stored={stored_hash[:8]}"
        )
        self.current_hash = current_hash
        self.stored_hash = stored_hash


_YOUR_NOTES_HEADING = "## Your Notes"
_SECTION_BOUNDARY = _re.compile(r"^## ", _re.MULTILINE)


def publish(
    conn,
    *,
    roll_id: str,
    vault_root: Path,
    force: bool = False,
) -> PublishResult:
    """Publish a roll's annotations to its vault markdown file.

    First publish: creates a new file under Roll Log/ with frontmatter + title +
    Your Notes. Re-publish: surgically replaces the Your Notes section only,
    preserving everything else. Hash-based conflict detection fires on external
    edits to Your Notes (raises ConflictError unless force=True).
    """
    roll_row = get_roll(conn, roll_id)
    if roll_row is None:
        raise LookupError(f"Roll not found: {roll_id}")

    # Render the new Your Notes body from current annotations.
    annotations = get_annotations_by_roll(conn, roll_id)
    new_body = render_your_notes(annotations)
    new_hash = _hash_section(new_body)

    vault_state = get_vault_state(conn, roll_id) or {
        "vault_path": None, "vault_your_notes_hash": None, "vault_published_at": None,
    }

    # Decide target path: existing stored path if any, else slugify new one.
    if vault_state["vault_path"]:
        target = vault_root / vault_state["vault_path"]
    else:
        target = slugify_filename(
            title=roll_row["title"],
            date=roll_row["date"],
            vault_root=vault_root,
        )

    # Security invariant: target must resolve under Roll Log/.
    _assert_under_roll_log(target, vault_root)

    if target.exists():
        current_text = target.read_text(encoding="utf-8")
        current_section = _extract_your_notes_section(current_text)
        current_hash = _hash_section(current_section)
        stored_hash = vault_state["vault_your_notes_hash"]
        if stored_hash is not None and current_hash != stored_hash and not force:
            raise ConflictError(current_hash=current_hash, stored_hash=stored_hash)
        new_text = _splice_your_notes(current_text, new_body)
    else:
        # Either first publish OR user deleted the file — build from scratch.
        new_text = _build_skeleton(
            title=roll_row["title"],
            date=roll_row["date"],
            partner=roll_row["partner"],
            duration_s=roll_row["duration_s"],
            roll_id=roll_id,
            your_notes_body=new_body,
        )

    _atomic_write(target, new_text)

    now = int(time.time())
    relative_path = str(target.relative_to(vault_root))
    set_vault_state(
        conn,
        roll_id=roll_id,
        vault_path=relative_path,
        vault_your_notes_hash=new_hash,
        vault_published_at=now,
    )
    return PublishResult(
        vault_path=relative_path,
        your_notes_hash=new_hash,
        vault_published_at=now,
    )


def _assert_under_roll_log(target: Path, vault_root: Path) -> None:
    roll_log = (vault_root / "Roll Log").resolve()
    resolved = target.resolve()
    if not resolved.is_relative_to(roll_log):
        raise ValueError(f"target {target} escapes Roll Log directory {roll_log}")


def _build_skeleton(
    *,
    title: str,
    date: str,
    partner: str | None,
    duration_s: float | None,
    roll_id: str,
    your_notes_body: str,
) -> str:
    duration = _format_duration(duration_s)
    partner_line = f"partner: {partner}" if partner else "partner:"
    duration_line = f'duration: "{duration}"' if duration else "duration:"

    frontmatter = "\n".join([
        "---",
        f"date: {date}",
        partner_line,
        duration_line,
        "tags: [roll]",
        f"roll_id: {roll_id}",
        "---",
    ])

    body = your_notes_body if your_notes_body else ""
    return (
        f"{frontmatter}\n\n"
        f"# {title}\n\n"
        f"{_YOUR_NOTES_HEADING}\n\n"
        f"{body}\n"
    )


def _format_duration(duration_s: float | None) -> str:
    if duration_s is None:
        return ""
    total = int(round(duration_s))
    m = total // 60
    s = total % 60
    return f"{m}:{s:02d}"


def _extract_your_notes_section(text: str) -> str:
    """Return the body of `## Your Notes` section, or '' if absent.

    The body spans from the first blank line after the heading to the next
    `## ` heading (exclusive) or EOF. Leading/trailing whitespace is stripped
    so whitespace-only differences don't trigger false conflicts.
    """
    heading_idx = text.find(_YOUR_NOTES_HEADING)
    if heading_idx == -1:
        return ""
    # Start after the heading line.
    body_start = text.find("\n", heading_idx)
    if body_start == -1:
        return ""
    body_start += 1

    # Find next `^## ` heading (anywhere in the remaining text).
    rest = text[body_start:]
    m = _SECTION_BOUNDARY.search(rest)
    end = body_start + m.start() if m else len(text)

    return text[body_start:end].strip()


def _splice_your_notes(current_text: str, new_body: str) -> str:
    """Replace the Your Notes section body inside an existing file.

    If the section heading is absent, append a new section at the end.
    """
    heading_idx = current_text.find(_YOUR_NOTES_HEADING)
    if heading_idx == -1:
        # Append a new section.
        separator = "" if current_text.endswith("\n\n") else ("\n" if current_text.endswith("\n") else "\n\n")
        return f"{current_text}{separator}{_YOUR_NOTES_HEADING}\n\n{new_body}\n"

    # Find body span [body_start, end).
    body_start = current_text.find("\n", heading_idx)
    if body_start == -1:
        body_start = len(current_text)
    else:
        body_start += 1
    rest = current_text[body_start:]
    m = _SECTION_BOUNDARY.search(rest)
    end = body_start + m.start() if m else len(current_text)

    # Standardise the body block: the heading line stays; then one blank line;
    # then the new body; then a blank line before the next `## ` (if any).
    before = current_text[: heading_idx + len(_YOUR_NOTES_HEADING)]
    after = current_text[end:]

    # Ensure `after` starts with a newline before `## ` so rendering stays clean.
    if after and not after.startswith("\n"):
        after = "\n" + after
    # If there's no following section, make sure the file ends with a trailing newline.
    if not after:
        after = "\n"

    return f"{before}\n\n{new_body}\n{after}"


def _hash_section(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
