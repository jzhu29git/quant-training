from __future__ import annotations

from fastapi import APIRouter

from app.services.model import get_model_overview, get_latest_picks

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("/latest")
def model_latest() -> dict[str, object]:
    return get_model_overview()


@router.get("/picks")
def model_picks(limit: int = 25) -> dict[str, object]:
    return get_latest_picks(limit=limit)
