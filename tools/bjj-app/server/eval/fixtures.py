"""YAML fixture loaders for the eval harness.

Fixtures reference existing (roll_id [, section_id]) entries in the local
DB — no re-upload, no re-extraction. Section fixtures list specific
sections; summary fixtures list whole rolls (the summary is evaluated
against the roll's currently-persisted section narratives).
"""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import yaml


class SectionFixtureEntry(TypedDict):
    roll_id: str
    section_id: str
    note: str | None


class SummaryFixtureEntry(TypedDict):
    roll_id: str
    note: str | None


class FixtureError(Exception):
    """Raised when a fixture YAML file is malformed."""


def load_section_fixture(path: Path) -> list[SectionFixtureEntry]:
    """Load a section-eval fixture. Top-level shape:

        sections:
          - roll_id: "<hex>"
            section_id: "<uuid>"
            note: "optional"
    """
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict) or "sections" not in data:
        raise FixtureError(f"{path}: missing 'sections' key")
    raw_entries = data.get("sections") or []
    out: list[SectionFixtureEntry] = []
    for i, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise FixtureError(f"{path}[{i}]: entry must be a mapping")
        roll_id = entry.get("roll_id")
        section_id = entry.get("section_id")
        if not roll_id:
            raise FixtureError(f"{path}[{i}]: missing roll_id")
        if not section_id:
            raise FixtureError(f"{path}[{i}]: missing section_id")
        note_val = entry.get("note")
        out.append({
            "roll_id": str(roll_id),
            "section_id": str(section_id),
            "note": str(note_val) if note_val else None,
        })
    return out


def load_summary_fixture(path: Path) -> list[SummaryFixtureEntry]:
    """Load a summary-eval fixture. Top-level shape:

        rolls:
          - roll_id: "<hex>"
            note: "optional"
    """
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict) or "rolls" not in data:
        raise FixtureError(f"{path}: missing 'rolls' key")
    raw_entries = data.get("rolls") or []
    out: list[SummaryFixtureEntry] = []
    for i, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise FixtureError(f"{path}[{i}]: entry must be a mapping")
        roll_id = entry.get("roll_id")
        if not roll_id:
            raise FixtureError(f"{path}[{i}]: missing roll_id")
        note_val = entry.get("note")
        out.append({
            "roll_id": str(roll_id),
            "note": str(note_val) if note_val else None,
        })
    return out
