from __future__ import annotations

from fastapi import APIRouter

from app.services.batch import get_batch_status
from app.services.pipeline_control import get_pipeline_run_status
from app.services.workflow import get_workflow_status

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("/batch")
def batch_status() -> dict[str, object]:
    return get_batch_status()


@router.get("/workflow")
def workflow_status() -> dict[str, object]:
    return get_workflow_status()


@router.get("/pipeline")
def pipeline_status() -> dict[str, object]:
    return get_pipeline_run_status()
