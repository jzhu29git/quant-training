from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.services.batch import BatchControlError, start_batch, stop_batch
from app.services.paper_control import start_paper_trading_daemon, stop_paper_trading_daemon
from app.services.pipeline_control import start_pipeline_run, start_step, stop_pipeline_run, stop_step

router = APIRouter(prefix="/api/control", tags=["control"])


def _require_admin_key(x_panel_admin_key: str | None = Header(default=None)) -> None:
    expected = get_settings().panel_admin_key
    if not expected or x_panel_admin_key != expected:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Admin control key rejected."})


@router.post("/batch/start")
def batch_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_batch()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/batch/stop")
def batch_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_batch()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/pipeline/start")
def pipeline_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_pipeline_run()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/pipeline/stop")
def pipeline_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_pipeline_run()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/step/{step_key}/start")
def step_start(
    step_key: str,
    profile: str | None = None,
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_step(step_key, profile_name=profile)
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/step/{step_key}/stop")
def step_stop(step_key: str, x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_step(step_key)
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/paper/start")
def paper_start(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return start_paper_trading_daemon()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/paper/stop")
def paper_stop(x_panel_admin_key: str | None = Header(default=None)) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return stop_paper_trading_daemon()
    except BatchControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
