"""Rolls API — list summaries, create (upload) a new roll."""
from __future__ import annotations

import shutil
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from server.analysis.vault import RollSummary, list_rolls
from server.analysis.video import read_duration
from server.config import Settings, load_settings
from server.db import connect, create_roll, get_analyses, get_moments, get_roll


class RollSummaryOut(BaseModel):
    """Compact shape for the home page roll list."""

    id: str
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None

    @classmethod
    def from_vault(cls, r: RollSummary) -> "RollSummaryOut":
        return cls(
            id=r.id,
            title=r.title,
            date=r.date,
            partner=r.partner,
            duration=r.duration,
            result=r.result,
        )


class AnalysisOut(BaseModel):
    id: str
    player: str
    position_id: str
    confidence: float | None
    description: str | None
    coach_tip: str | None


class MomentOut(BaseModel):
    id: str
    frame_idx: int
    timestamp_s: float
    pose_delta: float | None
    analyses: list[AnalysisOut] = []


class RollDetailOut(BaseModel):
    """Full roll shape used by POST /api/rolls response and GET /api/rolls/:id."""

    id: str
    title: str
    date: str
    partner: str | None
    duration_s: float | None
    result: str
    video_url: str
    moments: list[MomentOut] = []


router = APIRouter(prefix="/api", tags=["rolls"])


@router.get("/rolls", response_model=list[RollSummaryOut])
def get_rolls(settings: Settings = Depends(load_settings)) -> list[RollSummaryOut]:
    return [RollSummaryOut.from_vault(r) for r in list_rolls(settings.vault_root)]


@router.post(
    "/rolls",
    response_model=RollDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_roll(
    video: UploadFile = File(...),
    title: str = Form(...),
    date: str = Form(...),
    partner: str | None = Form(default=None),
    settings: Settings = Depends(load_settings),
) -> RollDetailOut:
    # roll_id is a 32-char hex string (no hyphens). Server-generated, never user input.
    roll_id = uuid.uuid4().hex
    roll_dir = settings.project_root / "assets" / roll_id
    roll_dir.mkdir(parents=True, exist_ok=False)
    video_path = roll_dir / "source.mp4"

    try:
        # Stream to disk so large uploads don't hold memory.
        with video_path.open("wb") as out:
            shutil.copyfileobj(video.file, out)

        # Validate it's a real video before we persist a row.
        try:
            duration_s = read_duration(video_path)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Uploaded file is not a readable video: {exc}",
            ) from exc

        relative_video_path = f"assets/{roll_id}/source.mp4"
        conn = connect(settings.db_path)
        try:
            create_roll(
                conn,
                id=roll_id,
                title=title,
                date=date,
                video_path=relative_video_path,
                duration_s=duration_s,
                partner=partner,
                result="unknown",
                created_at=int(time.time()),
            )
        finally:
            conn.close()
    except Exception:
        # Any failure after mkdir — bad upload, DB error, disk-full — must not
        # leave an orphan roll_dir behind.
        shutil.rmtree(roll_dir, ignore_errors=True)
        raise

    return RollDetailOut(
        id=roll_id,
        title=title,
        date=date,
        partner=partner,
        duration_s=duration_s,
        result="unknown",
        video_url=f"/assets/{roll_id}/source.mp4",
        moments=[],
    )


@router.get("/rolls/{roll_id}", response_model=RollDetailOut)
def get_roll_detail(
    roll_id: str,
    settings: Settings = Depends(load_settings),
) -> RollDetailOut:
    conn = connect(settings.db_path)
    try:
        row = get_roll(conn, roll_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        moment_rows = get_moments(conn, roll_id)
        analyses_by_moment: dict[str, list] = {
            m["id"]: get_analyses(conn, m["id"]) for m in moment_rows
        }
    finally:
        conn.close()

    moments_out = [
        MomentOut(
            id=m["id"],
            frame_idx=m["frame_idx"],
            timestamp_s=m["timestamp_s"],
            pose_delta=m["pose_delta"],
            analyses=[
                AnalysisOut(
                    id=a["id"],
                    player=a["player"],
                    position_id=a["position_id"],
                    confidence=a["confidence"],
                    description=a["description"],
                    coach_tip=a["coach_tip"],
                )
                for a in analyses_by_moment[m["id"]]
            ],
        )
        for m in moment_rows
    ]

    return RollDetailOut(
        id=row["id"],
        title=row["title"],
        date=row["date"],
        partner=row["partner"],
        duration_s=row["duration_s"],
        result=row["result"],
        video_url=f"/{row['video_path']}",
        moments=moments_out,
    )
