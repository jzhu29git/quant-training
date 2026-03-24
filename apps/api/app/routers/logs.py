from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.batch import get_batch_logs

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/batch")
def batch_logs(tail: int = Query(default=120, ge=20, le=500)) -> dict[str, object]:
    return get_batch_logs(lines=tail)
