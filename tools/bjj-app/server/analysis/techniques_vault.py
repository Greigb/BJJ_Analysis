"""Index of Techniques/*.md vault files keyed by technique_id from frontmatter.

Mirrors positions_vault.py. Built once at app startup in main.create_app(),
consumed by server.api.analyse (for grounded prompts) and server.eval (for
the m10-techniques variants).

Techniques cross-link to positions via `## Used from` wikilinks. Resolution
of those wikilinks to canonical position_ids uses the already-loaded
positions_index as an authority — any wikilink that does not match a
position name is dropped with a warning (not raised), so a typo in one
vault note never breaks app startup.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TypedDict

import frontmatter

from server.analysis.positions_vault import PositionNote

logger = logging.getLogger(__name__)

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

_USED_FROM_RE = re.compile(
    r"^##\s+Used from\s*\n+(.+?)(?=\n##\s|\Z)",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)

_HOW_TO_IDENTIFY_RE = re.compile(
    r"^##\s+How to Identify\s*\n+(.+?)(?=\n##\s|\Z)",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)

# `[[Target]]` or `[[Target|Alias]]` — capture the pre-pipe target text.
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


class TechniqueNote(TypedDict):
    technique_id: str
    name: str
    markdown: str
    vault_path: str
    how_to_identify: str | None
    used_from_position_ids: list[str]


def load_techniques_index(
    vault_root: Path, positions_index: dict[str, PositionNote]
) -> dict[str, TechniqueNote]:
    """Scan vault_root/Techniques/*.md and return an index keyed by technique_id.

    `positions_index` is consulted to resolve `## Used from` wikilinks into
    canonical position_ids. Techniques without `technique_id` frontmatter are
    silently skipped; a missing `Techniques/` directory returns an empty dict.
    """
    techniques_dir = vault_root / "Techniques"
    if not techniques_dir.is_dir():
        return {}

    name_to_pid = {
        note["name"].strip(): pid for pid, note in positions_index.items()
    }

    index: dict[str, TechniqueNote] = {}
    for md_path in sorted(techniques_dir.glob("*.md")):
        post = frontmatter.load(md_path)
        technique_id = post.metadata.get("technique_id")
        if not technique_id:
            continue

        name = _extract_name(post.content, fallback=md_path.stem)
        index[str(technique_id)] = TechniqueNote(
            technique_id=str(technique_id),
            name=name,
            markdown=post.content,
            vault_path=f"Techniques/{md_path.name}",
            how_to_identify=_extract_how_to_identify(post.content),
            used_from_position_ids=_resolve_used_from(
                post.content, name_to_pid, md_path.name
            ),
        )
    return index


def techniques_for_positions(
    *,
    techniques_index: dict[str, TechniqueNote],
    position_ids: set[str],
    taxonomy: dict,
    max_per_position: int = 10,
) -> list[TechniqueNote]:
    """Techniques linked to any position in `position_ids`, taxonomy-ordered.

    Order follows `taxonomy["techniques"]`. Techniques present in the taxonomy
    but missing from `techniques_index` are silently dropped. Output length
    is capped at `max_per_position * max(1, len(position_ids))` so the
    grounding block stays bounded even when the taxonomy has hundreds of
    techniques against a small set of grounded positions.
    """
    cap = max_per_position * max(1, len(position_ids))
    out: list[TechniqueNote] = []
    for t in taxonomy.get("techniques", []):
        entry = techniques_index.get(t["id"])
        if entry is None:
            continue
        if not (set(entry["used_from_position_ids"]) & position_ids):
            continue
        out.append(entry)
        if len(out) >= cap:
            break
    return out


def _extract_name(content: str, *, fallback: str) -> str:
    m = _H1_RE.search(content)
    return m.group(1) if m else fallback


def _extract_how_to_identify(content: str) -> str | None:
    m = _HOW_TO_IDENTIFY_RE.search(content)
    if m is None:
        return None
    return m.group(1).strip() or None


def _resolve_used_from(
    content: str, name_to_pid: dict[str, str], technique_filename: str
) -> list[str]:
    m = _USED_FROM_RE.search(content)
    if m is None:
        return []
    resolved: list[str] = []
    for wl in _WIKILINK_RE.finditer(m.group(1)):
        target = wl.group(1).strip()
        pid = name_to_pid.get(target)
        if pid is None:
            logger.warning(
                "Unresolved wikilink [[%s]] in Techniques/%s — technique will be "
                "scoped to one fewer position.",
                target, technique_filename,
            )
            continue
        if pid not in resolved:
            resolved.append(pid)
    return resolved
