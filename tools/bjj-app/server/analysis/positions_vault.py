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


class PositionNote(TypedDict):
    position_id: str
    name: str
    markdown: str
    vault_path: str  # relative to vault root


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
        )
    return index


def get_position(
    index: dict[str, PositionNote], position_id: str
) -> PositionNote | None:
    """Return the indexed entry for position_id, or None."""
    return index.get(position_id)


def _extract_name(content: str, *, fallback: str) -> str:
    m = _H1_RE.search(content)
    return m.group(1) if m else fallback
