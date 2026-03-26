from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from docker.errors import DockerException, NotFound

from app.config import get_settings
from app.services.batch import _docker_client, _get_container_by_ref, get_batch_logs, get_batch_status
from app.services.data import get_data_summary, get_pipeline_summary
from app.services.files import run_command, tail_file
from app.services.model import get_model_overview
from app.services.paper import get_paper_trading_status

STEP_LOG_TAIL = 24


STEP1_LOG_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    (r"^请求失败，([0-9.]+) 秒后重试 \((\d+)/(\d+)\): (.+)$", r"Request failed, retrying in \1s (\2/\3): \4"),
    (r"^Baostock 会话已失效，正在自动重新登录\.\.\.$", r"Baostock session expired, re-authenticating..."),
    (r"^正在通过 Baostock 获取全市场 A 股名单，交易日: (.+)\.\.\.$", r"Fetching full A-share universe from Baostock, trade date: \1..."),
    (r"^(.+) 返回空股票列表，回退到更早交易日继续尝试。$", r"\1 returned an empty stock list, falling back to an earlier trade date."),
    (r"^(.+) 过滤后无有效 A 股列表，回退到更早交易日继续尝试。$", r"\1 returned no investable A-shares after filtering, falling back to an earlier trade date."),
    (r"^正在通过 Baostock 获取沪深300成分股名单\.\.\.$", r"Fetching CSI 300 constituents from Baostock..."),
    (r"^行业补全已启用：当前已知行业 (\d+)/(\d+)，待补 (\d+)。$", r"Industry enrichment enabled: \1/\2 industries already known, \3 to fill."),
    (r"^\[stock_list (\d+)/(\d+)\] 正在通过 Baostock 补充行业信息: (\d+)$", r"[stock_list \1/\2] Filling industry metadata from Baostock: \3"),
    (r"^补充 (\d+) 行业信息失败: (.+)$", r"Failed to fill industry metadata for \1: \2"),
    (r"^行业补全完成：已知行业 (\d+)/(\d+)，仍缺失 (\d+)。$", r"Industry enrichment finished: \1/\2 industries known, \3 still missing."),
    (r"^行业补全已跳过：当前已知行业 (\d+)/(\d+)，缺失 (\d+)。如需恢复 industry 特征，请启用 --include-industry。$", r"Industry enrichment skipped: \1/\2 industries known, \3 missing. Enable --include-industry to restore the industry feature."),
    (r"^活跃股票池已保存至 (.+)，共 (\d+) 只股票。$", r"Active universe saved to \1, \2 stocks."),
    (r"^主注册表已保存至 (.+)，共 (\d+) 只股票。$", r"Master registry saved to \1, \2 stocks."),
    (r"^股票池同步结果: 新增 (\d+)，恢复 (\d+)，停用 (\d+)$", r"Universe sync result: added \1, reactivated \2, deactivated \3"),
    (r"^全市场股票数: (\d+)$", r"Full-market stock count: \1"),
    (r"^已完成: (\d+)$", r"Completed: \1"),
    (r"^状态文件: (.+)$", r"State file: \1"),
    (r"^开始第 (\d+)/(\d+) 轮，待处理股票数: (\d+)$", r"Starting pass \1/\2, pending stocks: \3"),
    (r"^\[pass (\d+) (\d+)/(\d+)\] 下载 (\d+)，尝试次数 (\d+)/(\d+)$", r"[pass \1 \2/\3] Downloading \4, attempt \5/\6"),
    (r"^达到重新登录阈值，重连 Baostock\.\.\.$", r"Reached re-login threshold, reconnecting to Baostock..."),
    (r"^(\d{6}) 完成，提醒: (.+)$", r"\1 completed, note: \2"),
    (r"^(\d{6}) 完成$", r"\1 completed"),
    (r"^(\d{6}) 失败: (.+)$", r"\1 failed: \2"),
    (r"^第 (\d+) 轮结束，累计完成 (\d+)/(\d+)，剩余待重试 (\d+)$", r"Pass \1 finished, completed \2/\3, remaining for retry: \4"),
    (r"^暂停 ([0-9.]+) 分钟后进入下一轮\.\.\.$", r"Pausing \1 minutes before the next pass..."),
)

STEP2_LOG_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    (r"^stock_list\.parquet 缺少 exchange 列，请先重新运行 download_data\.py 刷新股票列表。$", r"stock_list.parquet is missing the exchange column. Re-run download_data.py to refresh the stock list."),
    (r"^没有可用的 K 线/估值 parquet 可合并。$", r"No K-line / valuation parquet files are available to merge."),
    (r"^已处理 (\d+)/(\d+) 只股票，当前累计 (\d+) 只进入训练集，(\d+) 行。$", r"Processed \1/\2 stocks, \3 included in training so far, \4 rows."),
    (r"^没有生成任何可用训练样本。$", r"No usable training samples were generated."),
    (r"^原始面板数据维度: \((.+)\)$", r"Raw panel shape: (\1)"),
    (r"^特征工程完成，可训练数据维度: \((.+)\)$", r"Feature engineering completed, trainable shape: (\1)"),
    (r"^输出文件: (.+)$", r"Output file: \1"),
    (r"^特征元数据文件: (.+)$", r"Feature metadata file: \1"),
)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_matching_log_file(logs_dir: Path, patterns: str | list[str]) -> Path | None:
    pattern_list = [patterns] if isinstance(patterns, str) else patterns
    candidates: list[Path] = []
    for pattern in pattern_list:
        candidates.extend(logs_dir.glob(pattern))
    candidates = sorted(candidates, key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _path_snapshot(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _container_command(container: Any) -> str:
    config = container.attrs.get("Config", {})
    parts: list[str] = []
    for value in [config.get("Entrypoint"), config.get("Cmd")]:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(part for part in parts if part)


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
            "command": None,
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
        "command": _container_command(container),
        "is_running": container.status == "running",
    }


def _container_from_pid_file(pid_path: Path) -> Any | None:
    if not pid_path.exists():
        return None
    container_ref = pid_path.read_text(encoding="utf-8").strip()
    if not container_ref:
        return None
    return _get_container_by_ref(container_ref)


def _find_latest_matching_container(
    *,
    pid_files: list[Path] | None = None,
    name_prefixes: list[str] | None = None,
    exact_names: list[str] | None = None,
    command_markers: list[str] | None = None,
) -> Any | None:
    matched: list[Any] = []
    seen_ids: set[str] = set()

    for pid_file in pid_files or []:
        container = _container_from_pid_file(pid_file)
        if container is None or container.id in seen_ids:
            continue
        matched.append(container)
        seen_ids.add(container.id)

    client = _docker_client()
    if client is None:
        if not matched:
            return None
        return sorted(matched, key=lambda item: (item.status == "running", item.attrs.get("Created", "")))[-1]

    try:
        containers = client.containers.list(all=True)
    except DockerException:
        if not matched:
            return None
        return sorted(matched, key=lambda item: (item.status == "running", item.attrs.get("Created", "")))[-1]

    def matches(container: Any) -> bool:
        name = container.name
        if exact_names and name in exact_names:
            return True
        if name_prefixes and any(name.startswith(prefix) for prefix in name_prefixes):
            return True
        if command_markers:
            command = _container_command(container)
            if any(marker in command for marker in command_markers):
                return True
        return False

    for container in containers:
        if not matches(container) or container.id in seen_ids:
            continue
        matched.append(container)
        seen_ids.add(container.id)
    if not matched:
        return None
    return sorted(matched, key=lambda item: (item.status == "running", item.attrs.get("Created", "")))[-1]


def _resolve_container(
    *,
    pid_files: list[Path] | None = None,
    name_prefixes: list[str] | None = None,
    exact_names: list[str] | None = None,
    command_markers: list[str] | None = None,
) -> Any | None:
    return _find_latest_matching_container(
        pid_files=pid_files,
        name_prefixes=name_prefixes,
        exact_names=exact_names,
        command_markers=command_markers,
    )


def _tail_container_logs(container_name: str, *, lines: int) -> list[str]:
    client = _docker_client()
    if client is not None:
        try:
            container = client.containers.get(container_name)
            log_bytes = container.logs(tail=lines)
            return log_bytes.decode("utf-8", errors="replace").splitlines()
        except (DockerException, NotFound):
            pass

    ok, output = run_command(
        ["docker", "logs", "--tail", str(lines), container_name],
        timeout=10,
    )
    return output.splitlines() if ok and output else []


def _resolve_log_payload(
    *,
    container_info: dict[str, Any],
    latest_log_file: Path | None,
    lines: int,
) -> dict[str, Any]:
    if container_info["container_name"]:
        live_lines = _tail_container_logs(container_info["container_name"], lines=lines)
        if live_lines:
            return {
                "source": "docker",
                "path": str(latest_log_file) if latest_log_file else None,
                "updated_at": None,
                "lines": live_lines,
            }

    if latest_log_file is not None:
        stat = latest_log_file.stat()
        return {
            "source": "file",
            "path": str(latest_log_file),
            "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "lines": tail_file(latest_log_file, lines=lines),
        }

    return {"source": "none", "path": None, "updated_at": None, "lines": []}


def _translate_log_line(line: str, translations: tuple[tuple[str, str], ...]) -> str:
    text = line.rstrip("\n")
    for pattern, replacement in translations:
        translated = re.sub(pattern, replacement, text)
        if translated != text:
            return translated
    return text


def _display_log_lines(*, step: int, key: str, lines: list[str]) -> list[str]:
    if step == 1 or key == "data_prepare":
        return [_translate_log_line(line, STEP1_LOG_TRANSLATIONS) for line in lines]
    if step == 2 or key == "feature_engineering":
        return [_translate_log_line(line, STEP2_LOG_TRANSLATIONS) for line in lines]
    return lines


def _detail(label: str, value: Any) -> dict[str, str]:
    if value is None:
        return {"label": label, "value": "—"}
    text = str(value).strip()
    return {"label": label, "value": text or "—"}


def _derive_step_status(
    *,
    container_info: dict[str, Any],
    artifact: dict[str, Any] | None,
) -> str:
    if container_info["is_running"]:
        return "running"

    artifact_updated_at = _parse_iso(artifact["updated_at"]) if artifact else None
    finished_at = _parse_iso(container_info["finished_at"])
    failed_after_artifact = (
        finished_at is not None
        and (artifact_updated_at is None or finished_at >= artifact_updated_at)
        and (container_info["oom_killed"] or container_info["exit_code"] not in (None, 0))
    )
    if failed_after_artifact:
        return "failed"

    if artifact is not None:
        return "completed"

    if container_info["container_name"] and container_info["exit_code"] not in (None, 0):
        return "failed"

    return "idle"


def _status_label(status: str) -> str:
    return {
        "running": "Running",
        "completed": "Completed",
        "failed": "Failed",
        "stalled": "Stalled",
        "idle": "Idle",
    }.get(status, "Unknown")


def _build_runtime_step(
    *,
    step: int,
    key: str,
    runner_script: str | None,
    command_hint: str | None,
    pid_file_names: list[str] | None,
    log_patterns: list[str] | None,
    name_prefixes: list[str] | None,
    exact_names: list[str] | None,
    command_markers: list[str] | None,
    artifact_path: Path | None,
    details: list[dict[str, str]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    pid_files = [settings.run_dir / pid_file_name for pid_file_name in (pid_file_names or [])]
    container = _resolve_container(
        pid_files=pid_files,
        name_prefixes=name_prefixes,
        exact_names=exact_names,
        command_markers=command_markers,
    )
    container_info = _snapshot_container(container)
    latest_log_file = _latest_matching_log_file(settings.logs_dir, log_patterns) if log_patterns else None
    artifact = _path_snapshot(artifact_path)
    log_payload = _resolve_log_payload(
        container_info=container_info,
        latest_log_file=latest_log_file,
        lines=STEP_LOG_TAIL,
    )

    return {
        "step": step,
        "key": key,
        "status": _derive_step_status(container_info=container_info, artifact=artifact),
        "status_label": _status_label(_derive_step_status(container_info=container_info, artifact=artifact)),
        "is_running": container_info["is_running"],
        "runner_script": runner_script,
        "command_hint": command_hint,
        "container_name": container_info["container_name"],
        "container_status": container_info["container_status"],
        "container_started_at": container_info["started_at"],
        "container_finished_at": container_info["finished_at"],
        "container_exit_code": container_info["exit_code"],
        "oom_killed": container_info["oom_killed"],
        "latest_log_source": log_payload["source"],
        "latest_log_file": log_payload["path"],
        "latest_log_updated_at": log_payload["updated_at"],
        "artifact_path": artifact["path"] if artifact else None,
        "artifact_updated_at": artifact["updated_at"] if artifact else None,
        "artifact_size_bytes": artifact["size_bytes"] if artifact else None,
        "details": details,
        "warnings": warnings or [],
        "log_lines": _display_log_lines(step=step, key=key, lines=log_payload["lines"]),
    }


def _build_data_prepare_step_runtime(
    *,
    data_summary: dict[str, Any],
    batch_status: dict[str, Any],
    batch_logs: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    artifact_path = settings.stock_list_path
    artifact = _path_snapshot(artifact_path)
    reference_snapshot = data_summary.get("reference_snapshot") or {}
    industry_missing_count = int(reference_snapshot.get("industry_missing_count") or 0)
    reference_missing_count = int(reference_snapshot.get("valuation_reference_missing_count") or 0)
    reference_stale_count = int(reference_snapshot.get("valuation_reference_stale_count") or 0)
    warnings: list[str] = []

    if not reference_snapshot:
        warnings.append(
            "Slow reference status is missing. Run `bash run_reference_data_batch.sh` after the active stock list is available."
        )
    else:
        if industry_missing_count > 0:
            warnings.append(
                f"Industry metadata is missing for {industry_missing_count} active stocks. Run `bash run_reference_data_batch.sh` to refresh slow metadata."
            )
        if reference_missing_count > 0 or reference_stale_count > 0:
            warnings.append(
                f"Reference valuation cache is missing for {reference_missing_count} stocks and stale for {reference_stale_count} stocks. Downstream feature rows can be dropped until the manual reference batch catches up."
            )

    if data_summary["active_stock_count"] == 0 and data_summary["paired_file_count"] == 0:
        status = "idle"
    elif batch_status.get("is_stalled"):
        status = "stalled"
    elif batch_status["is_running"]:
        status = "running"
    elif batch_status.get("oom_killed") or batch_status.get("container_exit_code") not in (None, 0):
        status = "failed"
    elif artifact is not None:
        status = "completed"
    else:
        status = "idle"

    top_failure_summary = ", ".join(
        f"{item['reason']} ({item['count']})"
        for item in batch_status.get("failure_reasons_top", [])[:4]
    ) or "—"
    details = [
        _detail("Combined stage", "step 1 data prepare combines universe sync and raw download in one batch"),
        _detail("Runner", "bash run_a_share_3y_batch.sh"),
        _detail("Container", batch_status.get("container_name")),
        _detail("Container status", batch_status.get("container_status")),
        _detail("Progress", f"{batch_status['progress_pct']}%" if batch_status.get("progress_pct") is not None else None),
        _detail("Done / total", f"{batch_status.get('done_count', 0)} / {batch_status.get('total_codes') or '—'}"),
        _detail("Failed count", batch_status.get("failed_count")),
        _detail("Current pass", batch_status.get("current_pass_index")),
        _detail("Last code", batch_status.get("last_code")),
        _detail("Active stocks", data_summary.get("active_stock_count")),
        _detail("Registry rows", data_summary.get("registry_stock_count")),
        _detail("Kline files", data_summary.get("kline_file_count")),
        _detail("Valuation files", data_summary.get("valuation_file_count")),
        _detail("Paired files", data_summary.get("paired_file_count")),
        _detail("Reference status", reference_snapshot.get("path")),
        _detail("Reference updated", reference_snapshot.get("updated_at")),
        _detail("Reference ready", reference_snapshot.get("valuation_reference_ready_count")),
        _detail("Reference missing", reference_missing_count),
        _detail("Reference stale", reference_stale_count),
        _detail("Industry missing", industry_missing_count),
        _detail("Reference batch state", reference_snapshot.get("batch_state_path")),
        _detail("Reference batch updated", reference_snapshot.get("batch_updated_at")),
        _detail("Reference batch last code", reference_snapshot.get("batch_last_code")),
        _detail("Failure reasons", top_failure_summary),
        _detail("Batch state created", batch_status.get("created_at")),
        _detail("State updated", batch_status.get("updated_at")),
        _detail("Last activity", batch_status.get("last_activity_at")),
        _detail("Stalled", "yes" if batch_status.get("is_stalled") else "no"),
    ]

    return {
        "step": 1,
        "key": "data_prepare",
        "status": status,
        "status_label": _status_label(status),
        "is_running": bool(batch_status.get("is_running")),
        "runner_script": "bash run_a_share_3y_batch.sh",
        "command_hint": "bash run_full_market_3y_batch.sh",
        "container_name": batch_status.get("container_name"),
        "container_status": batch_status.get("container_status"),
        "container_started_at": batch_status.get("container_started_at") or batch_status.get("created_at"),
        "container_finished_at": batch_status.get("container_finished_at"),
        "container_exit_code": batch_status.get("container_exit_code"),
        "oom_killed": bool(batch_status.get("oom_killed")),
        "latest_log_source": batch_logs.get("source"),
        "latest_log_file": batch_status.get("latest_log_file"),
        "latest_log_updated_at": batch_status.get("latest_log_updated_at"),
        "artifact_path": artifact["path"] if artifact else None,
        "artifact_updated_at": artifact["updated_at"] if artifact else None,
        "artifact_size_bytes": artifact["size_bytes"] if artifact else None,
        "details": details,
        "warnings": warnings,
        "log_lines": _display_log_lines(step=1, key="data_prepare", lines=batch_logs.get("lines", [])),
    }


def _build_panel_step_runtime() -> dict[str, Any]:
    web_container = _resolve_container(exact_names=["aistockcn-panel-web-1"])
    api_container = _resolve_container(exact_names=["aistockcn-panel-api-1"])
    web_info = _snapshot_container(web_container)
    api_info = _snapshot_container(api_container)

    if web_info["is_running"] and api_info["is_running"]:
        status = "running"
    elif web_info["container_name"] or api_info["container_name"]:
        status = "failed"
    else:
        status = "idle"

    log_lines: list[str] = []
    for prefix, info in [("panel-api", api_info), ("panel-web", web_info)]:
        if not info["container_name"]:
            continue
        for line in _tail_container_logs(info["container_name"], lines=8):
            log_lines.append(f"[{prefix}] {line}")

    settings = get_settings()
    public_url = None
    panel_env_path = settings.run_dir / "panel.env"
    if panel_env_path.exists():
        for line in panel_env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("PANEL_PUBLIC_URL="):
                public_url = line.split("=", 1)[1].strip() or None
                break

    return {
        "step": 7,
        "key": "panel_and_ops",
        "status": status,
        "status_label": _status_label(status),
        "is_running": web_info["is_running"] and api_info["is_running"],
        "runner_script": "docker compose up -d panel-api panel-web",
        "command_hint": "docker compose up -d panel-api panel-web",
        "container_name": None,
        "container_status": None,
        "container_started_at": None,
        "container_finished_at": None,
        "container_exit_code": None,
        "oom_killed": False,
        "latest_log_source": "docker" if log_lines else "none",
        "latest_log_file": None,
        "latest_log_updated_at": None,
        "artifact_path": public_url,
        "artifact_updated_at": None,
        "artifact_size_bytes": None,
        "details": [
            _detail("Panel web", f"{web_info['container_name'] or '—'} / {web_info['container_status'] or '—'}"),
            _detail("Panel API", f"{api_info['container_name'] or '—'} / {api_info['container_status'] or '—'}"),
            _detail("Public URL", public_url),
            _detail("Web started", web_info["started_at"]),
            _detail("API started", api_info["started_at"]),
        ],
        "warnings": [],
        "log_lines": log_lines,
    }


def _build_paper_trading_step_runtime() -> dict[str, Any]:
    settings = get_settings()
    paper_status = get_paper_trading_status()
    daemon = paper_status.get("daemon") or {}
    state = paper_status.get("state") or {}
    gateway = paper_status.get("gateway") or {}
    targets = paper_status.get("targets") or {}

    artifact_path = targets.get("path") or str(settings.paper_trading_state_path)
    return {
        "step": 6,
        "key": "auto_paper_trading",
        "status": daemon.get("status") or "idle",
        "status_label": daemon.get("status_label") or "Idle",
        "is_running": bool(daemon.get("is_running")),
        "runner_script": "bash run_paper_trading_daemon.sh",
        "command_hint": "python paper_trade_daemon.py --scores-path quant_data/models/inference_scores_latest.parquet --state-dir quant_data/paper_trading",
        "container_name": daemon.get("container_name"),
        "container_status": daemon.get("container_status"),
        "container_started_at": daemon.get("container_started_at"),
        "container_finished_at": daemon.get("container_finished_at"),
        "container_exit_code": daemon.get("container_exit_code"),
        "oom_killed": daemon.get("oom_killed"),
        "latest_log_source": daemon.get("log_source"),
        "latest_log_file": daemon.get("log_file"),
        "latest_log_updated_at": None,
        "artifact_path": artifact_path,
        "artifact_updated_at": targets.get("updated_at"),
        "artifact_size_bytes": None,
        "details": [
            _detail("Runner", "bash run_paper_trading_daemon.sh"),
            _detail("Gateway", gateway.get("base_url")),
            _detail("Gateway healthy", gateway.get("healthy")),
            _detail("Agent", gateway.get("agent_id")),
            _detail("Market", gateway.get("market")),
            _detail("Last signal date", state.get("score_signal_date")),
            _detail("Last status", state.get("last_status")),
            _detail("Last success", state.get("last_success_at")),
            _detail("Target rows", targets.get("rows")),
            _detail("Target snapshot", targets.get("latest_signal_date")),
        ],
        "warnings": [],
        "log_lines": daemon.get("log_lines", []),
    }


def get_workflow_status() -> dict[str, Any]:
    settings = get_settings()
    data_summary = get_data_summary()
    pipeline_summary = get_pipeline_summary()
    model_overview = get_model_overview()
    batch_status = get_batch_status()
    batch_logs = get_batch_logs(lines=STEP_LOG_TAIL)

    training_snapshot = pipeline_summary.get("training_features") or {}
    inference_snapshot = pipeline_summary.get("inference_features") or {}
    score_snapshot = pipeline_summary.get("inference_scores") or {}
    training_metadata = model_overview.get("training_metadata") or {}
    backtest_summary = model_overview.get("backtest_summary") or {}
    training_metrics = training_metadata.get("metrics") or {}
    backtest_metrics = backtest_summary.get("oos_metrics") or {}

    steps = [
        _build_data_prepare_step_runtime(
            data_summary=data_summary,
            batch_status=batch_status,
            batch_logs=batch_logs,
        ),
        _build_runtime_step(
            step=2,
            key="training_features",
            runner_script="bash run_step2_feature_engineering.sh",
            command_hint="python feature_engineering.py --data-dir quant_data --output quant_data/ml_features_ready.parquet",
            pid_file_names=["step2_feature_engineering.pid", "step3_feature_engineering.pid"],
            log_patterns=["step2_feature_engineering_*.log", "step3_feature_engineering_*.log"],
            name_prefixes=["aistockcn-step2-feature-engineering-", "aistockcn-step3-feature-engineering-"],
            exact_names=None,
            command_markers=["feature_engineering.py"],
            artifact_path=settings.quant_dir / "ml_features_ready.parquet",
            details=[
                _detail("Runner", "bash run_step2_feature_engineering.sh"),
                _detail("Rows", training_snapshot.get("rows")),
                _detail("Codes", training_snapshot.get("code_count")),
                _detail("Date range", f"{training_snapshot.get('date_min') or '—'} to {training_snapshot.get('date_max') or '—'}"),
                _detail("Artifact", training_snapshot.get("path")),
            ],
        ),
        _build_runtime_step(
            step=3,
            key="inference_features",
            runner_script="bash run_step3_inference_features.sh",
            command_hint="python build_inference_features.py --data-dir quant_data --output quant_data/inference_features_latest.parquet",
            pid_file_names=["step3_inference_features.pid", "step4_inference_features.pid"],
            log_patterns=["step3_inference_features_*.log", "step4_inference_features_*.log"],
            name_prefixes=["aistockcn-step3-inference-features-", "aistockcn-step4-inference-features-"],
            exact_names=None,
            command_markers=["build_inference_features.py"],
            artifact_path=settings.quant_dir / "inference_features_latest.parquet",
            details=[
                _detail("Runner", "bash run_step3_inference_features.sh"),
                _detail("Rows", inference_snapshot.get("rows")),
                _detail("Codes", inference_snapshot.get("code_count")),
                _detail("Latest date", inference_snapshot.get("date_max")),
                _detail("Artifact", inference_snapshot.get("path")),
            ],
        ),
        _build_runtime_step(
            step=4,
            key="train_and_score",
            runner_script="bash run_step4_train_score.sh",
            command_hint="python train_lightgbm.py --train-path quant_data/ml_features_ready.parquet --inference-path quant_data/inference_features_latest.parquet --model-dir quant_data/models",
            pid_file_names=["step4_train_score.pid", "step5_train_score.pid"],
            log_patterns=["step4_train_score_*.log", "step5_train_score_*.log"],
            name_prefixes=["aistockcn-step4-train-score-", "aistockcn-step5-train-score-"],
            exact_names=None,
            command_markers=["train_lightgbm.py"],
            artifact_path=settings.models_dir / "inference_scores_latest.parquet",
            details=[
                _detail("Runner", "bash run_step4_train_score.sh"),
                _detail("Valid AUC", training_metrics.get("auc")),
                _detail("Train rows", training_metadata.get("train_rows")),
                _detail("Valid rows", training_metadata.get("valid_rows")),
                _detail("Score rows", score_snapshot.get("rows")),
                _detail("Score latest date", score_snapshot.get("date_max")),
            ],
        ),
        _build_runtime_step(
            step=5,
            key="backtest",
            runner_script="bash run_step5_backtest.sh",
            command_hint="python backtest_profile_runner.py --profile short_5d --sync-latest",
            pid_file_names=["step5_backtest.pid", "step6_backtest.pid"],
            log_patterns=["step5_backtest_*.log", "step6_backtest_*.log"],
            name_prefixes=["aistockcn-step5-backtest-", "aistockcn-step6-backtest-"],
            exact_names=None,
            command_markers=["backtest_profile_runner.py", "backtest_walk_forward.py"],
            artifact_path=settings.backtests_dir / "summary.json",
            details=[
                _detail("Runner", "bash run_step5_backtest.sh"),
                _detail("Profile", backtest_summary.get("profile_label") or backtest_summary.get("profile_name")),
                _detail("Rebalances", backtest_summary.get("num_rebalances")),
                _detail("Codes", backtest_summary.get("num_codes")),
                _detail("OOS AUC", backtest_metrics.get("auc")),
                _detail(
                    "Backtest range",
                    f"{backtest_summary.get('backtest_start') or '—'} to {backtest_summary.get('backtest_end') or '—'}",
                ),
                _detail("Summary file", str(settings.backtests_dir / "summary.json")),
            ],
        ),
        _build_paper_trading_step_runtime(),
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
    }
