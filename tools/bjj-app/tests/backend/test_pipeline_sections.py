"""Integration test for M9 section-based pipeline."""
from __future__ import annotations

from pathlib import Path

from server.analysis.pipeline import run_section_analysis
from server.db import connect, create_roll, get_sections_by_roll, init_db


def _short_video_path() -> Path:
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


def _make_roll(conn) -> None:
    create_roll(
        conn,
        id="r1",
        title="Test",
        date="2026-04-22",
        video_path="assets/r1/source.mp4",
        duration_s=2.0,
        partner=None,
        result="unknown",
        created_at=1713700000,
        player_a_name="Player A",
        player_b_name="Player B",
    )


def test_run_section_analysis_emits_frames_and_done(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        frames_dir = tmp_path / "frames"

        events = list(
            run_section_analysis(
                conn=conn,
                roll_id="r1",
                video_path=_short_video_path(),
                frames_dir=frames_dir,
                sections=[
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0},
                ],
                duration_s=2.0,
            )
        )

        # At least one "frames" event and exactly one terminal "done" event.
        stages = [e["stage"] for e in events]
        assert "frames" in stages
        assert stages[-1] == "done"

        done = events[-1]
        assert done["total"] == 1  # one timestamp at 0.0
        assert len(done["moments"]) == 1
        assert done["moments"][0]["section_id"]
    finally:
        conn.close()


def test_run_section_analysis_persists_sections_row(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        frames_dir = tmp_path / "frames"

        list(
            run_section_analysis(
                conn=conn,
                roll_id="r1",
                video_path=_short_video_path(),
                frames_dir=frames_dir,
                sections=[
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0},
                    {"start_s": 1.0, "end_s": 2.0, "sample_interval_s": 0.5},
                ],
                duration_s=2.0,
            )
        )

        sections = get_sections_by_roll(conn, "r1")
        assert len(sections) == 2
        assert sections[0]["start_s"] == 0.0
        assert sections[1]["start_s"] == 1.0
        assert sections[1]["sample_interval_s"] == 0.5
    finally:
        conn.close()


def test_run_section_analysis_dedupes_overlapping_timestamps(tmp_path):
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        frames_dir = tmp_path / "frames"

        events = list(
            run_section_analysis(
                conn=conn,
                roll_id="r1",
                video_path=_short_video_path(),
                frames_dir=frames_dir,
                sections=[
                    {"start_s": 0.0, "end_s": 1.5, "sample_interval_s": 1.0},   # 0, 1
                    {"start_s": 1.0, "end_s": 2.0, "sample_interval_s": 1.0},   # 1 (dup),
                ],
                duration_s=2.0,
            )
        )

        done = events[-1]
        timestamps = sorted({m["timestamp_s"] for m in done["moments"]})
        assert timestamps == [0.0, 1.0]  # 1.0 deduped
    finally:
        conn.close()


def test_re_running_replaces_prior_sections(tmp_path):
    """Second call to run_section_analysis must not leak prior-run sections."""
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        frames_dir = tmp_path / "frames"

        # First run: 2 sections.
        list(
            run_section_analysis(
                conn=conn,
                roll_id="r1",
                video_path=_short_video_path(),
                frames_dir=frames_dir,
                sections=[
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0},
                    {"start_s": 1.0, "end_s": 2.0, "sample_interval_s": 1.0},
                ],
                duration_s=2.0,
            )
        )
        assert len(get_sections_by_roll(conn, "r1")) == 2

        # Second run: 1 section. Prior 2 must be replaced.
        list(
            run_section_analysis(
                conn=conn,
                roll_id="r1",
                video_path=_short_video_path(),
                frames_dir=frames_dir,
                sections=[
                    {"start_s": 0.0, "end_s": 1.0, "sample_interval_s": 1.0},
                ],
                duration_s=2.0,
            )
        )
        sections_after = get_sections_by_roll(conn, "r1")
        assert len(sections_after) == 1, (
            f"Expected 1 section after re-run, got {len(sections_after)} — "
            f"sections from the prior run leaked"
        )
    finally:
        conn.close()
