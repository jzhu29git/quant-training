from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.batch import BatchControlError, _get_container_by_ref
from app.services.pipeline_control import (
    FULL_PIPELINE_STATE_FILE,
    PIPELINE_STEP_KEY_SCHEMA_VERSION,
    STEP_CONTROL_SPECS,
    start_step,
    stop_step,
)
from app.services.files import read_json

STOP_REQUESTED = False
CURRENT_STEP_KEY: str | None = None
CURRENT_STEP_LABEL: str | None = None
LOG_PATH: Path | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path() -> Path:
    return get_settings().run_dir / FULL_PIPELINE_STATE_FILE


def _write_state(**updates: Any) -> None:
    state = read_json(_state_path())
    state.update(updates)
    state["step_key_schema_version"] = PIPELINE_STEP_KEY_SCHEMA_VERSION
    state["updated_at"] = _now_iso()
    _state_path().write_text(__import__("json").dumps(state, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _log(message: str) -> None:
    line = f"[{_now_iso()}] {message}"
    print(line, flush=True)
    if LOG_PATH is not None:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _signal_handler(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    _log(f"Received signal {signum}, stopping full pipeline.")


def _wait_for_container_exit(container_ref: str, label: str) -> None:
    poll_seconds = 10
    while True:
        if STOP_REQUESTED:
            raise KeyboardInterrupt(f"Stop requested while waiting for {label}.")

        container = _get_container_by_ref(container_ref)
        if container is None:
            raise RuntimeError(f"{label} container {container_ref} disappeared before completion.")
        container.reload()
        state = container.attrs.get("State", {})
        if container.status != "running":
            if state.get("OOMKilled"):
                raise RuntimeError(f"{label} failed because the container was OOM killed.")
            exit_code = state.get("ExitCode")
            if exit_code not in (None, 0):
                raise RuntimeError(f"{label} exited with code {exit_code}.")
            _log(f"{label} completed in container {container.name}.")
            return

        _log(f"{label} still running in {container.name}.")
        time.sleep(poll_seconds)


def _run_step(step_key: str, label: str) -> None:
    global CURRENT_STEP_KEY, CURRENT_STEP_LABEL

    CURRENT_STEP_KEY = step_key
    CURRENT_STEP_LABEL = label
    _write_state(status="running", current_step_key=step_key, current_step_label=label, failed_step_key=None, error_message=None)
    _log(f"Starting {label}.")

    payload = start_step(step_key, allow_pipeline_run=True)
    container_ref = str(payload.get("container_id") or "")
    if not container_ref:
        raise RuntimeError(f"{label} did not return a container id.")

    _log(f"{label} launched in {payload.get('container_name')}.")
    _wait_for_container_exit(container_ref, label)

    state = read_json(_state_path())
    completed = list(state.get("completed_steps", []))
    if step_key not in completed:
        completed.append(step_key)
    _write_state(completed_steps=completed, current_step_key=None, current_step_label=None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()

    global LOG_PATH
    settings = get_settings()
    LOG_PATH = settings.logs_dir / f"full_pipeline_{args.timestamp}.log"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings.run_dir.mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    _write_state(status="running", started_at=_now_iso(), finished_at=None, completed_steps=[], failed_step_key=None, error_message=None)
    _log("Daily pipeline orchestration booted.")

    ordered_steps = [
        ("step1", "Step 1 Data Prepare"),
        ("step2", STEP_CONTROL_SPECS["step2"].label),
        ("step3", STEP_CONTROL_SPECS["step3"].label),
        ("step4", STEP_CONTROL_SPECS["step4"].label),
    ]

    try:
        for step_key, label in ordered_steps:
            _run_step(step_key, label)

        _write_state(status="completed", finished_at=_now_iso(), current_step_key=None, current_step_label=None)
        _log("Daily pipeline completed successfully.")
        return 0
    except KeyboardInterrupt:
        if CURRENT_STEP_KEY:
            try:
                stop_step(CURRENT_STEP_KEY)
            except BatchControlError:
                pass
        _write_state(
            status="stopped",
            finished_at=_now_iso(),
            current_step_key=None,
            current_step_label=None,
            error_message="Stopped before the pipeline finished.",
        )
        _log("Daily pipeline stopped.")
        return 1
    except Exception as exc:
        if CURRENT_STEP_KEY:
            try:
                stop_step(CURRENT_STEP_KEY)
            except BatchControlError:
                pass
        _write_state(
            status="failed",
            finished_at=_now_iso(),
            failed_step_key=CURRENT_STEP_KEY,
            current_step_key=None,
            current_step_label=None,
            error_message=str(exc),
        )
        _log(f"Daily pipeline failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
