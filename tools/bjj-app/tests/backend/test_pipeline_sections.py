"""Integration tests for the M9b async section pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.analysis.pipeline import run_section_analysis
from server.analysis.rate_limit import SlidingWindowLimiter
from server.db import connect, create_roll, get_moments, get_sections_by_roll, init_db


def _short_video_path() -> Path:
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


def _make_roll(conn) -> None:
    create_roll(
        conn, id="r1", title="Test", date="2026-04-22",
        video_path="assets/r1/source.mp4", duration_s=2.0,
        partner=None, result="unknown", created_at=1713700000,
        player_a_name="Greig", player_b_name="Sam",
    )


def _fake_settings(tmp_path):
    from server.config import Settings
    return Settings(
        project_root=tmp_path,
        vault_root=tmp_path,
        db_path=tmp_path / "db.sqlite",
        host="0.0.0.0",
        port=8000,
        frontend_build_dir=tmp_path / "build",
        claude_bin=Path("/usr/bin/false"),
        claude_model="test",
        claude_max_calls=100,
        claude_window_seconds=60.0,
        taxonomy_path=tmp_path / "taxonomy.json",
    )


async def _drain(agen):
    events = []
    async for e in agen:
        events.append(e)
    return events


@pytest.mark.asyncio
async def test_emits_section_started_and_section_done(tmp_path, monkeypatch):
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return '{"narrative": "A recovers guard.", "coach_tip": "Elbows tight."}'

    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        events = await _drain(run_section_analysis(
            conn=conn,
            roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.5}],
            duration_s=2.0,
            player_a_name="Greig",
            player_b_name="Sam",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        stages = [e["stage"] for e in events]
        assert stages[0] == "section_started"
        assert "section_done" in stages
        assert stages[-1] == "done"
        done = events[-1]
        assert done["total"] == 1

        sections = get_sections_by_roll(conn, "r1")
        assert len(sections) == 1
        assert sections[0]["narrative"] == "A recovers guard."
        assert sections[0]["coach_tip"] == "Elbows tight."
        assert sections[0]["analysed_at"] is not None
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_adding_sections_preserves_prior_sections(tmp_path, monkeypatch):
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return '{"narrative": "x", "coach_tip": "y"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="Greig", player_b_name="Sam",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 1.0, "end_s": 2.0}],
            duration_s=2.0,
            player_a_name="Greig", player_b_name="Sam",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        sections = get_sections_by_roll(conn, "r1")
        assert len(sections) == 2
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_assigns_unique_frame_idx_across_runs(tmp_path, monkeypatch):
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return '{"narrative": "x", "coach_tip": "y"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 1.0, "end_s": 2.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        moments = get_moments(conn, "r1")
        idxs = [m["frame_idx"] for m in moments]
        assert len(idxs) == len(set(idxs)), f"frame_idx collisions: {idxs}"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_section_error_continues_batch(tmp_path, monkeypatch):
    """A parse error on section 1 must not block section 2."""
    calls = {"n": 0}
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json"
        return '{"narrative": "ok", "coach_tip": "tip"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        events = await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[
                {"start_s": 0.0, "end_s": 1.0},
                {"start_s": 1.0, "end_s": 2.0},
            ],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        stages = [e["stage"] for e in events]
        assert "section_error" in stages
        assert stages.count("section_done") == 1
        assert stages[-1] == "done"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_rate_limit_retry_emits_queued_then_succeeds(tmp_path, monkeypatch):
    from server.analysis.claude_cli import RateLimitedError

    calls = {"n": 0}
    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitedError(retry_after_s=0.01)
        return '{"narrative": "ok", "coach_tip": "tip"}'
    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    async def fake_sleep(s): pass
    monkeypatch.setattr("server.analysis.pipeline.asyncio.sleep", fake_sleep)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        events = await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        ))
        stages = [e["stage"] for e in events]
        assert "section_queued" in stages
        assert "section_done" in stages
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_pipeline_passes_positions_reference_to_claude_prompt(tmp_path, monkeypatch):
    """The optional positions kwarg is threaded into build_section_prompt."""
    captured: dict = {}

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        captured["prompt"] = prompt
        return '{"narrative": "ok", "coach_tip": "tip"}'

    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        _make_roll(conn)
        fixture_position = {
            "position_id": "fixture_pos",
            "name": "Fixture Position",
            "markdown": "# Fixture Position",
            "vault_path": "Positions/Fixture Position.md",
            "how_to_identify": "FIXTURE_GROUND_PHRASE_XYZ appears in prompt.",
        }
        await _drain(run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
            positions=[fixture_position],
        ))
    finally:
        conn.close()

    assert "FIXTURE_GROUND_PHRASE_XYZ" in captured["prompt"]
    assert "Fixture Position" in captured["prompt"]
    assert "Canonical BJJ positions" in captured["prompt"]
