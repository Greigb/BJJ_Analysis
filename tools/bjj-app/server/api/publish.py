"""POST /api/rolls/:id/publish — publish annotations to the vault markdown."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.analysis.vault_writer import ConflictError, publish as vault_publish
from server.config import Settings, load_settings
from server.db import connect

router = APIRouter(prefix="/api", tags=["publish"])


class _PublishIn(BaseModel):
    force: bool = False


class _PublishOut(BaseModel):
    vault_path: str
    your_notes_hash: str
    vault_published_at: int


@router.post(
    "/rolls/{roll_id}/publish",
    response_model=_PublishOut,
)
def publish_roll(
    roll_id: str,
    payload: _PublishIn,
    settings: Settings = Depends(load_settings),
):
    conn = connect(settings.db_path)
    try:
        try:
            result = vault_publish(
                conn,
                roll_id=roll_id,
                vault_root=settings.vault_root,
                force=payload.force,
            )
        except LookupError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        except ConflictError as exc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "Your Notes was edited in Obsidian since last publish",
                    "current_hash": exc.current_hash,
                    "stored_hash": exc.stored_hash,
                },
            )
    finally:
        conn.close()

    return _PublishOut(
        vault_path=result.vault_path,
        your_notes_hash=result.your_notes_hash,
        vault_published_at=result.vault_published_at,
    )
