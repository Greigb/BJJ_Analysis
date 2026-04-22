"""Rolls API — list summaries, create (upload) a new roll."""
from __future__ import annotations

import shutil
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel

from server.analysis.summarise import compute_distribution
from server.analysis.vault import RollSummary, list_rolls
from server.analysis.video import read_duration
from server.config import Settings, load_settings
from server.db import (
    connect,
    create_roll,
    delete_section_and_moments,
    get_analyses,
    get_moments,
    get_roll,
    get_sections_by_roll,
)


class RollSummaryOut(BaseModel):
    """Compact shape for the home page roll list."""

    id: str
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None
    roll_id: str | None = None

    @classmethod
    def from_vault(cls, r: RollSummary) -> "RollSummaryOut":
        return cls(
            id=r.id,
            title=r.title,
            date=r.date,
            partner=r.partner,
            duration=r.duration,
            result=r.result,
            roll_id=r.roll_id,
        )


class AnalysisOut(BaseModel):
    id: str
    player: str
    position_id: str
    confidence: float | None
    description: str | None
    coach_tip: str | None


class AnnotationOut(BaseModel):
    id: str
    body: str
    created_at: int


class SectionOut(BaseModel):
    id: str
    start_s: float
    end_s: float
    sample_interval_s: float


class MomentOut(BaseModel):
    id: str
    frame_idx: int
    timestamp_s: float
    pose_delta: float | None
    section_id: str | None = None
    analyses: list[AnalysisOut] = []
    annotations: list[AnnotationOut] = []


class RollDetailOut(BaseModel):
    """Full roll shape used by POST /api/rolls response and GET /api/rolls/:id."""

    id: str
    title: str
    date: str
    partner: str | None
    duration_s: float | None
    result: str
    video_url: str
    vault_path: str | None = None
    vault_published_at: int | None = None
    player_a_name: str = "Player A"
    player_b_name: str = "Player B"
    finalised_at: int | None = None
    scores: dict | None = None
    distribution: dict | None = None
    moments: list[MomentOut] = []
    sections: list[SectionOut] = []


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
    player_a_name: str = Form(default="Player A"),
    player_b_name: str = Form(default="Player B"),
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
                player_a_name=player_a_name,
                player_b_name=player_b_name,
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
        vault_path=None,
        vault_published_at=None,
        player_a_name=player_a_name,
        player_b_name=player_b_name,
        finalised_at=None,
        scores=None,
        distribution=None,
        moments=[],
        sections=[],
    )


@router.get("/rolls/{roll_id}", response_model=RollDetailOut)
def get_roll_detail(
    roll_id: str,
    request: Request,
    settings: Settings = Depends(load_settings),
) -> RollDetailOut:
    import json as _json

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
        # Annotations are now section-scoped (M9b); moments carry no annotations.
        annotations_by_moment: dict[str, list] = {m["id"]: [] for m in moment_rows}
        section_rows = get_sections_by_roll(conn, roll_id)
    finally:
        conn.close()

    moments_out = [
        MomentOut(
            id=m["id"],
            frame_idx=m["frame_idx"],
            timestamp_s=m["timestamp_s"],
            pose_delta=m["pose_delta"],
            section_id=m["section_id"],
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
            annotations=[
                AnnotationOut(id=an["id"], body=an["body"], created_at=an["created_at"])
                for an in annotations_by_moment[m["id"]]
            ],
        )
        for m in moment_rows
    ]

    scores = None
    if row["scores_json"]:
        try:
            scores = _json.loads(row["scores_json"])
        except Exception:
            scores = None

    distribution = None
    taxonomy = getattr(request.app.state, "taxonomy", None)
    if taxonomy is not None and any(analyses_by_moment[m["id"]] for m in moment_rows):
        position_to_category = {p["id"]: p["category"] for p in taxonomy.get("positions", [])}
        flat_analyses: list[dict] = []
        for m in moment_rows:
            for a in analyses_by_moment[m["id"]]:
                flat_analyses.append({
                    "position_id": a["position_id"],
                    "player": a["player"],
                    "timestamp_s": m["timestamp_s"],
                    "category": position_to_category.get(a["position_id"], "scramble"),
                })
        distribution = compute_distribution(flat_analyses, taxonomy.get("categories", []))

    return RollDetailOut(
        id=row["id"],
        title=row["title"],
        date=row["date"],
        partner=row["partner"],
        duration_s=row["duration_s"],
        result=row["result"],
        video_url=f"/{row['video_path']}",
        vault_path=row["vault_path"],
        vault_published_at=row["vault_published_at"],
        player_a_name=row["player_a_name"] or "Player A",
        player_b_name=row["player_b_name"] or "Player B",
        finalised_at=row["finalised_at"],
        scores=scores,
        distribution=distribution,
        moments=moments_out,
        sections=[
            SectionOut(
                id=s["id"],
                start_s=s["start_s"],
                end_s=s["end_s"],
                sample_interval_s=s["sample_interval_s"],
            )
            for s in section_rows
        ],
    )


@router.delete(
    "/rolls/{roll_id}/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_section(
    roll_id: str,
    section_id: str,
    settings: Settings = Depends(load_settings),
) -> Response:
    conn = connect(settings.db_path)
    try:
        if get_roll(conn, roll_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found"
            )
        sections = get_sections_by_roll(conn, roll_id)
        if not any(s["id"] == section_id for s in sections):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
            )
        frames_dir = settings.project_root / "assets" / roll_id / "frames"
        delete_section_and_moments(
            conn, section_id=section_id, frames_dir=frames_dir
        )
    finally:
        conn.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
