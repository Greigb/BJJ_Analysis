"""Taxonomy loader for the BJJ Graph page.

Parses `tools/taxonomy.json` and exposes a frontend-ready shape with
category tints attached. Shipped once at app startup; no runtime IO.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class Category(TypedDict):
    id: str
    label: str
    dominance: int
    tint: str


class Position(TypedDict):
    id: str
    name: str
    category: str


class Transition(TypedDict):
    from_: str  # serialised as "from" in JSON
    to: str


class Taxonomy(TypedDict):
    categories: list[Category]
    positions: list[Position]
    transitions: list[dict]  # {"from": str, "to": str}


TINTS: dict[str, str] = {
    "standing":          "#e6f2ff",  # pale blue
    "guard_bottom":      "#e6f7e6",  # pale green
    "guard_top":         "#fff5e6",  # pale orange
    "dominant_top":      "#ffe6e6",  # pale red
    "inferior_bottom":   "#f0e6ff",  # pale purple
    "leg_entanglement":  "#fff9cc",  # pale yellow
    "scramble":          "#eeeeee",  # pale grey
}
_FALLBACK_TINT = "#dddddd"


def load_taxonomy(path: Path) -> Taxonomy:
    """Load and shape the taxonomy for the graph API.

    Adds a `tint` field to each category by keying into TINTS (or a fallback).
    Converts `valid_transitions` from [from, to] pairs into {"from","to"} objects.
    Raises FileNotFoundError if path doesn't exist.
    """
    raw = json.loads(path.read_text())

    categories: list[Category] = [
        {
            "id": cat_id,
            "label": cat["label"],
            "dominance": int(cat.get("dominance", 0)),
            "tint": TINTS.get(cat_id, _FALLBACK_TINT),
        }
        for cat_id, cat in raw["categories"].items()
    ]

    positions: list[Position] = [
        {"id": p["id"], "name": p["name"], "category": p["category"]}
        for p in raw["positions"]
    ]

    transitions = [{"from": f, "to": t} for f, t in raw["valid_transitions"]]

    return {
        "categories": categories,
        "positions": positions,
        "transitions": transitions,
    }
