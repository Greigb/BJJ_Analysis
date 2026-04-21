"""Graph API — taxonomy skeleton, per-roll path arrays, vault position markdown."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from server.config import Settings, load_settings
from server.db import connect, get_analyses, get_moments, get_roll

router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/graph")
def get_graph(request: Request) -> dict:
    """Return the cached taxonomy (categories + positions + transitions + tints)."""
    return request.app.state.taxonomy


@router.get("/vault/position/{position_id}")
def get_vault_position(position_id: str, request: Request) -> dict:
    """Return markdown for a position's vault note. 404 if no matching file."""
    from server.analysis.positions_vault import get_position

    entry = get_position(request.app.state.positions_index, position_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No vault note for this position",
        )
    return dict(entry)


@router.get("/graph/paths/{roll_id}")
def get_graph_paths(
    roll_id: str,
    settings: Settings = Depends(load_settings),
) -> dict:
    """Return per-roll sparse paths for both players."""
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )

        moment_rows = get_moments(conn, roll_id)
        a: list[dict] = []
        b: list[dict] = []
        for m in moment_rows:
            for an in get_analyses(conn, m["id"]):
                entry = {
                    "timestamp_s": m["timestamp_s"],
                    "position_id": an["position_id"],
                    "moment_id": m["id"],
                }
                if an["player"] == "a":
                    a.append(entry)
                elif an["player"] == "b":
                    b.append(entry)

        return {
            "duration_s": row["duration_s"],
            "player_a_name": row["player_a_name"] or "Player A",
            "player_b_name": row["player_b_name"] or "Player B",
            "paths": {"a": a, "b": b},
        }
    finally:
        conn.close()
