#!/usr/bin/env python3
"""Draft technique_id frontmatter + How to Identify bodies into Techniques.draft/.

Idempotent — re-run skips files that already have technique_id / How to Identify.
Writes to `<vault_root>/Techniques.draft/` so the live vault files are never
touched until the user runs `apply_technique_drafts.py`.

Usage (from tools/bjj-app/):
    # Task 1: deterministic phase — add technique_id frontmatter to all notes.
    .venv/bin/python scripts/bootstrap_technique_notes.py --frontmatter-only

    # Task 2: Claude-assisted phase — generate ## How to Identify bodies.
    .venv/bin/python scripts/bootstrap_technique_notes.py
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import re
import sys
from pathlib import Path

from server.analysis.positions_vault import load_positions_index
from server.config import load_settings


_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_USED_FROM_RE = re.compile(
    r"^##\s+Used from\s*\n+(.+?)(?=\n##\s|\Z)",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)
_FRONTMATTER_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)


def slugify(stem: str) -> str:
    """Filename stem → snake_case ASCII slug, with parenthetical notes stripped."""
    s = re.sub(r"\([^)]*\)", "", stem)
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def splice_frontmatter_add_key(text: str, key: str, value: str) -> tuple[str, bool]:
    """Regex-splice `key: value` into the existing frontmatter block.

    Avoids a full `frontmatter.dump` round-trip, which rewrites whitespace and
    key order and generates a large cosmetic diff. Idempotent: if `key` is
    already present, returns the text unchanged.
    """
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        new = f"---\n{key}: {value}\n---\n\n" + text
        return new, True
    open_marker, body, close_marker = m.groups()
    if re.search(rf"^\s*{re.escape(key)}\s*:", body, re.MULTILINE):
        return text, False
    new_body = body.rstrip("\n") + f"\n{key}: {value}"
    new_text = open_marker + new_body + close_marker + text[m.end():]
    return new_text, True


def _build_name_to_pid(positions_index: dict) -> dict[str, str]:
    return {note["name"].strip(): pid for pid, note in positions_index.items()}


def _collect_wikilinks(text: str) -> list[str]:
    m = _USED_FROM_RE.search(text)
    if m is None:
        return []
    return [wl.group(1).strip() for wl in _WIKILINK_RE.finditer(m.group(1))]


def frontmatter_phase(vault_root: Path, draft_dir: Path) -> None:
    techniques_dir = vault_root / "Techniques"
    if not techniques_dir.is_dir():
        print(f"ERROR: {techniques_dir} not found.", file=sys.stderr)
        sys.exit(2)

    positions_index = load_positions_index(vault_root)
    name_to_pid = _build_name_to_pid(positions_index)

    draft_dir.mkdir(parents=True, exist_ok=True)

    diffs: list[str] = []
    per_wikilink: dict[str, list[str]] = {}  # wikilink_text → [technique filenames]
    changed_count = 0

    for md_path in sorted(techniques_dir.glob("*.md")):
        original = md_path.read_text()
        tid = slugify(md_path.stem)
        new_text, changed = splice_frontmatter_add_key(original, "technique_id", tid)

        (draft_dir / md_path.name).write_text(new_text)

        if changed:
            changed_count += 1
            diff = "".join(difflib.unified_diff(
                original.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/Techniques/{md_path.name}",
                tofile=f"b/Techniques/{md_path.name}",
            ))
            diffs.append(diff)

        for target in _collect_wikilinks(original):
            per_wikilink.setdefault(target, []).append(md_path.name)

    resolved, unresolved = [], []
    for target in sorted(per_wikilink):
        users = per_wikilink[target]
        suffix = f" _(used by {len(users)} techniques)_"
        if target in name_to_pid:
            resolved.append(f"- `[[{target}]]` → `{name_to_pid[target]}`{suffix}")
        else:
            unresolved.append(
                f"- `[[{target}]]` → **UNRESOLVED** — first seen in `{users[0]}`"
            )

    (draft_dir / "frontmatter_diff.md").write_text(
        "# Frontmatter diff — `technique_id` additions\n\n"
        f"Changed {changed_count} files (skipped {len(list(techniques_dir.glob('*.md'))) - changed_count} "
        "already having `technique_id`).\n\n"
        "```diff\n" + "\n".join(diffs) + "\n```\n"
    )
    (draft_dir / "wikilink_report.md").write_text(
        "# Wikilink resolution report\n\n"
        f"**Total unique wikilink targets in `## Used from`:** {len(per_wikilink)}  \n"
        f"**Resolved to a taxonomy position:** {len(resolved)}  \n"
        f"**Unresolved:** {len(unresolved)}\n\n"
        "Unresolved wikilinks will cause the owning technique to be **silently dropped** "
        "from `techniques_for_positions` at prompt time. Fix the vault (rename the "
        "position H1 or the wikilink) before flipping `BJJ_GROUNDING_MODE=positions+techniques`.\n\n"
        "## Unresolved\n\n"
        + ("\n".join(unresolved) if unresolved else "_(none — all wikilinks resolve)_")
        + "\n\n## Resolved\n\n"
        + "\n".join(resolved)
        + "\n"
    )
    print(f"Wrote {changed_count} changed drafts to {draft_dir}/", file=sys.stderr)
    print(
        f"Wikilinks: {len(resolved)} resolved, {len(unresolved)} unresolved "
        f"(see {draft_dir}/wikilink_report.md).",
        file=sys.stderr,
    )


async def bodies_phase(vault_root: Path, draft_dir: Path) -> None:
    # Task 2 of the M12 plan — implemented after Task 1 lands.
    raise NotImplementedError(
        "bodies phase lands in Task 2; re-run with --frontmatter-only for Task 1"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Draft technique_id frontmatter + How to Identify bodies into "
            "<vault>/Techniques.draft/."
        )
    )
    parser.add_argument(
        "--frontmatter-only", action="store_true",
        help="Only draft technique_id frontmatter (deterministic, no Claude calls).",
    )
    args = parser.parse_args()

    settings = load_settings()
    draft_dir = settings.vault_root / "Techniques.draft"

    if args.frontmatter_only:
        frontmatter_phase(settings.vault_root, draft_dir)
        return 0
    asyncio.run(bodies_phase(settings.vault_root, draft_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
