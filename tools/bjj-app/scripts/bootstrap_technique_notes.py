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

from server.analysis.claude_cli import (
    ClaudeProcessError, ClaudeResponseError, RateLimitedError, run_claude,
)
from server.analysis.positions_vault import load_positions_index
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import load_settings


_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    # Order matters — first match wins. Most distinctive keywords first.
    ("submission", (
        "choke", "strangle", "lock", "armbar", "triangle", "kimura", "americana",
        "omoplata", "ezekiel", "slicer", "bar trap", "bow & arrow", "gogoplata",
        "baratoplata", "arm triangle", "heel hook", "toe hold", "wrist lock",
        "head and arm", "crucifix choke", "rear naked", "guillotine",
    )),
    ("sweep", (
        "sweep", "berimbolo", "balloon", "tornado", "roll", "hook sweep",
        "scissor", "pendulum", "x-guard entry",
    )),
    ("pass", (
        "pass", "knee cut", "leg drag", "torreando", "toreando", "stack",
        "smash pass", "over under", "double under", "x-pass", "long step",
        "knee slice", "hip switch",
    )),
    ("escape", (
        "escape", "shrimp", "elbow escape", "bridge and roll", "upa", "hip bump escape",
    )),
    ("takedown", (
        "takedown", "single leg", "double leg", "body lock takedown", "snap down",
        "duck under", "ankle pick", "collar drag", "arm drag to back", "foot sweep",
        "fireman", "clinch",
    )),
    ("control", (
        "control", "grip", "back take", "mount transition", "cross face",
        "underhook", "back step", "boot scoot", "hip switch", "entry",
    )),
]


def categorize_technique(name: str) -> str:
    """Heuristic category from the technique filename. Falls back to 'control'.

    The emitted taxonomy_techniques_proposal.json is a *proposal* — the user is
    expected to hand-tune obvious mis-categorisations before pasting into
    taxonomy.json.
    """
    lower = name.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in lower:
                return category
    return "control"


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
    # Taxonomy proposal — category-grouped, alphabetical within.
    proposal: list[dict] = []
    for md_path in sorted(techniques_dir.glob("*.md")):
        stem = md_path.stem
        proposal.append({
            "id": slugify(stem),
            "name": stem,
            "category": categorize_technique(stem),
        })
    # Re-sort: category → name
    _CATEGORY_ORDER = ["submission", "sweep", "pass", "escape", "takedown", "control"]
    proposal.sort(key=lambda e: (_CATEGORY_ORDER.index(e["category"]), e["name"].lower()))

    import json as _json
    (draft_dir / "taxonomy_techniques_proposal.json").write_text(
        _json.dumps(proposal, indent=2) + "\n"
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


_HOW_TO_IDENTIFY_SECTION_RE = re.compile(
    r"^##\s+How to Identify\s*\n", re.IGNORECASE | re.MULTILINE,
)


def _build_body_prompt(technique_name: str, position_contexts: list[dict]) -> str:
    """Prompt Claude to draft a one-paragraph `## How to Identify` body.

    `position_contexts` is a list of `{"name": str, "how_to_identify": str}`
    for each position this technique is used from — gives Claude the visual
    vocabulary to ground the description in.
    """
    position_lines = "\n".join(
        f"- {p['name']}: {p['how_to_identify']}"
        for p in position_contexts
        if p.get("how_to_identify")
    )
    return (
        f"You are writing a `## How to Identify` section for the BJJ technique "
        f"\"{technique_name}\". This text will appear in an Obsidian vault note and "
        f"will be injected into a video-analysis prompt to help Claude recognise the "
        f"technique mid-execution.\n\n"
        f"The technique is typically entered from these positions (each with its own "
        f"visual cues):\n{position_lines}\n\n"
        f"Write ONE paragraph of 2-4 sentences (~200-300 characters) describing the "
        f"distinctive visual cues a coach would use to identify \"{technique_name}\" "
        f"while it is being applied in video frames. Focus on what grips, limb "
        f"positions, angles, or body-weight distribution signal this technique is "
        f"happening NOW (not what to set up or how to finish). Use standard BJJ "
        f"vocabulary. Plain text only — no markdown, no headers, no bullets, no "
        f"surrounding quotes, no preamble like \"Here is...\". Just the paragraph."
    )


def _splice_how_to_identify_body(text: str, body: str) -> tuple[str, bool]:
    """Insert `## How to Identify\\n\\n<body>\\n\\n` between `## Used from` and
    the next `##` heading. Idempotent — no-op if section already exists."""
    if _HOW_TO_IDENTIFY_SECTION_RE.search(text):
        return text, False
    # Find end of the `## Used from` block (first `\n## ` after "Used from").
    used_from_match = _USED_FROM_RE.search(text)
    if used_from_match is None:
        return text, False
    # The match captures the body up to (but not including) the next `## `.
    # Insert the new section right after the Used from body.
    insert_at = used_from_match.end()
    block = f"\n## How to Identify\n\n{body.strip()}\n\n"
    return text[:insert_at] + block + text[insert_at:], True


async def bodies_phase(vault_root: Path, draft_dir: Path) -> None:
    """Draft `## How to Identify` bodies for each technique via Claude CLI.

    Idempotent: skips techniques that already have the section. Writes drafts
    into Techniques.draft/<name>.md — same location the frontmatter phase uses,
    so a single apply_technique_drafts.py run ships both.
    """
    techniques_dir = vault_root / "Techniques"
    if not techniques_dir.is_dir():
        print(f"ERROR: {techniques_dir} not found.", file=sys.stderr)
        sys.exit(2)

    positions_index = load_positions_index(vault_root)
    name_to_pid = _build_name_to_pid(positions_index)
    # Reverse lookup: pid → {name, how_to_identify}.
    pid_to_context = {pid: note for pid, note in positions_index.items()}

    settings = load_settings()
    limiter = SlidingWindowLimiter(
        max_calls=settings.claude_max_calls,
        window_seconds=settings.claude_window_seconds,
    )

    draft_dir.mkdir(parents=True, exist_ok=True)

    diffs: list[str] = []
    written_count = 0
    skipped_existing = 0
    errors: list[str] = []

    files = sorted(techniques_dir.glob("*.md"))
    print(f"Drafting ## How to Identify for {len(files)} techniques…", file=sys.stderr)
    for idx, md_path in enumerate(files, 1):
        # Work against the draft (which already has technique_id frontmatter)
        # if it exists; otherwise against the live vault file.
        source_path = draft_dir / md_path.name
        if not source_path.exists():
            source_path = md_path
        original = source_path.read_text()

        if _HOW_TO_IDENTIFY_SECTION_RE.search(original):
            skipped_existing += 1
            # Still make sure the draft reflects the source.
            (draft_dir / md_path.name).write_text(original)
            continue

        # Build position context from `## Used from` wikilinks.
        contexts: list[dict] = []
        for wl in _collect_wikilinks(original):
            pid = name_to_pid.get(wl)
            if pid is None:
                continue
            p = pid_to_context.get(pid)
            if p is None:
                continue
            contexts.append({
                "name": p["name"],
                "how_to_identify": (p.get("how_to_identify") or "").strip(),
            })

        if not contexts:
            errors.append(f"{md_path.name}: no resolvable positions, skipped")
            (draft_dir / md_path.name).write_text(original)
            continue

        technique_name = md_path.stem
        prompt = _build_body_prompt(technique_name, contexts)

        # RateLimitedError is expected across a 115-call batch — sleep + retry
        # rather than abandon. Mirrors server/analysis/pipeline.py:144-160, but
        # unbounded since the batch is paced, not failing.
        body: str | None = None
        error_msg: str | None = None
        while True:
            try:
                body = await run_claude(prompt, settings=settings, limiter=limiter)
                break
            except RateLimitedError as exc:
                wait = max(1.0, exc.retry_after_s)
                print(
                    f"  [{idx}/{len(files)}] rate-limited on {md_path.name}, "
                    f"sleeping {wait:.1f}s…",
                    file=sys.stderr,
                )
                await asyncio.sleep(wait)
            except (ClaudeProcessError, ClaudeResponseError) as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                break

        if error_msg is not None:
            errors.append(f"{md_path.name}: {error_msg}")
            (draft_dir / md_path.name).write_text(original)
            continue

        assert body is not None  # unreachable — loop sets body or error_msg
        # Strip surrounding quotes or stray leading "Here is..." if Claude
        # slipped outside the instructions.
        body = body.strip().strip('"').strip("'")

        new_text, changed = _splice_how_to_identify_body(original, body)
        (draft_dir / md_path.name).write_text(new_text)
        if changed:
            written_count += 1
            diff = "".join(difflib.unified_diff(
                original.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/Techniques/{md_path.name}",
                tofile=f"b/Techniques/{md_path.name}",
            ))
            diffs.append(diff)

        if idx % 10 == 0:
            print(f"  [{idx}/{len(files)}] drafted {written_count}, "
                  f"skipped {skipped_existing}, errors {len(errors)}", file=sys.stderr)

    (draft_dir / "bodies_diff.md").write_text(
        "# `## How to Identify` body drafts\n\n"
        f"Wrote bodies for {written_count} techniques, "
        f"skipped {skipped_existing} already-populated, "
        f"encountered {len(errors)} errors.\n\n"
        "## Errors\n\n"
        + ("\n".join(f"- {e}" for e in errors) if errors else "_(none)_")
        + "\n\n## Diffs\n\n```diff\n" + "\n".join(diffs) + "\n```\n"
    )
    print(
        f"Done — drafted {written_count}, skipped {skipped_existing}, "
        f"errors {len(errors)}. See {draft_dir}/bodies_diff.md",
        file=sys.stderr,
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
