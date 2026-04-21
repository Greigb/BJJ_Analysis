"""Live Claude CLI integration test — opt-in only.

Run manually with:  pytest -m integration -v

This spends Claude subscription budget (~1 call). It proves that the adapter
still works end-to-end against the real CLI — the fake subprocess in
test_claude_cli.py can drift from reality if the CLI's stream-json format
changes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.analysis.claude_cli import analyse_frame
from server.analysis.rate_limit import SlidingWindowLimiter
from server.config import load_settings
from server.db import connect, init_db


pytestmark = pytest.mark.integration


@pytest.fixture
def fixture_frame(tmp_path: Path) -> Path:
    """Copy a real extracted frame into a tmpdir-under-project-root.

    We need the frame path to lie inside settings.project_root, so we place
    the copy inside the active project's assets/ tree.
    """
    src_candidates = list(
        Path("/Users/greigbradley/Desktop/BJJ_Analysis/assets/greig_1s").glob("*.jpg")
    )
    if not src_candidates:
        pytest.skip("no real frame available in assets/greig_1s/")
    src = src_candidates[0]

    dest_dir = Path("/Users/greigbradley/Desktop/BJJ_Analysis/assets/__integration_frames__")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    dest.write_bytes(src.read_bytes())
    return dest


@pytest.fixture
def cache_conn(tmp_path: Path):
    db = tmp_path / "cache.db"
    init_db(db)
    conn = connect(db)
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_live_claude_returns_parseable_analysis(
    fixture_frame: Path, cache_conn
) -> None:
    settings = load_settings()
    limiter = SlidingWindowLimiter(max_calls=10, window_seconds=300)

    streamed: list[dict] = []

    async def on_event(evt: dict) -> None:
        streamed.append(evt)

    result = await analyse_frame(
        frame_path=fixture_frame,
        timestamp_s=0.0,
        stream_callback=on_event,
        settings=settings,
        limiter=limiter,
        cache_conn=cache_conn,
    )

    print(f"\n--- Live Claude result ---\n{json.dumps(result, indent=2)}\n")
    assert "greig" in result
    assert "anthony" in result
    assert result["greig"]["position"]
    assert result["anthony"]["position"]
    assert any(e.get("stage") == "streaming" for e in streamed) or any(
        e.get("stage") == "cache" for e in streamed
    )
