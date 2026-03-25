from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    host_project_root: Path
    state_file: Path
    run_dir: Path
    logs_dir: Path
    quant_dir: Path
    stock_list_path: Path
    stock_registry_path: Path
    stock_list_subset_path: Path
    models_dir: Path
    backtests_dir: Path
    paper_trading_dir: Path
    paper_trading_state_path: Path
    paper_trading_targets_path: Path
    paper_trading_history_path: Path
    panel_admin_key: str | None
    panel_api_allowed_cidrs: tuple[str, ...]
    panel_api_allowed_service_names: tuple[str, ...]
    futu_gateway_base_url: str
    futu_gateway_market: str
    futu_gateway_agent_id: str
    futu_gateway_agent_key: str | None
    futu_gateway_agent_id_header: str
    futu_gateway_agent_key_header: str
    futu_gateway_account_id: int | None
    paper_trading_top_k: int
    paper_trading_min_score: float
    paper_trading_lot_size: int
    paper_trading_cash_buffer_pct: float
    paper_trading_buy_limit_bps: float
    paper_trading_sell_limit_bps: float
    paper_trading_budget_total: float | None
    paper_trading_interval_seconds: int
    paper_trading_max_order_qty: int
    pipeline_auto_run_enabled: bool
    pipeline_auto_run_timezone: str
    pipeline_auto_run_time: str
    pipeline_auto_run_poll_seconds: int
    pipeline_auto_run_state_path: Path


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _optional_float_env(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _optional_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


@lru_cache
def get_settings() -> Settings:
    project_root_env = os.getenv("PROJECT_ROOT")
    if project_root_env:
        project_root = Path(project_root_env).resolve()
    else:
        project_root = Path(__file__).resolve().parents[3]
    host_project_root_env = os.getenv("HOST_PROJECT_ROOT")
    host_project_root = Path(host_project_root_env).resolve() if host_project_root_env else project_root
    quant_dir = project_root / "quant_data"
    paper_trading_dir = quant_dir / "paper_trading"
    return Settings(
        project_root=project_root,
        host_project_root=host_project_root,
        state_file=quant_dir / "batch_state" / "all_a_3y_state.json",
        run_dir=project_root / "run",
        logs_dir=project_root / "logs",
        quant_dir=quant_dir,
        stock_list_path=quant_dir / "stock_list.parquet",
        stock_registry_path=quant_dir / "stock_registry.parquet",
        stock_list_subset_path=quant_dir / "stock_list_subset.parquet",
        models_dir=quant_dir / "models",
        backtests_dir=quant_dir / "backtests",
        paper_trading_dir=paper_trading_dir,
        paper_trading_state_path=paper_trading_dir / "state.json",
        paper_trading_targets_path=paper_trading_dir / "targets_latest.parquet",
        paper_trading_history_path=paper_trading_dir / "sync_history.jsonl",
        panel_admin_key=os.getenv("PANEL_ADMIN_KEY"),
        panel_api_allowed_cidrs=_csv_env(
            "PANEL_API_ALLOWED_CIDRS",
            ("127.0.0.1/32", "::1/128"),
        ),
        panel_api_allowed_service_names=_csv_env(
            "PANEL_API_ALLOWED_SERVICE_NAMES",
            ("panel-web",),
        ),
        futu_gateway_base_url=os.getenv("FUTU_GATEWAY_BASE_URL", "http://127.0.0.1:8080").strip() or "http://127.0.0.1:8080",
        futu_gateway_market=(os.getenv("FUTU_GATEWAY_MARKET", "CN").strip() or "CN").upper(),
        futu_gateway_agent_id=os.getenv("FUTU_GATEWAY_AGENT_ID", "aistockcn-paper-cn").strip() or "aistockcn-paper-cn",
        futu_gateway_agent_key=(os.getenv("FUTU_GATEWAY_AGENT_KEY", "local-dev-agent-key") or "").strip() or None,
        futu_gateway_agent_id_header=os.getenv("FUTU_GATEWAY_AGENT_ID_HEADER", "X-Agent-Id").strip() or "X-Agent-Id",
        futu_gateway_agent_key_header=os.getenv("FUTU_GATEWAY_AGENT_KEY_HEADER", "X-Agent-Key").strip() or "X-Agent-Key",
        futu_gateway_account_id=_optional_int_env("FUTU_GATEWAY_ACCOUNT_ID"),
        paper_trading_top_k=max(_int_env("PAPER_TRADING_TOP_K", 5), 1),
        paper_trading_min_score=_float_env("PAPER_TRADING_MIN_SCORE", 0.5),
        paper_trading_lot_size=max(_int_env("PAPER_TRADING_LOT_SIZE", 100), 1),
        paper_trading_cash_buffer_pct=max(min(_float_env("PAPER_TRADING_CASH_BUFFER_PCT", 0.02), 0.95), 0.0),
        paper_trading_buy_limit_bps=max(_float_env("PAPER_TRADING_BUY_LIMIT_BPS", 50.0), 0.0),
        paper_trading_sell_limit_bps=max(_float_env("PAPER_TRADING_SELL_LIMIT_BPS", 50.0), 0.0),
        paper_trading_budget_total=_optional_float_env("PAPER_TRADING_BUDGET_TOTAL"),
        paper_trading_interval_seconds=max(_int_env("PAPER_TRADING_INTERVAL_SECONDS", 300), 30),
        paper_trading_max_order_qty=max(_int_env("PAPER_TRADING_MAX_ORDER_QTY", 1000), 1),
        pipeline_auto_run_enabled=_bool_env("PIPELINE_AUTO_RUN_ENABLED", False),
        pipeline_auto_run_timezone=os.getenv("PIPELINE_AUTO_RUN_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
        pipeline_auto_run_time=os.getenv("PIPELINE_AUTO_RUN_TIME", "18:00").strip() or "18:00",
        pipeline_auto_run_poll_seconds=max(_int_env("PIPELINE_AUTO_RUN_POLL_SECONDS", 60), 15),
        pipeline_auto_run_state_path=project_root / "run" / "pipeline_auto_run_state.json",
    )
