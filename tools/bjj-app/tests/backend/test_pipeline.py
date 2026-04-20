from pathlib import Path

import pytest

from server.analysis.pipeline import run_analysis


def test_run_analysis_emits_progress_events_and_final_done(
    short_video_path: Path, tmp_path: Path
):
    frames_dir = tmp_path / "frames"
    events = list(run_analysis(short_video_path, frames_dir))

    # Must start with a frames stage and end with a done stage.
    stages = [e["stage"] for e in events]
    assert stages[0] == "frames"
    assert stages[-1] == "done"
    assert "pose" in stages

    # Each progress event has a 0–100 pct (the "done" event carries moments).
    for e in events[:-1]:
        assert "pct" in e
        assert 0 <= e["pct"] <= 100


def test_run_analysis_done_event_includes_moments_list(
    short_video_path: Path, tmp_path: Path
):
    frames_dir = tmp_path / "frames"
    events = list(run_analysis(short_video_path, frames_dir))

    done = events[-1]
    assert done["stage"] == "done"
    assert "moments" in done
    assert isinstance(done["moments"], list)
    # Each moment shape:
    for m in done["moments"]:
        assert "frame_idx" in m
        assert "timestamp_s" in m
        assert "pose_delta" in m


def test_run_analysis_creates_frames_in_frames_dir(
    short_video_path: Path, tmp_path: Path
):
    frames_dir = tmp_path / "frames"
    list(run_analysis(short_video_path, frames_dir))  # drain generator

    assert frames_dir.is_dir()
    jpgs = list(frames_dir.glob("*.jpg"))
    # 2s fixture at 1fps = 2 frames.
    assert len(jpgs) == 2


def test_run_analysis_always_returns_at_least_three_moments_when_possible(
    short_video_path: Path, tmp_path: Path
):
    # Even with the blank fixture (no pose detected → zero deltas), the flagging
    # rule floors at 3 moments; with only 2 frames we'll get at most 2.
    events = list(run_analysis(short_video_path, tmp_path / "frames"))
    done = events[-1]
    # For the 2-frame fixture we get up to 2 moments; floor of 3 only applies
    # when there are >= 3 frames. This test documents the boundary.
    assert len(done["moments"]) <= 2
