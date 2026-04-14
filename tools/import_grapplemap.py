#!/usr/bin/python3
"""
Import GrappleMap data into BJJ Analysis project.

Downloads and parses GrappleMap.txt, maps positions/transitions to our
taxonomy, and generates:
  - grapplemap_data.json (full parsed data)
  - position_reference.json (enriched position descriptions for model prompts)

Usage:
    python import_grapplemap.py
"""

import json
import re
import math
import urllib.request
from pathlib import Path
from collections import defaultdict

TOOLS_DIR = Path(__file__).parent
TAXONOMY_PATH = TOOLS_DIR / "taxonomy.json"
GRAPPLEMAP_PATH = TOOLS_DIR / "GrappleMap.txt"
GRAPPLEMAP_URL = "https://raw.githubusercontent.com/Eelis/GrappleMap/master/GrappleMap.txt"
OUTPUT_DATA = TOOLS_DIR / "grapplemap_data.json"
OUTPUT_REF = TOOLS_DIR / "position_reference.json"

# Base62 decoding
B62 = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

def b62_decode(c1, c2):
    """Decode two base62 characters to a coordinate value."""
    return B62.index(c1) * 62 + B62.index(c2)

def decode_joint_line(line):
    """Decode a line of base62-encoded joint coordinates."""
    line = line.strip()
    joints = []
    for i in range(0, len(line) - 1, 2):
        val = b62_decode(line[i], line[i+1])
        # Convert from 0-3843 range to -2.0..+2.0 range
        joints.append(round((val / 1000.0) - 2.0, 3))
    return joints


def decode_position_coords(coord_lines):
    """Decode 4 lines of coordinates into joint positions for 2 players."""
    all_coords = []
    for line in coord_lines:
        all_coords.extend(decode_joint_line(line))

    # 14 joints per player, 3 coords (x,y,z) each = 84 values per player
    # Total = 168 values across 4 lines
    if len(all_coords) < 168:
        return None, None

    player1 = []
    player2 = []
    for i in range(14):
        idx = i * 6
        player1.append({
            "x": all_coords[idx], "y": all_coords[idx+1], "z": all_coords[idx+2]
        })
        player2.append({
            "x": all_coords[idx+3], "y": all_coords[idx+4], "z": all_coords[idx+5]
        })

    return player1, player2


JOINT_NAMES = [
    "left_toe", "right_toe", "left_heel", "right_heel",
    "left_knee", "right_knee", "left_hip", "right_hip",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist"
]


def analyse_body_geometry(joints):
    """Analyse joint positions to describe body geometry."""
    if not joints or len(joints) < 14:
        return ""

    def dist(a, b):
        return math.sqrt(sum((joints[a][k] - joints[b][k])**2 for k in "xyz"))

    def height(idx):
        return joints[idx]["y"]

    # Key measurements
    hip_height = (height(6) + height(7)) / 2
    shoulder_height = (height(8) + height(9)) / 2
    knee_height = (height(4) + height(5)) / 2

    torso_vertical = abs(shoulder_height - hip_height)
    is_upright = torso_vertical > 0.3 and shoulder_height > hip_height
    is_flat = torso_vertical < 0.15
    is_inverted = hip_height > shoulder_height

    knee_spread = dist(4, 5)
    hip_spread = dist(6, 7)

    descriptions = []
    if is_upright:
        descriptions.append("upright/standing")
    elif is_flat:
        descriptions.append("lying flat")
    elif is_inverted:
        descriptions.append("hips above shoulders (inverted/turtle)")

    if knee_spread > 0.4:
        descriptions.append("legs spread wide")
    elif knee_spread < 0.15:
        descriptions.append("knees together")

    return ", ".join(descriptions) if descriptions else "neutral position"


# ─── Tag-to-Taxonomy Mapping ─────────────────────────────────────────────────

TAG_MAP = {
    # Guard bottom
    ("closed_guard",): "closed_guard_bottom",
    ("full_guard",): "closed_guard_bottom",
    ("half_guard", "bottom"): "half_guard_bottom",
    ("half_guard", "bottom_turned_in"): "half_guard_bottom",
    ("half_guard", "bottom_supine"): "half_guard_bottom",
    ("butterfly",): "butterfly_guard",
    ("butterfly", "bottom_seated"): "butterfly_guard",
    ("de_la_riva",): "de_la_riva",
    ("spider_guard",): "spider_lasso",
    ("x_guard",): "single_leg_x",
    ("rubber_guard",): "closed_guard_bottom",

    # Guard top
    ("full_guard", "top"): "closed_guard_top",
    ("closed_guard", "top"): "closed_guard_top",
    ("combat_base",): "closed_guard_top",
    ("half_guard", "top"): "half_guard_top",
    ("half_guard", "top_kneeling"): "half_guard_top",
    ("knee_slice",): "headquarters",
    ("headquarters",): "headquarters",

    # Dominant top
    ("side_control",): "side_control_top",
    ("side_control", "top"): "side_control_top",
    ("mount",): "mount_top",
    ("mount", "top"): "mount_top",
    ("back", "top"): "back_mount",
    ("back", "seatbelt"): "back_mount",
    ("back", "top_seated"): "back_mount",
    ("knee_on_belly",): "knee_on_belly",
    ("north_south",): "north_south_top",
    ("north_south", "top"): "north_south_top",
    ("crucifix",): "crucifix",

    # Inferior bottom
    ("side_control", "bottom"): "side_control_bottom",
    ("side_control", "bottom_supine"): "side_control_bottom",
    ("mount", "bottom"): "mount_bottom",
    ("mount", "bottom_supine"): "mount_bottom",
    ("back", "bottom"): "back_taken",
    ("turtle",): "turtle_bottom",
    ("turtle", "bottom"): "turtle_bottom",
    ("north_south", "bottom"): "north_south_bottom",

    # Leg entanglements
    ("ashi_garami",): "single_leg_x",
    ("slx",): "single_leg_x",
    ("50_50",): "fifty_fifty",
    ("heel_hook",): "single_leg_x",
    ("inside_sankaku",): "inside_sankaku",
    ("saddle",): "inside_sankaku",
    ("honeyhole",): "inside_sankaku",

    # Scramble
    ("standing",): "standing_neutral",
    ("collar_tie",): "standing_clinch",
    ("clinch",): "standing_clinch",
    ("dogfight",): "dogfight",
    ("guillotine",): "front_headlock",
    ("front_headlock",): "front_headlock",
    ("darce",): "front_headlock",
    ("anaconda",): "front_headlock",
    ("turtle", "top"): "turtle_top",
    ("sprawl",): "turtle_top",
}


def map_tags_to_taxonomy(tags):
    """Map a set of GrappleMap tags to our taxonomy position ID."""
    tag_set = set(tags)

    # Try specific multi-tag matches first (more specific = better)
    best_match = None
    best_score = 0

    for key_tags, position_id in TAG_MAP.items():
        if all(t in tag_set for t in key_tags):
            score = len(key_tags)
            if score > best_score:
                best_score = score
                best_match = position_id

    return best_match


# ─── Parser ───────────────────────────────────────────────────────────────────

def parse_grapplemap(filepath):
    """Parse GrappleMap.txt into positions and transitions."""
    with open(filepath) as f:
        lines = f.readlines()

    positions = []
    transitions = []
    i = 0

    while i < len(lines):
        line = lines[i].rstrip('\n')

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # Check if this is a tags line
        if line.startswith("tags:"):
            # We missed the name — skip
            i += 1
            continue

        # Check if line starts with spaces (coordinate data)
        if line.startswith("    "):
            i += 1
            continue

        # Check for ref: line
        if line.startswith("ref:"):
            i += 1
            continue

        # This should be a position/transition name
        name_lines = [line]
        i += 1

        # Check for continuation of name (lines with \n in the original)
        # Actually names can span multiple concepts but are on one line with \n
        # The raw file has literal \n in names — they're on one line

        # Look for tags line
        if i < len(lines) and lines[i].startswith("tags:"):
            tags_line = lines[i].strip()
            tags = tags_line.replace("tags:", "").strip().split()
            i += 1
        else:
            continue

        # Check for ref line
        ref = None
        if i < len(lines) and lines[i].startswith("ref:"):
            ref = lines[i].replace("ref:", "").strip()
            i += 1

        # Collect coordinate lines
        coord_lines = []
        while i < len(lines) and lines[i].startswith("    "):
            coord_lines.append(lines[i].strip())
            i += 1

        # Parse the name (replace \n with space for readability)
        name = name_lines[0].replace("\\n", " ").strip()

        # Determine if position (4 coord lines) or transition (multiple of 4)
        entry = {
            "name": name,
            "tags": tags,
            "ref": ref,
        }

        if len(coord_lines) == 4:
            # Single position
            p1, p2 = decode_position_coords(coord_lines)
            if p1:
                entry["player1_geometry"] = analyse_body_geometry(p1)
                entry["player2_geometry"] = analyse_body_geometry(p2)
            positions.append(entry)
        elif len(coord_lines) > 4 and len(coord_lines) % 4 == 0:
            # Transition (multiple frames)
            entry["frames"] = len(coord_lines) // 4
            transitions.append(entry)
        elif len(coord_lines) >= 4:
            # Treat as position (take first 4 lines)
            p1, p2 = decode_position_coords(coord_lines[:4])
            if p1:
                entry["player1_geometry"] = analyse_body_geometry(p1)
                entry["player2_geometry"] = analyse_body_geometry(p2)
            positions.append(entry)

    return positions, transitions


def map_to_taxonomy(positions, transitions, taxonomy):
    """Map GrappleMap entries to our taxonomy positions."""
    mapped = defaultdict(lambda: {"variations": [], "techniques": [], "references": []})

    for pos in positions:
        tax_id = map_tags_to_taxonomy(pos["tags"])
        if tax_id:
            mapped[tax_id]["variations"].append({
                "name": pos["name"],
                "tags": pos["tags"],
                "player1_geometry": pos.get("player1_geometry", ""),
                "player2_geometry": pos.get("player2_geometry", ""),
            })

    for trans in transitions:
        tax_id = map_tags_to_taxonomy(trans["tags"])
        if tax_id:
            mapped[tax_id]["techniques"].append(trans["name"])
            if trans.get("ref"):
                mapped[tax_id]["references"].append(trans["ref"])

    return dict(mapped)


def build_position_reference(mapped, taxonomy):
    """Build enriched position reference for model prompts."""
    pos_map = {p["id"]: p for p in taxonomy["positions"]}
    reference = {}

    for pos in taxonomy["positions"]:
        pid = pos["id"]
        cat = taxonomy["categories"][pos["category"]]
        gm_data = mapped.get(pid, {"variations": [], "techniques": [], "references": []})

        # Collect variation names
        variation_names = list(set(v["name"] for v in gm_data["variations"]))[:8]

        # Collect body geometry descriptions
        geometries = []
        for v in gm_data["variations"][:5]:
            g1 = v.get("player1_geometry", "")
            g2 = v.get("player2_geometry", "")
            if g1:
                geometries.append(f"Person 1: {g1}")
            if g2:
                geometries.append(f"Person 2: {g2}")

        # Build distinguishing features
        existing_cues = pos.get("visual_cues", "")

        reference[pid] = {
            "name": pos["name"],
            "category": cat["label"],
            "visual_cues": existing_cues,
            "grapplemap_variations": variation_names,
            "grapplemap_variation_count": len(gm_data["variations"]),
            "body_geometry": list(set(geometries))[:4],
            "techniques_from_here": list(set(gm_data["techniques"]))[:10],
            "instructional_references": list(set(gm_data["references"]))[:5],
        }

    return reference


def main():
    # Download if not present
    if not GRAPPLEMAP_PATH.exists():
        print("Downloading GrappleMap.txt...")
        urllib.request.urlretrieve(GRAPPLEMAP_URL, GRAPPLEMAP_PATH)
        print("  Downloaded.")

    # Load taxonomy
    with open(TAXONOMY_PATH) as f:
        taxonomy = json.load(f)

    # Parse
    print("Parsing GrappleMap.txt...")
    positions, transitions = parse_grapplemap(GRAPPLEMAP_PATH)
    print(f"  Found {len(positions)} positions, {len(transitions)} transitions")

    # Map to taxonomy
    print("Mapping to taxonomy...")
    mapped = map_to_taxonomy(positions, transitions, taxonomy)

    # Stats
    mapped_count = sum(len(v["variations"]) for v in mapped.values())
    unmapped_positions = [p for p in positions if not map_tags_to_taxonomy(p["tags"])]
    print(f"  Mapped {mapped_count}/{len(positions)} positions to {len(mapped)} taxonomy entries")
    print(f"  Unmapped: {len(unmapped_positions)} positions")

    # Show unmapped tags for debugging
    unmapped_tags = set()
    for p in unmapped_positions[:20]:
        unmapped_tags.update(p["tags"])
    if unmapped_tags:
        print(f"  Common unmapped tags: {', '.join(sorted(unmapped_tags)[:20])}")

    # Save full data
    gm_data = {
        "positions": positions,
        "transitions": transitions,
        "mapped_to_taxonomy": {k: {
            "variation_count": len(v["variations"]),
            "variation_names": [var["name"] for var in v["variations"][:10]],
            "techniques": list(set(v["techniques"]))[:15],
            "references": list(set(v["references"]))[:10],
        } for k, v in mapped.items()},
    }
    with open(OUTPUT_DATA, "w") as f:
        json.dump(gm_data, f, indent=2)
    print(f"\nSaved full data to: {OUTPUT_DATA}")

    # Build position reference
    print("Building position reference...")
    reference = build_position_reference(mapped, taxonomy)
    with open(OUTPUT_REF, "w") as f:
        json.dump(reference, f, indent=2)
    print(f"Saved position reference to: {OUTPUT_REF}")

    # Summary
    print(f"\nSummary:")
    for pid, data in sorted(reference.items()):
        var_count = data["grapplemap_variation_count"]
        tech_count = len(data["techniques_from_here"])
        ref_count = len(data["instructional_references"])
        if var_count > 0:
            print(f"  {data['name']}: {var_count} variations, {tech_count} techniques, {ref_count} refs")


if __name__ == "__main__":
    main()
