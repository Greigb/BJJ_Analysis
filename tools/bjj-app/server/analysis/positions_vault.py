"""Index of Positions/*.md vault files keyed by position_id from frontmatter.

Built once at app startup in main.create_app(). Looked up by the /api/vault/position/:id
endpoint to serve the side-drawer markdown.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

import frontmatter

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# Matches an H2 "How to Identify" heading and captures the body up to (but not
# including) the next H2 heading or end-of-text. `re.DOTALL` lets `.` cross
# newlines; the lookahead tolerates a following heading with or without a
# preceding blank line.
_HOW_TO_IDENTIFY_RE = re.compile(
    r"^##\s+How to Identify\s*\n+(.+?)(?=\n##\s|\Z)",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)


class PositionNote(TypedDict):
    position_id: str
    name: str
    markdown: str
    vault_path: str  # relative to vault root
    how_to_identify: str | None  # parsed body of `## How to Identify`, or None if absent


def load_positions_index(vault_root: Path) -> dict[str, PositionNote]:
    """Scan vault_root/Positions/*.md and return an index keyed by position_id.

    Positions without a `position_id` field in frontmatter are silently skipped.
    Missing `Positions/` directory returns an empty dict.
    """
    positions_dir = vault_root / "Positions"
    if not positions_dir.is_dir():
        return {}

    index: dict[str, PositionNote] = {}
    for md_path in sorted(positions_dir.glob("*.md")):
        post = frontmatter.load(md_path)
        position_id = post.metadata.get("position_id")
        if not position_id:
            continue

        name = _extract_name(post.content, fallback=md_path.stem)
        index[str(position_id)] = PositionNote(
            position_id=str(position_id),
            name=name,
            markdown=post.content,
            vault_path=f"Positions/{md_path.name}",
            how_to_identify=_extract_how_to_identify(post.content),
        )
    return index


def get_position(
    index: dict[str, PositionNote], position_id: str
) -> PositionNote | None:
    """Return the indexed entry for position_id, or None."""
    return index.get(position_id)


def ordered_positions_from_taxonomy(
    *,
    positions_index: dict[str, PositionNote],
    taxonomy: dict,
) -> list[PositionNote]:
    """Return PositionNotes in the order they appear in `taxonomy["positions"]`.

    Positions present in `taxonomy` but missing from `positions_index` are
    silently dropped (no vault note → nothing to ground with). Positions in
    `positions_index` but not in `taxonomy` are silently dropped too — the
    taxonomy is the authoritative vocabulary. Used by the /analyse handler
    to feed a stable, category-ordered grounding list into the pipeline.
    """
    out: list[PositionNote] = []
    for p in taxonomy.get("positions", []):
        entry = positions_index.get(p["id"])
        if entry is not None:
            out.append(entry)
    return out


def _extract_name(content: str, *, fallback: str) -> str:
    m = _H1_RE.search(content)
    return m.group(1) if m else fallback


def _extract_how_to_identify(content: str) -> str | None:
    """Return the stripped body of `## How to Identify`, or None if absent.

    Body spans from the heading's terminating newline to the next H2 heading
    (exclusive) or end-of-file. Note editors may follow the body with another
    H2 immediately (no blank line) — the lookahead handles that.
    """
    m = _HOW_TO_IDENTIFY_RE.search(content)
    if m is None:
        return None
    return m.group(1).strip() or None
