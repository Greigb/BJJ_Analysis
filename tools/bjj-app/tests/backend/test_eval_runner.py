"""Tests for server.eval.runner — generation + judgement orchestration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.analysis.rate_limit import SlidingWindowLimiter
from server.db import connect, create_roll, init_db, insert_moments, insert_section
from server.eval.runner import evaluate_section_variants


def _fake_settings(tmp_path: Path):
    from server.config import Settings
    (tmp_path / "assets").mkdir(exist_ok=True)
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
        taxonomy_path=tmp_path / "tools" / "taxonomy.json",
    )


def _seed_one_analysed_section(tmp_path: Path) -> tuple[str, str]:
    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        create_roll(
            conn, id="r1", title="Test", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=2.0,
            partner=None, result="unknown", created_at=1,
            player_a_name="Greig", player_b_name="Sam",
        )
        sec = insert_section(
            conn, roll_id="r1", start_s=0.0, end_s=1.0, sample_interval_s=1.0,
        )
        insert_moments(
            conn, roll_id="r1",
            moments=[{
                "frame_idx": 0, "timestamp_s": 0.0, "pose_delta": None,
                "section_id": sec["id"],
            }],
        )
    finally:
        conn.close()
    # Create the frame file the pipeline expects on disk.
    frames_dir = tmp_path / "assets" / "r1" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    (frames_dir / "frame_000000.jpg").write_bytes(b"x")
    return "r1", sec["id"]


@pytest.mark.asyncio
async def test_evaluate_section_variants_runs_each_variant_and_returns_judgements(
    tmp_path, monkeypatch,
):
    roll_id, section_id = _seed_one_analysed_section(tmp_path)

    # First call per variant = generation; second call = judgement.
    call_kind = {"i": 0}

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        call_kind["i"] += 1
        if call_kind["i"] % 2 == 1:
            return json.dumps({
                "narrative": "A recovers guard.",
                "coach_tip": "Elbows tight.",
            })
        return json.dumps({
            "scores": {
                "vocabulary": 7, "accuracy": 8, "specificity": 6, "coach_tip": 7,
            },
            "rationale": {
                "vocabulary": "OK.", "accuracy": "OK.",
                "specificity": "OK.", "coach_tip": "OK.",
            },
            "overall": 7,
            "verdict": "Solid.",
        })

    monkeypatch.setattr("server.eval.runner.run_claude", fake_run_claude)

    results = await evaluate_section_variants(
        fixture_entries=[{
            "roll_id": roll_id, "section_id": section_id, "note": "smoke",
        }],
        variant_names=["m9b-baseline", "m10-grounded"],
        settings=_fake_settings(tmp_path),
        limiter=SlidingWindowLimiter(max_calls=100, window_seconds=60),
    )

    assert len(results) == 2
    variants = sorted(r.variant for r in results)
    assert variants == ["m10-grounded", "m9b-baseline"]
    for r in results:
        assert r.roll_id == roll_id
        assert r.section_id == section_id
        assert r.error is None
        assert r.narrative == "A recovers guard."
        assert r.coach_tip == "Elbows tight."
        assert r.judgement is not None
        assert r.judgement["scores"]["vocabulary"] == 7
        assert r.judgement["overall"] == 7


@pytest.mark.asyncio
async def test_evaluate_section_variants_records_error_when_section_not_found(
    tmp_path, monkeypatch,
):
    db = tmp_path / "db.sqlite"
    init_db(db)

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        pytest.fail("run_claude must not be called for a missing section")

    monkeypatch.setattr("server.eval.runner.run_claude", fake_run_claude)

    results = await evaluate_section_variants(
        fixture_entries=[{"roll_id": "no", "section_id": "no", "note": None}],
        variant_names=["m9b-baseline"],
        settings=_fake_settings(tmp_path),
        limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
    )
    assert len(results) == 1
    assert results[0].error is not None
    assert "not found" in results[0].error.lower()
    assert results[0].narrative is None


@pytest.mark.asyncio
async def test_evaluate_section_variants_rejects_unknown_variant_name(
    tmp_path,
):
    with pytest.raises(ValueError, match="unknown section variant"):
        await evaluate_section_variants(
            fixture_entries=[],
            variant_names=["does-not-exist"],
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
        )


@pytest.mark.asyncio
async def test_evaluate_section_variants_records_error_on_malformed_generation(
    tmp_path, monkeypatch,
):
    roll_id, section_id = _seed_one_analysed_section(tmp_path)

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        return "not json"  # generation output is broken

    monkeypatch.setattr("server.eval.runner.run_claude", fake_run_claude)

    results = await evaluate_section_variants(
        fixture_entries=[{
            "roll_id": roll_id, "section_id": section_id, "note": None,
        }],
        variant_names=["m9b-baseline"],
        settings=_fake_settings(tmp_path),
        limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
    )
    assert len(results) == 1
    assert results[0].narrative is None
    assert results[0].judgement is None
    assert results[0].error is not None
    assert "generation" in results[0].error.lower()
