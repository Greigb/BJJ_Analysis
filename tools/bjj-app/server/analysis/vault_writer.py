"""SOLE module that writes to Roll Log/*.md.

All vault markdown writes go through `publish`. Pure helpers (`render_your_notes`,
`slugify_filename`) are extracted for easy unit testing.

Security invariant: every write target must resolve under `vault_root/Roll Log/`.
Enforced inside `publish` by Path.resolve().relative_to().
"""
from __future__ import annotations

import hashlib
import os
import re
import re as _re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from server.db import (
    get_annotations_by_roll,
    get_roll,
    get_sections_by_roll,
    get_vault_state,
    set_vault_state,
    set_vault_summary_hashes,
)


def render_your_notes(rows: Iterable) -> str:
    """Render annotation rows as the body of `## Your Notes`, grouped by section range.

    Input row shape (dict or sqlite3.Row): keys `section_id`, `start_s`, `end_s`,
    `body`, `created_at`. Ordering is performed here — caller need not sort.
    Returns a string without a trailing newline; the caller adds surrounding
    section framing.
    """
    rows_list: list = list(rows)
    if not rows_list:
        return ""

    rows_list.sort(key=lambda r: (_row_get(r, "start_s"), _row_get(r, "created_at")))

    sections: list[str] = []
    current_section_id: str | None = None
    current_bullets: list[str] = []
    current_header: str = ""

    def flush() -> None:
        if current_section_id is None:
            return
        sections.append(current_header + "\n" + "\n".join(current_bullets))

    for row in rows_list:
        sid = _row_get(row, "section_id")
        if sid != current_section_id:
            flush()
            current_bullets = []
            current_section_id = sid
            start = _format_mm_ss(_row_get(row, "start_s"))
            end = _format_mm_ss(_row_get(row, "end_s"))
            current_header = f"### {start} – {end}"
        ts = _format_created_stamp(_row_get(row, "created_at"))
        body = _row_get(row, "body")
        current_bullets.append(f"- _({ts})_ {body}")
    flush()

    return "\n\n".join(sections)


def _row_get(row, key: str):
    if isinstance(row, dict):
        return row[key]
    return row[key]


def _format_mm_ss(seconds: float) -> str:
    total = int(round(seconds))
    m = total // 60
    s = total % 60
    return f"{m}:{s:02d}"


def _format_created_stamp(unix_seconds: int) -> str:
    dt = datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")


_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def slugify_filename(title: str, date: str, vault_root: Path) -> Path:
    """Return a collision-safe path under `<vault_root>/Roll Log/`."""
    roll_log = vault_root / "Roll Log"
    roll_log.mkdir(parents=True, exist_ok=True)

    clean_title = _UNSAFE_CHARS.sub("", title).strip()
    clean_title = re.sub(r"\s+", " ", clean_title)
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


@dataclass(frozen=True)
class PublishResult:
    vault_path: str
    your_notes_hash: str
    vault_published_at: int


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
_YOUR_NOTES_HEADING_RE = _re.compile(r"^## Your Notes\s*$", _re.MULTILINE)
_SECTION_BOUNDARY = _re.compile(r"^## ", _re.MULTILINE)

_SUMMARY_SECTION_ORDER: list[tuple[str, str]] = [
    ("summary", "## Summary"),
    ("scores", "## Scores"),
    ("key_moments", "## Key Moments"),
    ("top_improvements", "## Top Improvements"),
    ("strengths", "## Strengths Observed"),
]


def _heading_regex(heading: str) -> _re.Pattern:
    escaped = _re.escape(heading)
    return _re.compile(rf"^{escaped}\s*$", _re.MULTILINE)


def _extract_section_by_heading(text: str, heading: str) -> str:
    m = _heading_regex(heading).search(text)
    if m is None:
        return ""
    body_start = text.find("\n", m.end())
    if body_start == -1:
        return ""
    body_start += 1
    rest = text[body_start:]
    next_m = _SECTION_BOUNDARY.search(rest)
    end = body_start + next_m.start() if next_m else len(text)
    return text[body_start:end].strip()


def _replace_section_body_if_present(current_text: str, heading: str, new_body: str) -> str | None:
    m = _heading_regex(heading).search(current_text)
    if m is None:
        return None

    body_start = current_text.find("\n", m.end())
    if body_start == -1:
        body_start = len(current_text)
    else:
        body_start += 1
    rest = current_text[body_start:]
    next_m = _SECTION_BOUNDARY.search(rest)
    end = body_start + next_m.start() if next_m else len(current_text)
    before = current_text[: m.end()]
    after = current_text[end:]
    if after and not after.startswith("\n"):
        after = "\n" + after
    if not after:
        after = "\n"
    return f"{before}\n\n{new_body}\n{after}"


def _insert_section_at_ordered_position(
    current_text: str,
    heading: str,
    new_body: str,
    ordered_headings_after: list[str],
) -> str:
    insert_at: int | None = None
    for following in ordered_headings_after:
        m = _heading_regex(following).search(current_text)
        if m is not None:
            insert_at = m.start()
            break

    block = f"{heading}\n\n{new_body}\n\n"
    if insert_at is None:
        if current_text.endswith("\n\n"):
            return current_text + block
        if current_text.endswith("\n"):
            return current_text + "\n" + block
        return current_text + "\n\n" + block

    return current_text[:insert_at] + block + current_text[insert_at:]


def publish(
    conn,
    *,
    roll_id: str,
    vault_root: Path,
    force: bool = False,
    taxonomy: dict | None = None,  # kept for API compat; ignored post-M9b
) -> PublishResult:
    """Publish a roll's annotations + (if finalised) summary sections."""
    roll_row = get_roll(conn, roll_id)
    if roll_row is None:
        raise LookupError(f"Roll not found: {roll_id}")

    annotations = get_annotations_by_roll(conn, roll_id)
    your_notes_body = render_your_notes(annotations)
    your_notes_hash = _hash_section(your_notes_body)

    is_finalised = roll_row["scores_json"] is not None and roll_row["finalised_at"] is not None
    summary_section_bodies: dict[str, str] = {}
    summary_hashes: dict[str, str] = {}

    if is_finalised:
        import json as _json
        scores_payload = _json.loads(roll_row["scores_json"])
        section_rows = [dict(s) for s in get_sections_by_roll(conn, roll_id)]
        summary_section_bodies = render_summary_sections(
            scores_payload=scores_payload,
            sections=section_rows,
        )
        summary_hashes = {k: _hash_section(v) for k, v in summary_section_bodies.items()}

    vault_state = get_vault_state(conn, roll_id) or {
        "vault_path": None, "vault_your_notes_hash": None, "vault_published_at": None,
    }
    if vault_state["vault_path"]:
        target = vault_root / vault_state["vault_path"]
    else:
        target = slugify_filename(
            title=roll_row["title"], date=roll_row["date"], vault_root=vault_root,
        )
    _assert_under_roll_log(target, vault_root)

    stored_summary_hashes: dict[str, str] = {}
    if roll_row["vault_summary_hashes"]:
        import json as _json
        stored_summary_hashes = _json.loads(roll_row["vault_summary_hashes"]) or {}

    if target.exists():
        current_text = target.read_text(encoding="utf-8")

        current_your_notes = _extract_your_notes_section(current_text)
        current_your_notes_hash = _hash_section(current_your_notes)
        if (
            vault_state["vault_your_notes_hash"] is not None
            and current_your_notes_hash != vault_state["vault_your_notes_hash"]
            and not force
        ):
            raise ConflictError(
                current_hash=current_your_notes_hash,
                stored_hash=vault_state["vault_your_notes_hash"],
            )

        if is_finalised and stored_summary_hashes:
            for section_id, heading in _SUMMARY_SECTION_ORDER:
                current_body = _extract_section_by_heading(current_text, heading)
                current_hash = _hash_section(current_body)
                stored_hash = stored_summary_hashes.get(section_id)
                if (
                    stored_hash is not None
                    and current_hash != stored_hash
                    and not force
                ):
                    raise ConflictError(current_hash=current_hash, stored_hash=stored_hash)

        new_text = current_text
        if is_finalised:
            for idx, (section_id, heading) in enumerate(_SUMMARY_SECTION_ORDER):
                replaced = _replace_section_body_if_present(
                    new_text, heading, summary_section_bodies[section_id]
                )
                if replaced is not None:
                    new_text = replaced
                else:
                    after_headings = [h for _, h in _SUMMARY_SECTION_ORDER[idx + 1:]]
                    after_headings.append(_YOUR_NOTES_HEADING)
                    new_text = _insert_section_at_ordered_position(
                        new_text, heading, summary_section_bodies[section_id], after_headings
                    )
        new_text = _splice_your_notes(new_text, your_notes_body)
    else:
        new_text = _build_skeleton(
            title=roll_row["title"],
            date=roll_row["date"],
            partner=roll_row["partner"],
            duration_s=roll_row["duration_s"],
            roll_id=roll_id,
            your_notes_body=your_notes_body,
            summary_sections=summary_section_bodies if is_finalised else None,
        )

    _atomic_write(target, new_text)

    now = int(time.time())
    relative_path = str(target.relative_to(vault_root))
    set_vault_state(
        conn,
        roll_id=roll_id,
        vault_path=relative_path,
        vault_your_notes_hash=your_notes_hash,
        vault_published_at=now,
    )
    if is_finalised:
        _owned_section_ids = {sid for sid, _ in _SUMMARY_SECTION_ORDER}
        merged_hashes = {
            k: v for k, v in stored_summary_hashes.items()
            if k not in _owned_section_ids
        }
        merged_hashes.update(summary_hashes)
    else:
        merged_hashes = None  # type: ignore[assignment]
    set_vault_summary_hashes(
        conn,
        roll_id=roll_id,
        hashes=merged_hashes,
    )
    return PublishResult(
        vault_path=relative_path,
        your_notes_hash=your_notes_hash,
        vault_published_at=now,
    )


def _assert_under_roll_log(target: Path, vault_root: Path) -> None:
    roll_log = (vault_root / "Roll Log").resolve()
    resolved = target.resolve()
    if not resolved.is_relative_to(roll_log):
        raise ValueError(f"target {target} escapes Roll Log directory {roll_log}")


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _build_skeleton(
    *,
    title: str,
    date: str,
    partner: str | None,
    duration_s: float | None,
    roll_id: str,
    your_notes_body: str,
    summary_sections: dict[str, str] | None = None,
) -> str:
    duration = _format_duration(duration_s)
    partner_line = f"partner: {_yaml_quote(partner)}" if partner else "partner:"
    duration_line = f"duration: {_yaml_quote(duration)}" if duration else "duration:"

    frontmatter = "\n".join([
        "---",
        f"date: {_yaml_quote(date)}",
        partner_line,
        duration_line,
        "tags: [roll]",
        f"roll_id: {_yaml_quote(roll_id)}",
        "---",
    ])

    parts = [f"{frontmatter}\n\n# {title}"]
    if summary_sections:
        for section_id, heading in _SUMMARY_SECTION_ORDER:
            parts.append(f"{heading}\n\n{summary_sections[section_id]}")
    parts.append(f"{_YOUR_NOTES_HEADING}\n\n{your_notes_body}")
    return "\n\n".join(parts) + "\n"


def _format_duration(duration_s: float | None) -> str:
    if duration_s is None:
        return ""
    total = int(round(duration_s))
    m = total // 60
    s = total % 60
    return f"{m}:{s:02d}"


def _extract_your_notes_section(text: str) -> str:
    m = _YOUR_NOTES_HEADING_RE.search(text)
    if m is None:
        return ""
    body_start = text.find("\n", m.end())
    if body_start == -1:
        return ""
    body_start += 1

    rest = text[body_start:]
    m = _SECTION_BOUNDARY.search(rest)
    end = body_start + m.start() if m else len(text)

    return text[body_start:end].strip()


def _splice_your_notes(current_text: str, new_body: str) -> str:
    m = _YOUR_NOTES_HEADING_RE.search(current_text)
    if m is None:
        separator = "" if current_text.endswith("\n\n") else ("\n" if current_text.endswith("\n") else "\n\n")
        return f"{current_text}{separator}{_YOUR_NOTES_HEADING}\n\n{new_body}\n"

    heading_idx = m.start()
    body_start = current_text.find("\n", heading_idx)
    if body_start == -1:
        body_start = len(current_text)
    else:
        body_start += 1
    rest = current_text[body_start:]
    m = _SECTION_BOUNDARY.search(rest)
    end = body_start + m.start() if m else len(current_text)

    before = current_text[: heading_idx + len(_YOUR_NOTES_HEADING)]
    after = current_text[end:]

    if after and not after.startswith("\n"):
        after = "\n" + after
    if not after:
        after = "\n"

    return f"{before}\n\n{new_body}\n{after}"


_EXTRA_BLANK_LINES = _re.compile(r"\n{2,}")


def _hash_section(body: str) -> str:
    normalised = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalised = _EXTRA_BLANK_LINES.sub("\n", normalised)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


_SCORE_METRIC_LABELS: list[tuple[str, str]] = [
    ("guard_retention", "Guard Retention"),
    ("positional_awareness", "Positional Awareness"),
    ("transition_quality", "Transition Quality"),
]


def render_summary_sections(
    scores_payload: dict,
    sections: list[dict],
) -> dict[str, str]:
    """Render summary-owned section bodies. No Position Distribution post-M9b.

    Returns {section_id: body_markdown} — bodies do NOT include the `## <heading>` line.
    """
    section_by_id = {s["id"]: s for s in sections}

    summary = scores_payload["summary"].strip()

    scores = scores_payload["scores"]
    score_rows = [
        "| Metric                 | Score |",
        "| ---------------------- | ----- |",
    ] + [
        f"| {label:<22} | {scores[metric]}/10  |"
        for metric, label in _SCORE_METRIC_LABELS
    ]
    scores_body = "\n".join(score_rows)

    km_lines: list[str] = []
    for km in scores_payload["key_moments"]:
        sec = section_by_id.get(km["section_id"])
        if sec is None:
            label = "?:??"
        else:
            label = f"{_format_mm_ss(sec['start_s'])} – {_format_mm_ss(sec['end_s'])}"
        km_lines.append(f"- **{label}** — {km['note']}")
    key_moments_body = "\n".join(km_lines)

    ti_lines = [f"{i + 1}. {item}" for i, item in enumerate(scores_payload["top_improvements"])]
    top_improvements_body = "\n".join(ti_lines)
    st_lines = [f"- {item}" for item in scores_payload["strengths"]]
    strengths_body = "\n".join(st_lines)

    return {
        "summary": summary,
        "scores": scores_body,
        "key_moments": key_moments_body,
        "top_improvements": top_improvements_body,
        "strengths": strengths_body,
    }


def update_report_section(
    conn,
    *,
    roll_id: str,
    vault_root: Path,
    body: str,
    force: bool = False,
) -> str:
    """Splice/insert the `## Report` section into a roll's existing markdown."""
    import json as _json

    roll_row = get_roll(conn, roll_id)
    if roll_row is None:
        raise LookupError(f"Roll not found: {roll_id}")

    vault_state = get_vault_state(conn, roll_id)
    if vault_state is None or not vault_state.get("vault_path"):
        raise FileNotFoundError(
            f"Roll {roll_id} has not been published to the vault — Save to Vault first."
        )

    target = vault_root / vault_state["vault_path"]
    _assert_under_roll_log(target, vault_root)
    if not target.exists():
        raise FileNotFoundError(f"Vault file missing on disk: {target}")

    current_text = target.read_text(encoding="utf-8")

    stored_summary_hashes: dict[str, str] = {}
    if roll_row["vault_summary_hashes"]:
        stored_summary_hashes = _json.loads(roll_row["vault_summary_hashes"]) or {}
    current_body = _extract_section_by_heading(current_text, "## Report")
    current_hash = _hash_section(current_body)
    stored_hash = stored_summary_hashes.get("report")
    if stored_hash is not None and current_hash != stored_hash and not force:
        raise ConflictError(current_hash=current_hash, stored_hash=stored_hash)

    replaced = _replace_section_body_if_present(current_text, "## Report", body)
    if replaced is not None:
        new_text = replaced
    else:
        new_text = _insert_section_at_ordered_position(
            current_text, "## Report", body, [_YOUR_NOTES_HEADING]
        )

    _atomic_write(target, new_text)

    new_hash = _hash_section(body)
    stored_summary_hashes["report"] = new_hash
    set_vault_summary_hashes(conn, roll_id=roll_id, hashes=stored_summary_hashes)
    return new_hash
