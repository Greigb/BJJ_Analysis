#!/usr/bin/env python3
"""
Generate Obsidian vault notes from BJJ taxonomy data.

Reads taxonomy.json and the JSX taxonomy component to produce:
- Position notes in Positions/ with wikilinks and frontmatter
- Technique notes in Techniques/ with backlinks to positions

Usage:
    python tools/generate_vault_notes.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"
JSX_PATH = Path(__file__).parent / "components" / "bjj-position-taxonomy.jsx"
POSITIONS_DIR = ROOT / "Positions"
TECHNIQUES_DIR = ROOT / "Techniques"


def load_taxonomy():
    with open(TAXONOMY_PATH) as f:
        return json.load(f)


def parse_jsx_techniques():
    """Extract richer technique data from the JSX taxonomy component."""
    jsx_text = JSX_PATH.read_text()

    # Parse each position block: { name: "...", techniques: [...] }
    position_techniques = {}
    pattern = r'name:\s*"([^"]+)",\s*techniques:\s*\[([^\]]+)\]'
    for match in re.finditer(pattern, jsx_text):
        name = match.group(1)
        techs_raw = match.group(2)
        techs = [t.strip().strip('"').strip("'") for t in techs_raw.split(",")]
        techs = [t for t in techs if t]
        position_techniques[name] = techs

    return position_techniques


def build_transition_map(taxonomy):
    """Build a dict of position_id -> {to: [...], from: [...]}."""
    transitions = {}
    for pos in taxonomy["positions"]:
        transitions[pos["id"]] = {"to": [], "from": []}

    for a, b in taxonomy["valid_transitions"]:
        if a in transitions:
            transitions[a]["to"].append(b)
        if b in transitions:
            transitions[b]["from"].append(a)

    return transitions


def match_taxonomy_to_jsx(taxonomy_positions, jsx_techniques):
    """Map taxonomy position IDs to JSX technique lists via fuzzy name matching."""
    mapping = {}

    jsx_names = list(jsx_techniques.keys())

    for pos in taxonomy_positions:
        pos_name = pos["name"].lower()
        best_match = None
        best_score = 0

        for jsx_name in jsx_names:
            jsx_lower = jsx_name.lower()
            # Check for substring match in either direction
            if pos_name in jsx_lower or jsx_lower in pos_name:
                score = len(set(pos_name.split()) & set(jsx_lower.split()))
                if score > best_score:
                    best_score = score
                    best_match = jsx_name
            # Also check key words
            pos_words = set(pos_name.replace("(", "").replace(")", "").split())
            jsx_words = set(jsx_lower.replace("(", "").replace(")", "").split())
            overlap = len(pos_words & jsx_words)
            if overlap > best_score:
                best_score = overlap
                best_match = jsx_name

        if best_match and best_score > 0:
            mapping[pos["id"]] = jsx_techniques[best_match]

    return mapping


def sanitize_filename(name):
    """Make a string safe for use as a filename."""
    return re.sub(r'[/\\<>:"|?*]', '-', name).strip()


def generate_position_notes(taxonomy, transitions, technique_mapping):
    POSITIONS_DIR.mkdir(exist_ok=True)

    pos_map = {p["id"]: p for p in taxonomy["positions"]}
    cat_map = taxonomy["categories"]

    for pos in taxonomy["positions"]:
        cat = cat_map[pos["category"]]
        trans = transitions.get(pos["id"], {"to": [], "from": []})
        techniques = technique_mapping.get(pos["id"], [])

        filename = sanitize_filename(pos["name"]) + ".md"
        filepath = POSITIONS_DIR / filename

        lines = [
            "---",
            f'category: "{cat["label"]}"',
            f"dominance: {cat['dominance']}",
            f"position_id: {pos['id']}",
            f"tags: [position, {pos['category'].replace('_', '-')}]",
            "---",
            "",
            f"# {pos['name']}",
            "",
            f"**Category:** {cat['label']}",
            "",
        ]

        # Techniques
        if techniques:
            lines.append("## Techniques from here")
            for tech in techniques:
                lines.append(f"- [[{tech}]]")
            lines.append("")

        # Transitions
        to_positions = [pos_map[pid]["name"] for pid in trans["to"] if pid in pos_map]
        from_positions = [pos_map[pid]["name"] for pid in trans["from"] if pid in pos_map]

        if to_positions or from_positions:
            lines.append("## Transitions")
            if to_positions:
                to_links = ", ".join(f"[[{name}]]" for name in to_positions)
                lines.append(f"**To:** {to_links}")
            if from_positions:
                from_links = ", ".join(f"[[{name}]]" for name in from_positions)
                lines.append(f"**From:** {from_links}")
            lines.append("")

        # Personal notes section
        lines.extend([
            "## My Notes",
            "",
            "<!-- Your observations, what works for you, what to drill -->",
            "",
        ])

        filepath.write_text("\n".join(lines))
        print(f"  Created: Positions/{filename}")

    return pos_map


def collect_all_techniques(technique_mapping):
    """Get unique set of all techniques across all positions."""
    all_techs = {}
    for pos_id, techs in technique_mapping.items():
        for tech in techs:
            if tech not in all_techs:
                all_techs[tech] = []
            all_techs[tech].append(pos_id)
    return all_techs


def generate_technique_notes(all_techniques, pos_map):
    TECHNIQUES_DIR.mkdir(exist_ok=True)

    for tech_name, position_ids in sorted(all_techniques.items()):
        filename = sanitize_filename(tech_name) + ".md"
        filepath = TECHNIQUES_DIR / filename

        position_names = [pos_map[pid]["name"] for pid in position_ids if pid in pos_map]

        lines = [
            "---",
            f"tags: [technique]",
            "---",
            "",
            f"# {tech_name}",
            "",
            "## Used from",
            "",
        ]
        for pname in sorted(set(position_names)):
            lines.append(f"- [[{pname}]]")

        lines.extend([
            "",
            "## Description",
            "",
            "<!-- How to execute this technique -->",
            "",
            "## Tips",
            "",
            "<!-- Personal tips and details -->",
            "",
            "## Drill Ideas",
            "",
            "<!-- Specific drills to improve this technique -->",
            "",
        ])

        filepath.write_text("\n".join(lines))
        print(f"  Created: Techniques/{filename}")


def main():
    print("Loading taxonomy...")
    taxonomy = load_taxonomy()

    print("Parsing JSX technique data...")
    jsx_techniques = parse_jsx_techniques()
    print(f"  Found {len(jsx_techniques)} position entries in JSX")

    print("Mapping taxonomy positions to techniques...")
    technique_mapping = match_taxonomy_to_jsx(taxonomy["positions"], jsx_techniques)
    print(f"  Matched {len(technique_mapping)}/{len(taxonomy['positions'])} positions")

    print("Building transition map...")
    transitions = build_transition_map(taxonomy)

    print("\nGenerating position notes...")
    pos_map = generate_position_notes(taxonomy, transitions, technique_mapping)
    print(f"  Generated {len(taxonomy['positions'])} position notes")

    print("\nCollecting techniques...")
    all_techniques = collect_all_techniques(technique_mapping)
    print(f"  Found {len(all_techniques)} unique techniques")

    print("\nGenerating technique notes...")
    generate_technique_notes(all_techniques, pos_map)
    print(f"  Generated {len(all_techniques)} technique notes")

    print("\nDone!")


if __name__ == "__main__":
    main()
