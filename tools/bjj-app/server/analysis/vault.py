"""Read roll summaries from the Obsidian vault's Roll Log/ directory."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class RollSummary:
    """One row in the home page's roll list.

    `id` is the markdown filename stem — a stable, vault-relative identifier
    safe to send over HTTP and use in URLs. `path` is the full filesystem
    Path for internal use by later-milestone code that reads/writes the file.
    `roll_id` is the SQLite uuid from frontmatter (present on files the app
    has published, absent on legacy markdown).
    """

    id: str
    path: Path
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None
    roll_id: str | None


def list_rolls(vault_root: Path) -> list[RollSummary]:
    """Scan `vault_root/Roll Log/*.md` and return parsed summaries, newest first.

    Files without YAML frontmatter are skipped. If `Roll Log/` does not exist,
    returns an empty list.
    """
    roll_log = vault_root / "Roll Log"
    if not roll_log.is_dir():
        return []

    summaries: list[RollSummary] = []
    for md_path in sorted(roll_log.glob("*.md")):
        post = frontmatter.load(md_path)
        if not post.metadata:
            continue

        title = _extract_title(post.content, fallback=md_path.stem)
        summaries.append(
            RollSummary(
                id=md_path.stem,
                path=md_path,
                title=title,
                date=str(post.metadata.get("date", "")),
                partner=_str_or_none(post.metadata.get("partner")),
                duration=_str_or_none(post.metadata.get("duration")),
                result=_str_or_none(post.metadata.get("result")),
                roll_id=_str_or_none(post.metadata.get("roll_id")),
            )
        )

    summaries.sort(key=lambda r: r.date, reverse=True)
    return summaries


def _extract_title(content: str, *, fallback: str) -> str:
    match = _TITLE_RE.search(content)
    return match.group(1) if match else fallback


def _str_or_none(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
