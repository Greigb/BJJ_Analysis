#!/usr/bin/env python3
"""Copy reviewed drafts from <vault>/Techniques.draft/ back into <vault>/Techniques/.

The draft directory is the authoritative "next state"; this script copies each
draft file to its corresponding live vault file. Report artefacts
(frontmatter_diff.md, wikilink_report.md, bodies_diff.md) are skipped.

Usage (from tools/bjj-app/):
    .venv/bin/python scripts/apply_technique_drafts.py
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from server.config import load_settings


_REPORT_FILENAMES = {
    "frontmatter_diff.md",
    "wikilink_report.md",
    "bodies_diff.md",
    "taxonomy_techniques_proposal.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply reviewed Techniques.draft/ back into Techniques/."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be copied, don't write anything.",
    )
    args = parser.parse_args()

    settings = load_settings()
    draft_dir = settings.vault_root / "Techniques.draft"
    target_dir = settings.vault_root / "Techniques"

    if not draft_dir.is_dir():
        print(f"Draft dir {draft_dir} not found — run bootstrap first.", file=sys.stderr)
        return 1

    count = 0
    skipped_missing_target = 0
    for draft in sorted(draft_dir.glob("*.md")):
        if draft.name in _REPORT_FILENAMES:
            continue
        target = target_dir / draft.name
        if not target.exists():
            print(f"WARN: target {target} does not exist, skipping.", file=sys.stderr)
            skipped_missing_target += 1
            continue
        if args.dry_run:
            print(f"would copy: {draft} -> {target}")
        else:
            shutil.copyfile(draft, target)
        count += 1

    verb = "would apply" if args.dry_run else "applied"
    print(
        f"{verb} {count} drafts "
        f"(skipped {skipped_missing_target} with no matching target).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
