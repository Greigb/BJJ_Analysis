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

# TODO(Task 11): CATEGORY_EMOJI and compute_distribution removed in M9b; vault_writer to be rewritten.
CATEGORY_EMOJI: dict[str, str] = {
    "standing":          "⬜",
    "guard_bottom":      "🟦",
    "guard_top":         "🟨",
    "dominant_top":      "🟩",
    "inferior_bottom":   "🟥",
    "leg_entanglement":  "🟫",
    "scramble":          "🟪",
}


def compute_distribution(analyses: list[dict], categories: list[dict]) -> dict:
    """Stub — will be removed when vault_writer is rewritten in Task 11."""
    return {"timeline": [], "counts": {}, "percentages": {}}
from server.db import (
    get_analyses,
    get_annotations_by_roll,
    get_moments,
    get_roll,
    get_vault_state,
    set_vault_state,
    set_vault_summary_hashes,
)


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
_YOUR_NOTES_HEADING_RE = _re.compile(r"^## Your Notes\s*$", _re.MULTILINE)
_SECTION_BOUNDARY = _re.compile(r"^## ", _re.MULTILINE)

# Ordered list of summary-owned sections — determines vault markdown order.
_SUMMARY_SECTION_ORDER: list[tuple[str, str]] = [
    ("summary", "## Summary"),
    ("scores", "## Scores"),
    ("position_distribution", "## Position Distribution"),
    ("key_moments", "## Key Moments"),
    ("top_improvements", "## Top Improvements"),
    ("strengths", "## Strengths Observed"),
]


def _heading_regex(heading: str) -> _re.Pattern:
    """Build a line-anchored regex for a given '## Section Name' heading."""
    escaped = _re.escape(heading)
    return _re.compile(rf"^{escaped}\s*$", _re.MULTILINE)


def _extract_section_by_heading(text: str, heading: str) -> str:
    """Return the body (stripped) of the section with the given heading.

    Empty string if heading not found. Section body spans from the line
    after the heading to the next `^## ` heading (exclusive) or EOF.
    """
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
    """Replace the body of a section if the heading is present. Return None if absent.

    Reuses the existing boundary-detection logic. The caller handles the 'absent'
    case by inserting the section at the correct ordered position via
    `_insert_section_at_ordered_position`.
    """
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
    """Insert a missing owned section at its correct ordered position.

    `ordered_headings_after` is the list of owned-section headings that should
    appear AFTER `heading` in the canonical order (e.g. for `## Summary`, that's
    `['## Scores', '## Position Distribution', ...,  '## Your Notes']`).

    We insert just before the first of those that's actually present in the file.
    If none are present, insert at EOF (fallback).
    """
    insert_at: int | None = None
    for following in ordered_headings_after:
        m = _heading_regex(following).search(current_text)
        if m is not None:
            insert_at = m.start()
            break

    block = f"{heading}\n\n{new_body}\n\n"
    if insert_at is None:
        # Fallback — append at end with a separator.
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
    taxonomy: dict | None = None,
) -> PublishResult:
    """Publish a roll's annotations + (if finalised) summary sections.

    `taxonomy` is required when the roll is finalised (needed for distribution labels).
    Passing `None` is acceptable only for unfinalised rolls.
    """
    roll_row = get_roll(conn, roll_id)
    if roll_row is None:
        raise LookupError(f"Roll not found: {roll_id}")

    # ---------- Render authoritative bodies ----------
    annotations = get_annotations_by_roll(conn, roll_id)
    your_notes_body = render_your_notes(annotations)
    your_notes_hash = _hash_section(your_notes_body)

    is_finalised = roll_row["scores_json"] is not None and roll_row["finalised_at"] is not None
    summary_section_bodies: dict[str, str] = {}
    summary_hashes: dict[str, str] = {}

    if is_finalised:
        if taxonomy is None:
            raise ValueError("publish() requires `taxonomy` for finalised rolls")
        import json as _json
        scores_payload = _json.loads(roll_row["scores_json"])
        moment_rows = get_moments(conn, roll_id)
        flat_analyses: list[dict] = []
        position_to_category = {p["id"]: p["category"] for p in taxonomy.get("positions", [])}
        for m in moment_rows:
            for a in get_analyses(conn, m["id"]):
                flat_analyses.append({
                    "position_id": a["position_id"],
                    "player": a["player"],
                    "timestamp_s": m["timestamp_s"],
                    "category": position_to_category.get(a["position_id"], "scramble"),
                })
        distribution = compute_distribution(flat_analyses, taxonomy.get("categories", []))
        summary_section_bodies = render_summary_sections(
            scores_payload=scores_payload,
            distribution=distribution,
            categories=taxonomy.get("categories", []),
            moments=[{"id": m["id"], "timestamp_s": m["timestamp_s"]} for m in moment_rows],
        )
        summary_hashes = {k: _hash_section(v) for k, v in summary_section_bodies.items()}

    # ---------- Target path ----------
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

        # Your Notes conflict check
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

        # Per-summary-section conflict check
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

        # Splice or insert each owned section in canonical order.
        new_text = current_text
        if is_finalised:
            for idx, (section_id, heading) in enumerate(_SUMMARY_SECTION_ORDER):
                replaced = _replace_section_body_if_present(
                    new_text, heading, summary_section_bodies[section_id]
                )
                if replaced is not None:
                    new_text = replaced
                else:
                    # Heading absent — insert at correct ordered position.
                    # "After" = remaining summary sections + Your Notes.
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
    # Merge summary_hashes with any non-summary-section keys already stored
    # (e.g. "report" written by update_report_section) so they aren't erased.
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
    """Quote a string value safely for YAML frontmatter.

    Uses double quotes; escapes embedded backslashes and double-quote characters.
    Protects against YAML-ambiguous inputs like colons, brackets, the literal
    "null", leading @/!, and newlines (which become \\n in the quoted form).
    """
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
    """Return the body of `## Your Notes` section, or '' if absent.

    The body spans from the first blank line after the heading to the next
    `## ` heading (exclusive) or EOF. Leading/trailing whitespace is stripped
    so whitespace-only differences don't trigger false conflicts.
    """
    m = _YOUR_NOTES_HEADING_RE.search(text)
    if m is None:
        return ""
    # Start at the character after the heading line's newline.
    body_start = text.find("\n", m.end())
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
    m = _YOUR_NOTES_HEADING_RE.search(current_text)
    if m is None:
        # Append a new section.
        separator = "" if current_text.endswith("\n\n") else ("\n" if current_text.endswith("\n") else "\n\n")
        return f"{current_text}{separator}{_YOUR_NOTES_HEADING}\n\n{new_body}\n"

    heading_idx = m.start()
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


_EXTRA_BLANK_LINES = _re.compile(r"\n{2,}")


def _hash_section(body: str) -> str:
    """Hash the section body after normalising whitespace.

    Normalisation: CRLF → LF, strip leading/trailing whitespace, collapse runs
    of 2+ newlines to exactly 1. This prevents false conflicts from Obsidian
    re-saves that only touch whitespace (line-ending conversion, blank-line
    cleanup) without changing the semantic content of the section.
    """
    normalised = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalised = _EXTRA_BLANK_LINES.sub("\n", normalised)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


# ---------- M6a: summary section rendering ----------


_SCORE_METRIC_LABELS: list[tuple[str, str]] = [
    ("guard_retention", "Guard Retention"),
    ("positional_awareness", "Positional Awareness"),
    ("transition_quality", "Transition Quality"),
]


def render_summary_sections(
    scores_payload: dict,
    distribution: dict,
    categories: list[dict],
    moments: list[dict],
) -> dict[str, str]:
    """Render the six summary-owned section bodies.

    Returns `{section_id: body_markdown}` — bodies do NOT include the `## <heading>` line.
    """
    moments_by_id = {m["id"]: m for m in moments}
    category_label_by_id = {c["id"]: c["label"] for c in categories}

    # Summary
    summary = scores_payload["summary"].strip()

    # Scores
    scores = scores_payload["scores"]
    score_rows = [
        "| Metric                 | Score |",
        "| ---------------------- | ----- |",
    ] + [
        f"| {label:<22} | {scores[metric]}/10  |"
        for metric, label in _SCORE_METRIC_LABELS
    ]
    scores_body = "\n".join(score_rows)

    # Position Distribution
    dist_rows = ["| Category        | Count | %   |", "|-----------------|-------|-----|"]
    for cat_id in sorted(distribution["counts"].keys()):
        label = category_label_by_id.get(cat_id, cat_id)
        count = distribution["counts"][cat_id]
        pct = distribution["percentages"][cat_id]
        dist_rows.append(f"| {label:<15} | {count:<5} | {pct}% |")
    timeline_bar = "".join(
        CATEGORY_EMOJI.get(cat, "⬛") for cat in distribution["timeline"]
    )
    legend = "Legend: " + " ".join(
        f"{CATEGORY_EMOJI[cat]}{category_label_by_id.get(cat, cat)}"
        for cat in CATEGORY_EMOJI.keys()
    )
    position_distribution_body = (
        "\n".join(dist_rows)
        + "\n\n### Position Timeline Bar\n\n"
        + (timeline_bar if timeline_bar else "(no analyses)")
        + "\n\n"
        + legend
    )

    # Key Moments
    km_lines: list[str] = []
    for km in scores_payload["key_moments"]:
        m = moments_by_id.get(km["moment_id"])
        mm_ss = _format_mm_ss(m["timestamp_s"]) if m is not None else "?:??"
        km_lines.append(f"- **{mm_ss}** — {km['note']}")
    key_moments_body = "\n".join(km_lines)

    # Top Improvements
    ti_lines = [f"{i + 1}. {item}" for i, item in enumerate(scores_payload["top_improvements"])]
    top_improvements_body = "\n".join(ti_lines)

    # Strengths
    st_lines = [f"- {item}" for item in scores_payload["strengths"]]
    strengths_body = "\n".join(st_lines)

    return {
        "summary": summary,
        "scores": scores_body,
        "position_distribution": position_distribution_body,
        "key_moments": key_moments_body,
        "top_improvements": top_improvements_body,
        "strengths": strengths_body,
    }


# ---------- M6b: report section ----------


def update_report_section(
    conn,
    *,
    roll_id: str,
    vault_root: Path,
    body: str,
    force: bool = False,
) -> str:
    """Splice/insert the `## Report` section into a roll's existing markdown.

    Assumes the roll has been published at least once (vault file exists).
    Raises `FileNotFoundError` if the vault file is missing.
    Raises `ConflictError` if the current `## Report` body hash doesn't match
    `vault_summary_hashes['report']` and `force=False`.
    On success returns the new hash and persists it to `vault_summary_hashes`.
    """
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

    # Conflict check against stored per-section hash.
    stored_summary_hashes: dict[str, str] = {}
    if roll_row["vault_summary_hashes"]:
        stored_summary_hashes = _json.loads(roll_row["vault_summary_hashes"]) or {}
    current_body = _extract_section_by_heading(current_text, "## Report")
    current_hash = _hash_section(current_body)
    stored_hash = stored_summary_hashes.get("report")
    if stored_hash is not None and current_hash != stored_hash and not force:
        raise ConflictError(current_hash=current_hash, stored_hash=stored_hash)

    # Splice or insert.
    replaced = _replace_section_body_if_present(current_text, "## Report", body)
    if replaced is not None:
        new_text = replaced
    else:
        # Report sits just above Your Notes (after all summary sections).
        new_text = _insert_section_at_ordered_position(
            current_text, "## Report", body, [_YOUR_NOTES_HEADING]
        )

    _atomic_write(target, new_text)

    new_hash = _hash_section(body)
    stored_summary_hashes["report"] = new_hash
    set_vault_summary_hashes(conn, roll_id=roll_id, hashes=stored_summary_hashes)
    return new_hash
