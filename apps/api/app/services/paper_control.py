from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docker.errors import DockerException, ImageNotFound, NotFound

from app.config import get_settings
from app.services.batch import BatchControlError, _docker_client, _get_container_by_ref
from app.services.files import run_command, tail_file

PAPER_LOG_TAIL = 40
PAPER_TRADING_PID_FILE = "paper_trading_daemon.pid"
PAPER_TRADING_LOG_PREFIX = "paper_trading_daemon"
PAPER_TRADING_CONTAINER_PREFIX = "aistockcn-paper-trading-daemon-"
DATA_PREP_IMAGE = "aistockcn-data-prep:latest"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pid_file() -> Path:
    return get_settings().run_dir / PAPER_TRADING_PID_FILE


def _latest_matching_log_file(logs_dir: Path, pattern: str) -> Path | None:
    candidates = sorted(logs_dir.glob(pattern), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _append_control_log_line(path: Path | None, line: str) -> None:
    if path is None:
        return
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return


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
        if name_prefixes and any(container.name.startswith(prefix) for prefix in name_prefixes):
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


def _write_log_stub(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _redact_command_args(command: list[str]) -> list[str]:
    redacted: list[str] = []
    secret_flags = {"--agent-key"}
    skip_next = False
    for value in command:
        if skip_next:
            redacted.append("***REDACTED***")
            skip_next = False
            continue
        redacted.append(value)
        if value in secret_flags:
            skip_next = True
    return redacted


def _paper_daemon_container() -> Any | None:
    return _find_latest_matching_container(
        pid_file=_pid_file(),
        name_prefixes=[PAPER_TRADING_CONTAINER_PREFIX],
        command_markers=["paper_trade_daemon.py"],
    )


def _paper_daemon_network() -> str | None:
    client = _docker_client()
    if client is None:
        return None

    current_ref = os.getenv("HOSTNAME", "").strip()
    if current_ref:
        current_container = _get_container_by_ref(current_ref)
        if current_container is not None:
            networks = current_container.attrs.get("NetworkSettings", {}).get("Networks", {})
            for name in networks:
                if name not in {"bridge", "host", "none"}:
                    return name

    try:
        network_names = {network.name for network in client.networks.list()}
    except DockerException:
        return None

    if "aistockcn_default" in network_names:
        return "aistockcn_default"
    return None


def _paper_command() -> list[str]:
    settings = get_settings()
    command = [
        "paper_trade_daemon.py",
        "--scores-path",
        "quant_data/models/inference_scores_latest.parquet",
        "--state-dir",
        "quant_data/paper_trading",
        "--gateway-base-url",
        settings.futu_gateway_base_url,
        "--market",
        settings.futu_gateway_market,
        "--agent-id",
        settings.futu_gateway_agent_id,
        "--agent-key",
        settings.futu_gateway_agent_key or "",
        "--agent-id-header",
        settings.futu_gateway_agent_id_header,
        "--agent-key-header",
        settings.futu_gateway_agent_key_header,
        "--top-k",
        str(settings.paper_trading_top_k),
        "--min-score",
        str(settings.paper_trading_min_score),
        "--lot-size",
        str(settings.paper_trading_lot_size),
        "--cash-buffer-pct",
        str(settings.paper_trading_cash_buffer_pct),
        "--buy-limit-bps",
        str(settings.paper_trading_buy_limit_bps),
        "--sell-limit-bps",
        str(settings.paper_trading_sell_limit_bps),
        "--interval-seconds",
        str(settings.paper_trading_interval_seconds),
        "--max-order-qty",
        str(settings.paper_trading_max_order_qty),
    ]
    if settings.futu_gateway_account_id is not None:
        command.extend(["--account-id", str(settings.futu_gateway_account_id)])
    if settings.paper_trading_budget_total is not None:
        command.extend(["--budget-total", str(settings.paper_trading_budget_total)])
    return command


def start_paper_trading_daemon() -> dict[str, Any]:
    active = _paper_daemon_container()
    if active is not None and active.status == "running":
        raise BatchControlError("already_running", f"Paper-trading daemon is already running in {active.name}.", status_code=409)

    client = _docker_client()
    if client is None:
        raise BatchControlError("docker_unavailable", "Docker socket is unavailable from the API container.", status_code=503)
    try:
        client.images.get(DATA_PREP_IMAGE)
    except ImageNotFound as exc:
        raise BatchControlError("image_missing", f"Image {DATA_PREP_IMAGE} is missing.", status_code=409) from exc
    except DockerException as exc:
        raise BatchControlError("docker_unavailable", "Unable to inspect Docker images.", status_code=503) from exc

    settings = get_settings()
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _timestamp()
    container_name = f"{PAPER_TRADING_CONTAINER_PREFIX}{timestamp}"
    log_file = settings.logs_dir / f"{PAPER_TRADING_LOG_PREFIX}_{timestamp}.log"
    command = _paper_command()
    network_name = _paper_daemon_network()

    try:
        container_kwargs: dict[str, Any] = {
            "command": command,
            "name": container_name,
            "detach": True,
            "entrypoint": "python",
            "working_dir": "/app",
            "environment": {"TZ": "UTC"},
            "volumes": {str(settings.host_project_root): {"bind": "/app", "mode": "rw"}},
        }
        if network_name:
            container_kwargs["network"] = network_name

        container = client.containers.run(
            DATA_PREP_IMAGE,
            **container_kwargs,
        )
    except DockerException as exc:
        raise BatchControlError("start_failed", f"Failed to start paper-trading daemon: {exc}", status_code=500) from exc

    _pid_file().write_text(f"{container.id}\n", encoding="utf-8")
    _write_log_stub(
        log_file,
        [
            "Paper-trading daemon started from control panel.",
            f"CONTAINER: {container.name}",
            f"CONTAINER_ID: {container.id}",
            f"ARGS: python {' '.join(_redact_command_args(command))}",
            "LIVE_LOG_SOURCE: docker",
            f"STARTED_AT: {_now_iso()}",
        ],
    )

    return {
        "ok": True,
        "action": "start",
        "target": "paper",
        "code": "started",
        "message": f"Paper-trading daemon started in {container.name}.",
        "container_id": container.id,
        "container_name": container.name,
        "log_file": str(log_file),
    }


def stop_paper_trading_daemon() -> dict[str, Any]:
    container = _paper_daemon_container()
    if container is None:
        raise BatchControlError("not_found", "No paper-trading daemon container record was found.", status_code=404)
    if container.status != "running":
        raise BatchControlError("not_running", "Paper-trading daemon is not currently running.", status_code=409)

    try:
        container.stop(timeout=30)
        container.reload()
    except DockerException as exc:
        raise BatchControlError("stop_failed", f"Failed to stop paper-trading daemon: {exc}", status_code=500) from exc

    latest_log_file = _latest_matching_log_file(get_settings().logs_dir, f"{PAPER_TRADING_LOG_PREFIX}_*.log")
    _append_control_log_line(latest_log_file, f"Stopped from control panel at {_now_iso()}\n")

    return {
        "ok": True,
        "action": "stop",
        "target": "paper",
        "code": "stopped",
        "message": f"Paper-trading daemon {container.name} has been stopped.",
        "container_id": container.id,
        "container_name": container.name,
        "status": container.status,
    }


def get_paper_trading_daemon_status() -> dict[str, Any]:
    settings = get_settings()
    container = _paper_daemon_container()
    container_info = _snapshot_container(container)
    latest_log_file = _latest_matching_log_file(settings.logs_dir, f"{PAPER_TRADING_LOG_PREFIX}_*.log")

    log_lines: list[str] = []
    log_source = "none"
    if container_info["container_name"]:
        log_lines = _tail_container_logs(container_info["container_name"], lines=PAPER_LOG_TAIL)
        if log_lines:
            log_source = "docker"
    if not log_lines and latest_log_file is not None:
        log_lines = tail_file(latest_log_file, lines=PAPER_LOG_TAIL)
        log_source = "file" if log_lines else "none"

    if container_info["is_running"]:
        status = "running"
    elif container_info["container_name"] and container_info["exit_code"] not in (None, 0):
        status = "failed"
    elif latest_log_file is not None:
        status = "stopped"
    else:
        status = "idle"

    return {
        "status": status,
        "status_label": {
            "running": "Running",
            "failed": "Failed",
            "stopped": "Stopped",
            "idle": "Idle",
        }.get(status, "Unknown"),
        "is_running": container_info["is_running"],
        "can_start": not container_info["is_running"],
        "can_stop": container_info["is_running"],
        "container_id": container_info["container_id"],
        "container_name": container_info["container_name"],
        "container_status": container_info["container_status"],
        "container_started_at": container_info["started_at"],
        "container_finished_at": container_info["finished_at"],
        "container_exit_code": container_info["exit_code"],
        "oom_killed": container_info["oom_killed"],
        "log_file": str(latest_log_file) if latest_log_file else None,
        "log_source": log_source,
        "log_lines": log_lines,
    }
