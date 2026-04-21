"""Graph API — taxonomy skeleton, per-roll path arrays, vault position markdown."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

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
