from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.batch import BatchControlError
from app.services.data import get_pipeline_summary
from app.services.files import read_json
from app.services.pipeline_control import get_pipeline_run_status, start_pipeline_run
from app.services.source_readiness import get_china_market_data_readiness

_LOCK = threading.Lock()
_STOP_EVENT: threading.Event | None = None
_THREAD: threading.Thread | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path() -> Path:
    return get_settings().pipeline_auto_run_state_path


def _read_state() -> dict[str, Any]:
    return read_json(_state_path())


def _write_state(payload: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _schedule_parts(raw_value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = raw_value.strip().split(":", maxsplit=1)
        hour = min(max(int(hour_text), 0), 23)
        minute = min(max(int(minute_text), 0), 59)
        return hour, minute
    except (AttributeError, TypeError, ValueError):
        return 18, 0


def _local_now() -> datetime:
    settings = get_settings()
    try:
        tz = ZoneInfo(settings.pipeline_auto_run_timezone)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    return datetime.now(timezone.utc).astimezone(tz)


def _latest_score_date() -> str | None:
    snapshot = get_pipeline_summary().get("inference_scores") or {}
    date_max = snapshot.get("date_max")
    if not date_max:
        return None
    return str(date_max)[:10]


def _maybe_start_pipeline() -> None:
    settings = get_settings()
    state = _read_state()
    local_now = _local_now()
    scheduled_hour, scheduled_minute = _schedule_parts(settings.pipeline_auto_run_time)
    local_date = local_now.date().isoformat()

    if local_now.weekday() >= 5:
        return
    if (local_now.hour, local_now.minute) < (scheduled_hour, scheduled_minute):
        return
    if state.get("last_trigger_local_date") == local_date:
        return

    readiness = get_china_market_data_readiness(local_date=local_date)
    checked_state = {
        **state,
        "last_checked_at": _now_iso(),
        "last_checked_local_date": local_date,
        "last_checked_timezone": settings.pipeline_auto_run_timezone,
        "last_readiness": readiness,
        "last_trigger_scheduled_time": settings.pipeline_auto_run_time,
    }
    expected_trade_date = readiness.get("expected_trade_date")

    if not readiness.get("is_trading_day"):
        checked_state["last_skipped_local_date"] = local_date
        checked_state["last_skip_reason"] = readiness.get("reason") or "non_trading_day"
        _write_state(checked_state)
        return

    if state.get("last_trigger_trade_date") == expected_trade_date:
        return

    if expected_trade_date and _latest_score_date() == expected_trade_date:
        _write_state(
            {
                **checked_state,
                "last_skipped_local_date": local_date,
                "last_skip_reason": "scores_already_current",
            }
        )
        return

    if not readiness.get("ready"):
        _write_state(
            {
                **checked_state,
                "last_skipped_local_date": local_date,
                "last_skip_reason": readiness.get("reason") or "market_data_not_ready",
            }
        )
        return

    pipeline_status = get_pipeline_run_status()
    if pipeline_status.get("is_running"):
        return

    next_state = {
        **checked_state,
        "last_trigger_local_date": local_date,
        "last_trigger_trade_date": expected_trade_date,
        "last_trigger_timezone": settings.pipeline_auto_run_timezone,
    }
    try:
        result = start_pipeline_run()
        next_state["last_triggered_at"] = _now_iso()
        next_state["last_result"] = {
            "ok": bool(result.get("ok")),
            "code": result.get("code"),
            "message": result.get("message"),
            "container_name": result.get("container_name"),
        }
    except BatchControlError as exc:
        next_state["last_triggered_at"] = _now_iso()
        next_state["last_result"] = {
            "ok": False,
            "code": exc.code,
            "message": exc.message,
        }
    _write_state(next_state)


def _run_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            _maybe_start_pipeline()
        except Exception as exc:
            state = _read_state()
            _write_state(
                {
                    **state,
                    "last_checked_at": _now_iso(),
                    "last_error_at": _now_iso(),
                    "last_error": str(exc),
                }
            )
        stop_event.wait(get_settings().pipeline_auto_run_poll_seconds)


def start_auto_pipeline_scheduler() -> None:
    settings = get_settings()
    if not settings.pipeline_auto_run_enabled:
        return

    global _STOP_EVENT, _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP_EVENT = threading.Event()
        _THREAD = threading.Thread(
            target=_run_loop,
            args=(_STOP_EVENT,),
            name="pipeline-auto-run",
            daemon=True,
        )
        _THREAD.start()


def stop_auto_pipeline_scheduler() -> None:
    global _STOP_EVENT, _THREAD
    with _LOCK:
        if _STOP_EVENT is not None:
            _STOP_EVENT.set()
        if _THREAD is not None and _THREAD.is_alive():
            _THREAD.join(timeout=2)
        _STOP_EVENT = None
        _THREAD = None
