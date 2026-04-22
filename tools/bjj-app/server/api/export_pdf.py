"""POST /api/rolls/:id/export-pdf — render and deliver the match report PDF."""
from __future__ import annotations

import json as _json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from server.analysis.vault_writer import (
    ConflictError,
    publish as vault_publish,
    update_report_section,
)
from server.config import Settings, load_settings
from server.db import (
    connect,
    get_analyses,
    get_moments,
    get_roll,
)
from server.export.pdf import (
    build_report_context,
    render_report_pdf,
    render_report_section_body,
    slugify_report_filename,
)

router = APIRouter(prefix="/api", tags=["export_pdf"])


@router.post("/rolls/{roll_id}/export-pdf")
def export_roll_pdf(
    roll_id: str,
    request: Request,
    overwrite: int = 0,
    settings: Settings = Depends(load_settings),
) -> Response:
    force = bool(overwrite)
    taxonomy = getattr(request.app.state, "taxonomy", None) or {"categories": [], "positions": []}

    # ---------- 1. Load roll + validate ----------
    conn = connect(settings.db_path)
    try:
        roll_row = get_roll(conn, roll_id)
        if roll_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found."
            )
        if roll_row["scores_json"] is None or roll_row["finalised_at"] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Roll must be finalised before export.",
            )

        scores_payload = _json.loads(roll_row["scores_json"])
        moment_rows = [dict(m) for m in get_moments(conn, roll_id)]
        position_to_category = {p["id"]: p["category"] for p in taxonomy.get("positions", [])}

        # One pass: collect analyses per moment, build flat_analyses, derive category.
        analyses_by_moment: dict[str, list[dict]] = {}
        flat_analyses: list[dict] = []
        for m in moment_rows:
            rows = [dict(a) for a in get_analyses(conn, m["id"])]
            analyses_by_moment[m["id"]] = rows
            for a in rows:
                flat_analyses.append({
                    "position_id": a["position_id"],
                    "player": a["player"],
                    "timestamp_s": m["timestamp_s"],
                    "category": position_to_category.get(a["position_id"], "scramble"),
                })

        # TODO(Task 12): compute_distribution removed in M9b; export-pdf to be rewritten.
        distribution: dict = {"timeline": [], "counts": {}, "percentages": {}}

        moments_with_cat = [
            {
                "id": m["id"],
                "frame_idx": m["frame_idx"],
                "timestamp_s": m["timestamp_s"],
                "category": (
                    position_to_category.get(
                        analyses_by_moment[m["id"]][0]["position_id"], "scramble"
                    )
                    if analyses_by_moment[m["id"]]
                    else "scramble"
                ),
            }
            for m in moment_rows
        ]
    finally:
        conn.close()

    # ---------- 2. Build context + render PDF in memory ----------
    generated_at = datetime.now(timezone.utc)
    context = build_report_context(
        roll=dict(roll_row),
        scores=scores_payload,
        distribution=distribution,
        moments=moments_with_cat,
        taxonomy=taxonomy,
        generated_at=generated_at,
    )

    try:
        pdf_bytes = render_report_pdf(context)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PDF rendering failed: {exc}",
        )

    # ---------- 3. Ensure vault is up to date (publish), then update Report ----------
    conflict_headers: dict[str, str] = {}
    report_body = render_report_section_body(roll_id=roll_id, generated_at=generated_at)
    conn = connect(settings.db_path)
    try:
        try:
            vault_publish(
                conn,
                roll_id=roll_id,
                vault_root=settings.vault_root,
                force=force,
                taxonomy=taxonomy,
            )
        except ConflictError:
            conflict_headers["X-Conflict"] = "report"

        if "X-Conflict" not in conflict_headers:
            try:
                update_report_section(
                    conn,
                    roll_id=roll_id,
                    vault_root=settings.vault_root,
                    body=report_body,
                    force=force,
                )
            except ConflictError:
                conflict_headers["X-Conflict"] = "report"
    finally:
        conn.close()

    # ---------- 4. Atomic-write the PDF file regardless of conflict state ----------
    pdf_dir: Path = settings.project_root / "assets" / roll_id
    pdf_dir.mkdir(parents=True, exist_ok=True)
    final_path = pdf_dir / "report.pdf"
    tmp_path = pdf_dir / "report.pdf.tmp"
    tmp_path.write_bytes(pdf_bytes)
    os.replace(tmp_path, final_path)

    # ---------- 5. Return PDF bytes ----------
    filename = slugify_report_filename(roll_row["title"], roll_row["date"])
    status_code = status.HTTP_409_CONFLICT if conflict_headers else status.HTTP_200_OK
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        **conflict_headers,
    }
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        status_code=status_code,
        headers=headers,
    )
