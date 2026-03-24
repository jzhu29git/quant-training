from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docker.errors import DockerException, ImageNotFound, NotFound

from app.config import get_settings
from app.services.batch import BatchControlError, _docker_client, _get_container_by_ref, start_batch, stop_batch
from app.services.files import read_json, run_command, tail_file
from app.services.model_profiles import resolve_model_profile

PIPELINE_LOG_TAIL = 40
ORCHESTRATOR_IMAGE = "aistockcn-panel-api:latest"
DATA_PREP_IMAGE = "aistockcn-data-prep:latest"
PIPELINE_STEP_KEY_SCHEMA_VERSION = 2
LEGACY_STEP1_ALIAS = "step12"
LEGACY_PIPELINE_STEP_KEY_MAP = {
    "step12": "step1",
    "step3": "step2",
    "step4": "step3",
    "step5": "step4",
    "step6": "step5",
}


@dataclass(frozen=True)
class StepControlSpec:
    key: str
    label: str
    step_numbers: tuple[int, ...]
    pid_file_name: str
    log_prefix: str
    container_prefix: str
    command_markers: tuple[str, ...]
    entrypoint: str
    command: tuple[str, ...]


STEP_CONTROL_SPECS: dict[str, StepControlSpec] = {
    "step2": StepControlSpec(
        key="step2",
        label="Step 2 Feature Engineering",
        step_numbers=(2,),
        pid_file_name="step3_feature_engineering.pid",
        log_prefix="step3_feature_engineering",
        container_prefix="aistockcn-step3-feature-engineering-",
        command_markers=("feature_engineering.py",),
        entrypoint="python",
        command=(
            "feature_engineering.py",
            "--data-dir",
            "quant_data",
            "--output",
            "quant_data/ml_features_ready.parquet",
            "--limit",
            "0",
            "--label-threshold",
            "0.02",
            "--label-horizon",
            "5",
            "--profile-name",
            "short_5d",
        ),
    ),
    "step3": StepControlSpec(
        key="step3",
        label="Step 3 Inference Features",
        step_numbers=(3,),
        pid_file_name="step4_inference_features.pid",
        log_prefix="step4_inference_features",
        container_prefix="aistockcn-step4-inference-features-",
        command_markers=("build_inference_features.py",),
        entrypoint="python",
        command=(
            "build_inference_features.py",
            "--data-dir",
            "quant_data",
            "--output",
            "quant_data/inference_features_latest.parquet",
            "--limit",
            "0",
        ),
    ),
    "step4": StepControlSpec(
        key="step4",
        label="Step 4 Train And Score",
        step_numbers=(4,),
        pid_file_name="step5_train_score.pid",
        log_prefix="step5_train_score",
        container_prefix="aistockcn-step5-train-score-",
        command_markers=("train_lightgbm.py",),
        entrypoint="python",
        command=(
            "train_lightgbm.py",
            "--train-path",
            "quant_data/ml_features_ready.parquet",
            "--inference-path",
            "quant_data/inference_features_latest.parquet",
            "--model-dir",
            "quant_data/models",
            "--valid-days",
            "60",
            "--threshold",
            "0.5",
            "--top-k",
            "20",
        ),
    ),
    "step5": StepControlSpec(
        key="step5",
        label="Backtest",
        step_numbers=(5,),
        pid_file_name="step6_backtest.pid",
        log_prefix="step6_backtest",
        container_prefix="aistockcn-step6-backtest-",
        command_markers=("backtest_profile_runner.py",),
        entrypoint="python",
        command=(
            "backtest_profile_runner.py",
            "--profile",
            "short_5d",
            "--sync-latest",
        ),
    ),
}

FULL_PIPELINE_PID_FILE = "full_pipeline.pid"
FULL_PIPELINE_STATE_FILE = "full_pipeline_state.json"
FULL_PIPELINE_LOG_PREFIX = "full_pipeline"
FULL_PIPELINE_CONTAINER_PREFIX = "aistockcn-full-pipeline-"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pid_file(path_name: str) -> Path:
    return get_settings().run_dir / path_name


def _state_file(path_name: str) -> Path:
    return get_settings().run_dir / path_name


def _latest_matching_log_file(logs_dir: Path, pattern: str) -> Path | None:
    candidates = sorted(logs_dir.glob(pattern), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _canonical_request_step_key(step_key: str) -> str:
    normalized = step_key.strip().lower()
    if normalized == LEGACY_STEP1_ALIAS:
        return "step1"
    return normalized


def _normalize_state_step_key(step_key: Any, *, schema_version: Any) -> str | None:
    if not isinstance(step_key, str):
        return None
    normalized = step_key.strip().lower()
    if not normalized:
        return None
    if schema_version == PIPELINE_STEP_KEY_SCHEMA_VERSION:
        return normalized
    return LEGACY_PIPELINE_STEP_KEY_MAP.get(normalized, normalized)


def _normalize_state_step_keys(step_keys: Any, *, schema_version: Any) -> list[str]:
    normalized: list[str] = []
    if not isinstance(step_keys, list):
        return normalized
    for value in step_keys:
        canonical = _normalize_state_step_key(value, schema_version=schema_version)
        if canonical and canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _container_command(container: Any) -> str:
    config = container.attrs.get("Config", {})
    parts: list[str] = []
    for value in [config.get("Entrypoint"), config.get("Cmd")]:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(part for part in parts if part)


def _find_latest_matching_container(
    *,
    pid_file: Path | None = None,
    name_prefixes: list[str] | None = None,
    command_markers: list[str] | None = None,
) -> Any | None:
    if pid_file is not None and pid_file.exists():
        container_ref = pid_file.read_text(encoding="utf-8").strip()
        if container_ref:
            container = _get_container_by_ref(container_ref)
            if container is not None:
                return container

    client = _docker_client()
    if client is None:
        return None

    try:
        containers = client.containers.list(all=True)
    except DockerException:
        return None

    matched: list[Any] = []
    for container in containers:
        name = container.name
        if name_prefixes and any(name.startswith(prefix) for prefix in name_prefixes):
            matched.append(container)
            continue
        if command_markers:
            command = _container_command(container)
            if any(marker in command for marker in command_markers):
                matched.append(container)
    if not matched:
        return None
    return sorted(matched, key=lambda item: item.attrs.get("Created", ""))[-1]


def _snapshot_container(container: Any | None) -> dict[str, Any]:
    if container is None:
        return {
            "container_id": None,
            "container_name": None,
            "container_status": None,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "oom_killed": False,
            "is_running": False,
        }

    state = container.attrs.get("State", {})
    return {
        "container_id": container.id,
        "container_name": container.name,
        "container_status": container.status,
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": bool(state.get("OOMKilled")),
        "is_running": container.status == "running",
    }


def _tail_container_logs(container_name: str, *, lines: int) -> list[str]:
    client = _docker_client()
    if client is not None:
        try:
            container = client.containers.get(container_name)
            log_bytes = container.logs(tail=lines)
            return log_bytes.decode("utf-8", errors="replace").splitlines()
        except (DockerException, NotFound):
            pass

    ok, output = run_command(["docker", "logs", "--tail", str(lines), container_name], timeout=10)
    return output.splitlines() if ok and output else []


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_log_stub(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assert_no_full_pipeline_run() -> None:
    pipeline_status = get_pipeline_run_status()
    if pipeline_status["is_running"]:
        raise BatchControlError(
            "pipeline_running",
            "Daily pipeline is running. Stop it before starting a single step.",
            status_code=409,
        )


def _ensure_image(image: str) -> None:
    client = _docker_client()
    if client is None:
        raise BatchControlError("docker_unavailable", "Docker socket is unavailable from the API container.", status_code=503)
    try:
        client.images.get(image)
    except ImageNotFound as exc:
        raise BatchControlError("image_missing", f"Image {image} is missing.", status_code=409) from exc
    except DockerException as exc:
        raise BatchControlError("docker_unavailable", f"Unable to inspect Docker image {image}.", status_code=503) from exc


def _step_container(spec: StepControlSpec) -> Any | None:
    return _find_latest_matching_container(
        pid_file=_pid_file(spec.pid_file_name),
        name_prefixes=[spec.container_prefix],
        command_markers=list(spec.command_markers),
    )


def _step_running(spec: StepControlSpec) -> bool:
    container = _step_container(spec)
    return bool(container is not None and container.status == "running")


def _container_name(prefix: str) -> str:
    return f"{prefix}{_timestamp()}"


def _stop_logger_pid(path: Path) -> None:
    if not path.exists():
        return
    pid_value = path.read_text(encoding="utf-8").strip()
    if not pid_value:
        path.unlink(missing_ok=True)
        return
    ok, _ = run_command(["kill", "-TERM", pid_value], timeout=5)
    path.unlink(missing_ok=True)
    if ok:
        return


def _step_command(spec: StepControlSpec, *, profile_name: str | None = None) -> list[str]:
    if spec.key != "step5":
        return list(spec.command)

    profile = resolve_model_profile(profile_name)
    return [
        "backtest_profile_runner.py",
        "--profile",
        str(profile["name"]),
        "--sync-latest",
    ]


def start_step(step_key: str, *, allow_pipeline_run: bool = False, profile_name: str | None = None) -> dict[str, Any]:
    step_key = _canonical_request_step_key(step_key)
    if step_key == "step1":
        if not allow_pipeline_run:
            _assert_no_full_pipeline_run()
        result = start_batch()
        result["target"] = "step1"
        return result

    spec = STEP_CONTROL_SPECS.get(step_key)
    if spec is None:
        raise BatchControlError("invalid_step", f"Unsupported step key {step_key}.", status_code=404)

    if not allow_pipeline_run:
        _assert_no_full_pipeline_run()
    if _step_running(spec):
        active = _step_container(spec)
        raise BatchControlError("already_running", f"{spec.label} is already running in {active.name}.", status_code=409)

    _ensure_image(DATA_PREP_IMAGE)
    client = _docker_client()
    if client is None:
        raise BatchControlError("docker_unavailable", "Docker socket is unavailable from the API container.", status_code=503)

    settings = get_settings()
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    container_name = _container_name(spec.container_prefix)
    timestamp = _timestamp()
    log_file = settings.logs_dir / f"{spec.log_prefix}_{timestamp}.log"
    pid_file = _pid_file(spec.pid_file_name)
    logger_pid_file = _pid_file(spec.pid_file_name.replace(".pid", "_logger.pid"))
    command = _step_command(spec, profile_name=profile_name)
    profile = resolve_model_profile(profile_name) if step_key == "step5" else None

    try:
        container = client.containers.run(
            DATA_PREP_IMAGE,
            command=command,
            name=container_name,
            detach=True,
            entrypoint=spec.entrypoint,
            working_dir="/app",
            environment={"TZ": "UTC"},
            volumes={str(settings.host_project_root): {"bind": "/app", "mode": "rw"}},
        )
    except DockerException as exc:
        raise BatchControlError("start_failed", f"Failed to start {spec.label}: {exc}", status_code=500) from exc

    pid_file.write_text(f"{container.id}\n", encoding="utf-8")
    logger_pid_file.unlink(missing_ok=True)
    _write_log_stub(
        log_file,
        [
            f"{spec.label} started from control panel.",
            f"CONTAINER: {container.name}",
            f"CONTAINER_ID: {container.id}",
            f"ARGS: {spec.entrypoint} {' '.join(command)}",
            "LIVE_LOG_SOURCE: docker",
            f"STARTED_AT: {_now_iso()}",
        ],
    )

    return {
        "ok": True,
        "action": "start",
        "target": step_key,
        "code": "started",
        "message": (
            f"{spec.label} ({profile['label']}) started in {container.name}."
            if profile is not None
            else f"{spec.label} started in {container.name}."
        ),
        "container_id": container.id,
        "container_name": container.name,
        "log_file": str(log_file),
        "profile_name": profile["name"] if profile is not None else None,
        "profile_label": profile["label"] if profile is not None else None,
    }


def stop_step(step_key: str) -> dict[str, Any]:
    step_key = _canonical_request_step_key(step_key)
    if step_key == "step1":
        result = stop_batch()
        result["target"] = "step1"
        return result

    spec = STEP_CONTROL_SPECS.get(step_key)
    if spec is None:
        raise BatchControlError("invalid_step", f"Unsupported step key {step_key}.", status_code=404)

    container = _step_container(spec)
    if container is None:
        raise BatchControlError("not_found", f"No container record was found for {spec.label}.", status_code=404)
    if container.status != "running":
        raise BatchControlError("not_running", f"{spec.label} is not currently running.", status_code=409)

    try:
        container.stop(timeout=30)
        container.reload()
    except DockerException as exc:
        raise BatchControlError("stop_failed", f"Failed to stop {spec.label}: {exc}", status_code=500) from exc

    _stop_logger_pid(_pid_file(spec.pid_file_name.replace(".pid", "_logger.pid")))

    latest_log_file = _latest_matching_log_file(get_settings().logs_dir, f"{spec.log_prefix}_*.log")
    if latest_log_file is not None:
        with latest_log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"Stopped from control panel at {_now_iso()}\n")

    return {
        "ok": True,
        "action": "stop",
        "target": step_key,
        "code": "stopped",
        "message": f"{spec.label} has been stopped.",
        "container_id": container.id,
        "container_name": container.name,
        "status": container.status,
    }


def _full_pipeline_container() -> Any | None:
    return _find_latest_matching_container(
        pid_file=_pid_file(FULL_PIPELINE_PID_FILE),
        name_prefixes=[FULL_PIPELINE_CONTAINER_PREFIX],
        command_markers=["app.services.pipeline_runner"],
    )


def _full_pipeline_state() -> dict[str, Any]:
    return read_json(_state_file(FULL_PIPELINE_STATE_FILE))


def start_pipeline_run() -> dict[str, Any]:
    active = _full_pipeline_container()
    if active is not None and active.status == "running":
        raise BatchControlError("already_running", f"Daily pipeline is already running in {active.name}.", status_code=409)

    _ensure_image(ORCHESTRATOR_IMAGE)
    client = _docker_client()
    if client is None:
        raise BatchControlError("docker_unavailable", "Docker socket is unavailable from the API container.", status_code=503)

    settings = get_settings()
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _timestamp()
    log_file = settings.logs_dir / f"{FULL_PIPELINE_LOG_PREFIX}_{timestamp}.log"
    state_file = _state_file(FULL_PIPELINE_STATE_FILE)
    pid_file = _pid_file(FULL_PIPELINE_PID_FILE)
    container_name = _container_name(FULL_PIPELINE_CONTAINER_PREFIX)

    _write_json(
        state_file,
        {
            "status": "starting",
            "started_at": _now_iso(),
            "updated_at": _now_iso(),
            "finished_at": None,
            "step_key_schema_version": PIPELINE_STEP_KEY_SCHEMA_VERSION,
            "current_step_key": None,
            "current_step_label": None,
            "completed_steps": [],
            "failed_step_key": None,
            "error_message": None,
            "log_file": str(log_file),
            "container_name": container_name,
        },
    )
    _write_log_stub(
        log_file,
        [
            "Daily pipeline started from control panel.",
            f"REQUESTED_AT: {_now_iso()}",
            f"CONTAINER: {container_name}",
        ],
    )

    try:
        container = client.containers.run(
            ORCHESTRATOR_IMAGE,
            command=["python", "-m", "app.services.pipeline_runner", "--timestamp", timestamp],
            name=container_name,
            detach=True,
            working_dir="/app",
            environment={
                "PROJECT_ROOT": "/workspace",
                "HOST_PROJECT_ROOT": str(settings.host_project_root),
                "TZ": "UTC",
            },
            volumes={
                str(settings.host_project_root): {"bind": "/workspace", "mode": "rw"},
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            },
        )
    except DockerException as exc:
        raise BatchControlError("start_failed", f"Failed to start full pipeline orchestration: {exc}", status_code=500) from exc

    pid_file.write_text(f"{container.id}\n", encoding="utf-8")
    state = _full_pipeline_state()
    state["status"] = "running"
    state["container_id"] = container.id
    state["container_name"] = container.name
    state["updated_at"] = _now_iso()
    _write_json(state_file, state)

    return {
        "ok": True,
        "action": "start",
        "target": "pipeline",
        "code": "started",
        "message": f"Daily pipeline started in {container.name}.",
        "container_id": container.id,
        "container_name": container.name,
        "log_file": str(log_file),
    }


def stop_pipeline_run() -> dict[str, Any]:
    state = _full_pipeline_state()
    schema_version = state.get("step_key_schema_version")
    current_step_key = _normalize_state_step_key(state.get("current_step_key"), schema_version=schema_version)
    stop_result = None
    if current_step_key in {"step1", "step2", "step3", "step4", "step5"}:
        try:
            stop_result = stop_step(current_step_key)
        except BatchControlError:
            stop_result = None

    container = _full_pipeline_container()
    if container is None:
        raise BatchControlError("not_found", "No daily pipeline container record was found.", status_code=404)
    if container.status != "running":
        raise BatchControlError("not_running", f"Daily pipeline container {container.name} is not running.", status_code=409)

    try:
        container.stop(timeout=20)
        container.reload()
    except DockerException as exc:
        raise BatchControlError("stop_failed", f"Failed to stop full pipeline orchestration: {exc}", status_code=500) from exc

    latest_log_file = _latest_matching_log_file(get_settings().logs_dir, f"{FULL_PIPELINE_LOG_PREFIX}_*.log")
    if latest_log_file is not None:
        with latest_log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"Daily pipeline stopped from control panel at {_now_iso()}\n")

    state["status"] = "stopped"
    state["updated_at"] = _now_iso()
    state["finished_at"] = _now_iso()
    state["step_key_schema_version"] = PIPELINE_STEP_KEY_SCHEMA_VERSION
    if not state.get("error_message"):
        state["error_message"] = "Stopped manually from control panel."
    _write_json(_state_file(FULL_PIPELINE_STATE_FILE), state)

    return {
        "ok": True,
        "action": "stop",
        "target": "pipeline",
        "code": "stopped",
        "message": f"Daily pipeline container {container.name} has been stopped.",
        "container_id": container.id,
        "container_name": container.name,
        "status": container.status,
        "stopped_step": stop_result,
    }


def get_pipeline_run_status() -> dict[str, Any]:
    settings = get_settings()
    state = _full_pipeline_state()
    auto_run_state = read_json(settings.pipeline_auto_run_state_path)
    schema_version = state.get("step_key_schema_version")
    container = _full_pipeline_container()
    container_info = _snapshot_container(container)
    latest_log_file = _latest_matching_log_file(settings.logs_dir, f"{FULL_PIPELINE_LOG_PREFIX}_*.log")

    if container_info["is_running"]:
        status = "running"
    elif state.get("status") == "completed":
        status = "completed"
    elif state.get("status") in {"failed", "stopped"}:
        status = state["status"]
    elif container_info["container_name"] and container_info["exit_code"] not in (None, 0):
        status = "failed"
    else:
        status = "idle"

    log_lines: list[str] = []
    log_source = "none"
    if container_info["container_name"]:
        log_lines = _tail_container_logs(container_info["container_name"], lines=PIPELINE_LOG_TAIL)
        if log_lines:
            log_source = "docker"
    if not log_lines and latest_log_file is not None:
        log_lines = tail_file(latest_log_file, lines=PIPELINE_LOG_TAIL)
        log_source = "file" if log_lines else "none"

    return {
        "status": status,
        "status_label": {
            "running": "Running",
            "completed": "Completed",
            "failed": "Failed",
            "stopped": "Stopped",
            "idle": "Idle",
        }.get(status, "Unknown"),
        "is_running": container_info["is_running"],
        "can_start": not container_info["is_running"],
        "can_stop": container_info["is_running"],
        "container_id": container_info["container_id"],
        "container_name": container_info["container_name"] or state.get("container_name"),
        "container_status": container_info["container_status"],
        "container_started_at": container_info["started_at"] or state.get("started_at"),
        "container_finished_at": container_info["finished_at"] or state.get("finished_at"),
        "container_exit_code": container_info["exit_code"],
        "oom_killed": container_info["oom_killed"],
        "current_step_key": _normalize_state_step_key(state.get("current_step_key"), schema_version=schema_version),
        "current_step_label": state.get("current_step_label"),
        "completed_steps": _normalize_state_step_keys(state.get("completed_steps", []), schema_version=schema_version),
        "failed_step_key": _normalize_state_step_key(state.get("failed_step_key"), schema_version=schema_version),
        "error_message": state.get("error_message"),
        "updated_at": state.get("updated_at"),
        "log_file": str(latest_log_file) if latest_log_file else state.get("log_file"),
        "log_source": log_source,
        "log_lines": log_lines,
        "auto_run": {
            "enabled": settings.pipeline_auto_run_enabled,
            "timezone": settings.pipeline_auto_run_timezone,
            "scheduled_time": settings.pipeline_auto_run_time,
            "state": auto_run_state,
        },
    }
