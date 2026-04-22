"""POST /api/rolls/:id/export-pdf — render and deliver the match report PDF."""
from __future__ import annotations

import json as _json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status

from server.analysis.vault_writer import (
    ConflictError,
    publish as vault_publish,
    update_report_section,
)
from server.config import Settings, load_settings
from server.db import connect, get_roll, get_sections_by_roll
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
    overwrite: int = 0,
    settings: Settings = Depends(load_settings),
) -> Response:
    force = bool(overwrite)

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
        section_rows = [dict(s) for s in get_sections_by_roll(conn, roll_id)]
    finally:
        conn.close()

    generated_at = datetime.now(timezone.utc)
    context = build_report_context(
        roll=dict(roll_row),
        scores=scores_payload,
        sections=section_rows,
        generated_at=generated_at,
    )

    try:
        pdf_bytes = render_report_pdf(context)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PDF rendering failed: {exc}",
        )

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

    pdf_dir: Path = settings.project_root / "assets" / roll_id
    pdf_dir.mkdir(parents=True, exist_ok=True)
    final_path = pdf_dir / "report.pdf"
    tmp_path = pdf_dir / "report.pdf.tmp"
    tmp_path.write_bytes(pdf_bytes)
    os.replace(tmp_path, final_path)

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
