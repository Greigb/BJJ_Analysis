"""M9 section-based analysis pipeline.

Takes a list of user-picked sections, extracts frames at each section's
requested interval, persists sections + moments in one transaction, and
yields SSE-shaped events the caller feeds into a StreamingResponse.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from server.analysis.frames import extract_frames_at_timestamps
from server.analysis.sections import build_sample_timestamps
from server.db import insert_moments, insert_section


def run_section_analysis(
    *,
    conn,
    roll_id: str,
    video_path: Path,
    frames_dir: Path,
    sections: list[dict],
    duration_s: float,
) -> Iterator[dict]:
    """Extract frames for each section, persist rows, yield progress events.

    Events:
        {"stage": "frames", "pct": 0..100}
        {"stage": "done", "total": int, "moments": [...]}

    Each moment dict in the done event has `id`, `frame_idx`, `timestamp_s`,
    and `section_id`.

    Sections are validated by the caller (api/analyse.py) — this function
    trusts the input shape.
    """
    # Insert section rows first so moments can reference them.
    section_rows = [
        insert_section(
            conn,
            roll_id=roll_id,
            start_s=s["start_s"],
            end_s=s["end_s"],
            sample_interval_s=s["sample_interval_s"],
        )
        for s in sections
    ]

    # Build a flat list of (timestamp, section_id), dedup by timestamp
    # (first-wins), sort ascending.
    pairs: dict[float, str] = {}
    for section_row, section_in in zip(section_rows, sections):
        for t in build_sample_timestamps(
            section_in["start_s"],
            section_in["end_s"],
            section_in["sample_interval_s"],
        ):
            pairs.setdefault(t, section_row["id"])

    ordered: list[tuple[float, str]] = sorted(pairs.items(), key=lambda x: x[0])
    timestamps = [p[0] for p in ordered]
    section_ids = [p[1] for p in ordered]

    yield {"stage": "frames", "pct": 0}

    # Extract frames.
    total = len(timestamps)
    if total > 0:
        extract_frames_at_timestamps(
            video_path, timestamps=timestamps, out_dir=frames_dir
        )
    yield {"stage": "frames", "pct": 100, "total": total}

    moment_inputs = [
        {
            "frame_idx": i,
            "timestamp_s": timestamps[i],
            "pose_delta": None,
            "section_id": section_ids[i],
        }
        for i in range(total)
    ]
    inserted_rows = insert_moments(conn, roll_id=roll_id, moments=moment_inputs)

    yield {
        "stage": "done",
        "total": len(inserted_rows),
        "moments": [
            {
                "id": r["id"],
                "frame_idx": r["frame_idx"],
                "timestamp_s": r["timestamp_s"],
                "section_id": r["section_id"],
            }
            for r in inserted_rows
        ],
    }
