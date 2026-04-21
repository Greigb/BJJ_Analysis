"""PATCH /api/rolls/:id/moments/:moment_id/annotations — append-only annotations."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from server.config import Settings, load_settings
from server.db import connect, get_moments, get_roll, insert_annotation

router = APIRouter(prefix="/api", tags=["annotations"])


class _AnnotationIn(BaseModel):
    body: str


class _AnnotationOut(BaseModel):
    id: str
    body: str
    created_at: int


@router.patch(
    "/rolls/{roll_id}/moments/{moment_id}/annotations",
    response_model=_AnnotationOut,
    status_code=status.HTTP_201_CREATED,
)
def add_annotation(
    roll_id: str,
    moment_id: str,
    payload: _AnnotationIn,
    settings: Settings = Depends(load_settings),
) -> _AnnotationOut:
    body = payload.body.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Annotation body must not be empty",
        )

    conn = connect(settings.db_path)
    try:
        if get_roll(conn, roll_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        moments = get_moments(conn, roll_id)
        if not any(m["id"] == moment_id for m in moments):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Moment not found"
            )
        row = insert_annotation(
            conn, moment_id=moment_id, body=body, created_at=int(time.time())
        )
    finally:
        conn.close()

    return _AnnotationOut(id=row["id"], body=row["body"], created_at=row["created_at"])
