from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from docker import DockerClient
from docker.errors import DockerException, ImageNotFound, NotFound

from app.config import get_settings
from app.services.files import count_lines, read_json, run_command, tail_file


class BatchControlError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _docker_client() -> DockerClient | None:
    try:
        return DockerClient.from_env()
    except DockerException:
        return None


def _get_container_info(container_ref: str | None) -> dict[str, Any]:
    if not container_ref:
        return {
            "container_id": None,
            "container_name": None,
            "status": None,
            "running_for": None,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "oom_killed": False,
            "is_running": False,
        }

    client = _docker_client()
    if client is not None:
        try:
            container = client.containers.get(container_ref)
            state = container.attrs.get("State", {})
            finished_at = state.get("FinishedAt")
            return {
                "container_id": container.id,
                "container_name": container.name,
                "status": container.status,
                "running_for": state.get("StartedAt"),
                "started_at": state.get("StartedAt"),
                "finished_at": None if finished_at == "0001-01-01T00:00:00Z" else finished_at,
                "exit_code": state.get("ExitCode"),
                "oom_killed": bool(state.get("OOMKilled")),
                "is_running": container.status == "running",
            }
        except NotFound:
            pass
        except DockerException:
            pass

    ok, output = run_command(
        [
            "docker",
            "inspect",
            container_ref,
            "--format",
            "{{.Id}}\t{{.Name}}\t{{.State.Status}}\t{{.State.StartedAt}}\t{{.State.FinishedAt}}\t{{.State.ExitCode}}\t{{.State.OOMKilled}}",
        ]
    )
    if ok and output:
        parts = output.strip().split("\t")
        if len(parts) == 7:
            container_id, container_name, status, started_at, finished_at, exit_code, oom_killed = parts
            normalized_name = container_name.lstrip("/")
            normalized_finished_at = None if finished_at == "0001-01-01T00:00:00Z" else finished_at
            try:
                normalized_exit_code = int(exit_code)
            except ValueError:
                normalized_exit_code = None
            return {
                "container_id": container_id,
                "container_name": normalized_name or None,
                "status": status or None,
                "running_for": started_at or None,
                "started_at": started_at or None,
                "finished_at": normalized_finished_at,
                "exit_code": normalized_exit_code,
                "oom_killed": oom_killed.strip().lower() == "true",
                "is_running": status == "running",
            }

    ok, output = run_command(
        [
            "docker",
            "ps",
            "--no-trunc",
            "--format",
            "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.RunningFor}}",
        ]
    )
    if not ok or not output:
        return {
            "container_id": container_ref,
            "container_name": None,
            "status": None,
            "running_for": None,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "oom_killed": False,
            "is_running": False,
        }

    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        container_id, container_name, status, running_for = parts
        if container_id.startswith(container_ref) or container_name == container_ref:
            return {
                "container_id": container_id,
                "container_name": container_name,
                "status": status,
                "running_for": running_for,
                "started_at": None,
                "finished_at": None,
                "exit_code": None,
                "oom_killed": False,
                "is_running": status.lower().startswith("up"),
            }
    return {
        "container_id": container_ref,
        "container_name": None,
        "status": None,
        "running_for": None,
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "oom_killed": False,
        "is_running": False,
    }


def _get_container_by_ref(container_ref: str | None):
    if not container_ref:
        return None
    client = _docker_client()
    if client is None:
        return None
    try:
        return client.containers.get(container_ref)
    except (DockerException, NotFound):
        return None


def _find_latest_batch_container():
    client = _docker_client()
    if client is None:
        return None
    try:
        containers = client.containers.list(all=True, filters={"name": "aistockcn-full-market-3y-"})
    except DockerException:
        return None
    if not containers:
        return None
    return sorted(containers, key=lambda item: item.attrs.get("Created", ""))[-1]


def _active_batch_container():
    settings = get_settings()
    container_ref = None
    container_id_path = settings.run_dir / "full_market_3y.pid"
    if container_id_path.exists():
        container_ref = container_id_path.read_text(encoding="utf-8").strip() or None

    container = _get_container_by_ref(container_ref)
    if container is not None:
        return container
    return _find_latest_batch_container()


def _china_today() -> datetime.date:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date()


def _rolling_default_start_date(end_date: datetime.date) -> str:
    return (end_date - timedelta(days=366 * 3)).strftime("%Y%m%d")


def _write_status_artifacts(*, timestamp: str, container_id: str, container_name: str, args: list[str]) -> Path:
    settings = get_settings()
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    (settings.run_dir / "full_market_3y.pid").write_text(f"{container_id}\n", encoding="utf-8")

    logger_pid_path = settings.run_dir / "full_market_3y_logger.pid"
    if logger_pid_path.exists():
        logger_pid_path.unlink()

    log_file = settings.logs_dir / f"full_market_3y_{timestamp}.log"
    log_file.write_text(
        "\n".join(
            [
                "Batch started from control panel.",
                f"CONTAINER: {container_name}",
                f"CONTAINER_ID: {container_id}",
                f"ARGS: {' '.join(args)}",
                "LIVE_LOG_SOURCE: docker",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return log_file


def _default_batch_args() -> dict[str, str]:
    settings = get_settings()
    state = read_json(settings.state_file)
    china_today = _china_today()
    return {
        "start_date": str(state.get("start_date") or _rolling_default_start_date(china_today)),
        "end_date": china_today.strftime("%Y%m%d"),
        "sleep_seconds": "1.2",
        "pause_minutes": "15",
        "max_passes": "5",
        "max_attempts": "6",
        "relogin_every": "300",
        # Industry is a live model feature, so the canonical batch should keep
        # stock metadata enriched instead of relying on a side workflow.
        "include_industry": str(state.get("include_industry") or "1"),
    }


def start_batch() -> dict[str, Any]:
    settings = get_settings()
    active = _active_batch_container()
    if active is not None and active.status == "running":
        raise BatchControlError("already_running", f"Batch is already running in {active.name}.", status_code=409)

    client = _docker_client()
    if client is None:
        raise BatchControlError("docker_unavailable", "Docker socket is unavailable from the API container.", status_code=503)

    try:
        client.images.get("aistockcn-data-prep:latest")
    except ImageNotFound as exc:
        raise BatchControlError("image_missing", "Image aistockcn-data-prep:latest is missing. Build data-prep first.", status_code=409) from exc
    except DockerException as exc:
        raise BatchControlError("docker_unavailable", "Unable to inspect Docker images.", status_code=503) from exc

    defaults = _default_batch_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    container_name = f"aistockcn-full-market-3y-{timestamp}"
    command = [
        "batch_download_all_a.py",
        "--start-date",
        defaults["start_date"],
        "--end-date",
        defaults["end_date"],
        "--sleep",
        defaults["sleep_seconds"],
        "--pause-minutes",
        defaults["pause_minutes"],
        "--max-passes",
        defaults["max_passes"],
        "--max-attempts",
        defaults["max_attempts"],
        "--relogin-every",
        defaults["relogin_every"],
    ]
    if defaults["include_industry"].strip().lower() not in {"0", "false", "no"}:
        command.append("--include-industry")

    try:
        container = client.containers.run(
            "aistockcn-data-prep:latest",
            command=command,
            name=container_name,
            detach=True,
            entrypoint="python",
            working_dir="/app",
            environment={"TZ": "UTC"},
            volumes={str(settings.host_project_root): {"bind": "/app", "mode": "rw"}},
        )
    except DockerException as exc:
        raise BatchControlError("start_failed", f"Failed to start batch container: {exc}", status_code=500) from exc

    log_file = _write_status_artifacts(
        timestamp=timestamp,
        container_id=container.id,
        container_name=container.name,
        args=command,
    )
    return {
        "ok": True,
        "action": "start",
        "code": "started",
        "message": f"Batch started in {container.name}.",
        "container_id": container.id,
        "container_name": container.name,
        "log_file": str(log_file),
    }


def stop_batch() -> dict[str, Any]:
    active = _active_batch_container()
    if active is None:
        raise BatchControlError("not_found", "No batch container record was found.", status_code=404)
    if active.status != "running":
        raise BatchControlError("not_running", f"Batch container {active.name} is not running.", status_code=409)

    try:
        active.stop(timeout=30)
        active.reload()
    except DockerException as exc:
        raise BatchControlError("stop_failed", f"Failed to stop batch container: {exc}", status_code=500) from exc

    settings = get_settings()
    logger_pid_path = settings.run_dir / "full_market_3y_logger.pid"
    if logger_pid_path.exists():
        logger_pid_path.unlink()

    latest_log_file = _latest_log_file(settings.logs_dir)
    if latest_log_file is not None:
        with latest_log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"Batch stopped from control panel at {datetime.now(timezone.utc).isoformat()}\n")

    return {
        "ok": True,
        "action": "stop",
        "code": "stopped",
        "message": f"Batch container {active.name} has been stopped.",
        "container_id": active.id,
        "container_name": active.name,
        "status": active.status,
    }


def _latest_log_file(logs_dir: Path) -> Path | None:
    candidates = sorted(logs_dir.glob("full_market_3y_*.log"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def get_batch_status() -> dict[str, Any]:
    settings = get_settings()
    state = read_json(settings.state_file)

    container_ref = None
    container_id_path = settings.run_dir / "full_market_3y.pid"
    if container_id_path.exists():
        container_ref = container_id_path.read_text(encoding="utf-8").strip() or None

    container = _get_container_info(container_ref)
    latest_log_file = _latest_log_file(settings.logs_dir)
    latest_log_updated_at = None
    latest_log_line_count = 0
    if latest_log_file is not None:
        stat = latest_log_file.stat()
        latest_log_updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        latest_log_line_count = count_lines(latest_log_file)

    stock_count = 0
    if settings.stock_list_path.exists():
        try:
            stock_count = int(len(pd.read_parquet(settings.stock_list_path, columns=["code"])))
        except Exception:
            stock_count = 0

    done_codes = state.get("done_codes", [])
    failed_codes = state.get("failed_codes", {})
    attempts = state.get("attempts", {})
    attempted_count = sum(1 for value in attempts.values() if int(value) > 0)
    total_codes = max(stock_count, len(attempts), len(done_codes))
    remaining_count = max(total_codes - len(done_codes), 0) if total_codes else None
    progress_pct = round((len(done_codes) / total_codes) * 100, 2) if total_codes else None

    updated_at = _parse_iso(state.get("updated_at"))
    stale_after = timedelta(minutes=20)
    is_stale = updated_at is None or (datetime.now(timezone.utc) - updated_at) > stale_after

    top_failures = [
        {"reason": reason, "count": count}
        for reason, count in Counter(str(reason) for reason in failed_codes.values()).most_common(8)
    ]

    return {
        "is_running": container["is_running"] or not is_stale,
        "is_stale": is_stale,
        "container_id": container["container_id"],
        "container_name": container["container_name"],
        "container_status": container["status"],
        "container_running_for": container["running_for"],
        "container_started_at": container["started_at"],
        "container_finished_at": container["finished_at"],
        "container_exit_code": container["exit_code"],
        "oom_killed": container["oom_killed"],
        "state_file": str(settings.state_file),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "start_date": state.get("start_date"),
        "end_date": state.get("end_date"),
        "current_pass_index": state.get("pass_index"),
        "last_code": state.get("last_code"),
        "done_count": len(done_codes),
        "failed_count": len(failed_codes),
        "attempted_count": attempted_count,
        "total_codes": total_codes,
        "remaining_count": remaining_count,
        "progress_pct": progress_pct,
        "failure_reasons_top": top_failures,
        "latest_log_file": str(latest_log_file) if latest_log_file else None,
        "latest_log_updated_at": latest_log_updated_at,
        "latest_log_line_count": latest_log_line_count,
        "can_start": not container["is_running"],
        "can_stop": bool(container["is_running"]),
    }


def get_batch_logs(*, lines: int = 120) -> dict[str, Any]:
    settings = get_settings()
    container_ref = None
    container_id_path = settings.run_dir / "full_market_3y.pid"
    if container_id_path.exists():
        container_ref = container_id_path.read_text(encoding="utf-8").strip() or None

    container = _get_container_info(container_ref)
    if container["container_name"]:
        client = _docker_client()
        if client is not None:
            try:
                log_bytes = client.containers.get(container["container_id"]).logs(tail=lines)
                return {
                    "source": "docker",
                    "container_name": container["container_name"],
                    "lines": log_bytes.decode("utf-8", errors="replace").splitlines(),
                }
            except (DockerException, NotFound):
                pass

        ok, output = run_command(
            ["docker", "logs", "--tail", str(lines), container["container_name"]],
            timeout=10,
        )
        if ok:
            return {
                "source": "docker",
                "container_name": container["container_name"],
                "lines": output.splitlines(),
            }

    latest_log_file = _latest_log_file(settings.logs_dir)
    if latest_log_file is not None:
        return {
            "source": "file",
            "path": str(latest_log_file),
            "lines": tail_file(latest_log_file, lines=lines),
        }

    return {"source": "none", "lines": []}
