"""M10 end-to-end: real vault + real taxonomy → grounded section prompt."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.analysis.pipeline import run_section_analysis
from server.analysis.positions_vault import (
    load_positions_index,
    ordered_positions_from_taxonomy,
)
from server.analysis.rate_limit import SlidingWindowLimiter
from server.analysis.taxonomy import load_taxonomy
from server.analysis.techniques_vault import (
    load_techniques_index,
    techniques_for_positions,
)
from server.db import connect, create_roll, init_db


_REPO_ROOT = Path(__file__).resolve().parents[4]  # BJJ_Analysis/


def _short_video_path() -> Path:
    return Path(__file__).parent / "fixtures" / "short_video.mp4"


def _fake_settings(tmp_path: Path):
    from server.config import Settings
    return Settings(
        project_root=tmp_path,
        vault_root=_REPO_ROOT,
        db_path=tmp_path / "db.sqlite",
        host="0.0.0.0",
        port=8000,
        frontend_build_dir=tmp_path / "build",
        claude_bin=Path("/usr/bin/false"),
        claude_model="test",
        claude_max_calls=100,
        claude_window_seconds=60.0,
        taxonomy_path=_REPO_ROOT / "tools" / "taxonomy.json",
        grounding_mode="positions",
    )


@pytest.mark.asyncio
async def test_real_vault_grounding_includes_closed_guard_identify_text(
    tmp_path, monkeypatch
):
    """Drive the pipeline with the real Positions/ vault + real taxonomy.json
    and verify the distinctive "Ankles are LOCKED" phrase from
    Closed Guard (Bottom).md ends up in the Claude prompt."""
    vault_root = _REPO_ROOT
    taxonomy_path = vault_root / "tools" / "taxonomy.json"

    index = load_positions_index(vault_root)
    taxonomy = load_taxonomy(taxonomy_path)
    assert "closed_guard_bottom" in index, "vault must contain Closed Guard (Bottom).md"

    positions = ordered_positions_from_taxonomy(
        positions_index=index, taxonomy=taxonomy
    )
    assert len(positions) >= 10, "expected many canonical positions to ground on"

    captured: dict = {}

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        captured["prompt"] = prompt
        return '{"narrative": "ok", "coach_tip": "tip"}'

    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        create_roll(
            conn, id="r1", title="Grounding", date="2026-04-22",
            video_path="assets/r1/source.mp4", duration_s=2.0,
            partner=None, result="unknown", created_at=1,
            player_a_name="A", player_b_name="B",
        )
        async for _ in run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
            positions=positions,
        ):
            pass
    finally:
        conn.close()

    prompt = captured["prompt"]
    assert "Ankles are LOCKED" in prompt, "grounding text missing from prompt"
    assert "Canonical BJJ positions" in prompt, "grounding header missing"

    # Ordering regression guard: reference block must precede the JSON schema
    # hint so schema-last JSON adherence is preserved.
    ref_idx = prompt.index("Canonical BJJ positions")
    schema_idx = prompt.index('"narrative"')
    assert ref_idx < schema_idx


@pytest.mark.asyncio
async def test_real_vault_techniques_grounding_nests_technique_names(
    tmp_path, monkeypatch
):
    """M12 end-to-end: positions+techniques mode threads real vault techniques
    (nested under positions) into the Claude prompt."""
    vault_root = _REPO_ROOT
    taxonomy_path = vault_root / "tools" / "taxonomy.json"

    positions_index = load_positions_index(vault_root)
    techniques_index = load_techniques_index(vault_root, positions_index)
    taxonomy = load_taxonomy(taxonomy_path)

    positions = ordered_positions_from_taxonomy(
        positions_index=positions_index, taxonomy=taxonomy
    )
    techniques = techniques_for_positions(
        techniques_index=techniques_index,
        position_ids={p["position_id"] for p in positions},
        taxonomy=taxonomy,
    )
    assert len(techniques) >= 10, (
        "expected many canonical techniques to ground on in real taxonomy"
    )

    captured: dict = {}

    async def fake_run_claude(prompt, *, settings, limiter, stream_callback=None):
        captured["prompt"] = prompt
        return '{"narrative": "ok", "coach_tip": "tip"}'

    monkeypatch.setattr("server.analysis.pipeline.run_claude", fake_run_claude)

    db = tmp_path / "db.sqlite"
    init_db(db)
    conn = connect(db)
    try:
        create_roll(
            conn, id="r1", title="M12 grounding", date="2026-04-23",
            video_path="assets/r1/source.mp4", duration_s=2.0,
            partner=None, result="unknown", created_at=1,
            player_a_name="A", player_b_name="B",
        )
        async for _ in run_section_analysis(
            conn=conn, roll_id="r1",
            video_path=_short_video_path(),
            frames_dir=tmp_path / "frames",
            sections=[{"start_s": 0.0, "end_s": 1.0}],
            duration_s=2.0,
            player_a_name="A", player_b_name="B",
            settings=_fake_settings(tmp_path),
            limiter=SlidingWindowLimiter(max_calls=10, window_seconds=60),
            positions=positions,
            techniques=techniques,
            techniques_mode="names",
        ):
            pass
    finally:
        conn.close()

    prompt = captured["prompt"]
    # Positions header still present (M10 lineage).
    assert "Canonical BJJ positions" in prompt
    # M12: nested techniques sub-line at least once.
    assert "Techniques from here:" in prompt
    # At least one canonical technique name must appear — Armbar is present
    # in the real vault and links to multiple taxonomy positions.
    assert "Armbar" in prompt
