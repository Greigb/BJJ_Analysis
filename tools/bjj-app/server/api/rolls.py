"""GET /api/rolls — list roll summaries from the Obsidian vault."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from server.analysis.vault import RollSummary, list_rolls
from server.config import Settings, load_settings


class RollSummaryOut(BaseModel):
    """HTTP-exposed shape. Intentionally excludes `path` (filesystem leak)."""

    id: str
    title: str
    date: str
    partner: str | None
    duration: str | None
    result: str | None

    @classmethod
    def from_domain(cls, r: RollSummary) -> "RollSummaryOut":
        return cls(
            id=r.id,
            title=r.title,
            date=r.date,
            partner=r.partner,
            duration=r.duration,
            result=r.result,
        )


router = APIRouter(prefix="/api", tags=["rolls"])


@router.get("/rolls", response_model=list[RollSummaryOut])
def get_rolls(settings: Settings = Depends(load_settings)) -> list[RollSummaryOut]:
    return [RollSummaryOut.from_domain(r) for r in list_rolls(settings.vault_root)]
