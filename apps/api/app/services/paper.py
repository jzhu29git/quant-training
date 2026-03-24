from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.config import Settings, get_settings
from app.serializers import records_to_json, to_jsonable
from app.services.files import read_json
from app.services.paper_control import get_paper_trading_daemon_status


class PaperGatewayError(RuntimeError):
    pass


def _safe_read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, columns=columns)
    except (pa.ArrowException, OSError, ValueError):
        return pd.DataFrame()


def _path_snapshot(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows[-limit:]


class PaperGatewayClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.futu_gateway_base_url.rstrip("/")
        self.market = settings.futu_gateway_market
        self.account_id = settings.futu_gateway_account_id
        self.headers = {
            settings.futu_gateway_agent_id_header: settings.futu_gateway_agent_id,
            settings.futu_gateway_agent_key_header: settings.futu_gateway_agent_key or "",
        }

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query_params = {key: value for key, value in (params or {}).items() if value is not None and value != ""}
        query = f"?{urlencode(query_params)}" if query_params else ""
        request = Request(f"{self.base_url}{path}{query}", method=method, headers=self.headers)
        try:
            with urlopen(request, timeout=8) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PaperGatewayError(f"HTTP {exc.code} {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise PaperGatewayError("request timed out") from exc
        except URLError as exc:
            raise PaperGatewayError(str(exc.reason)) from exc
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise PaperGatewayError("gateway returned invalid JSON") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def sync(self) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/admin/sync",
            params={
                "market": self.market,
                "target_agent_id": get_settings().futu_gateway_agent_id,
                "account_id": self.account_id,
            },
        )

    def get_summary(self) -> dict[str, Any]:
        return dict(self._request("GET", "/v1/agents/me/summary", params={"market": self.market}).get("summary", {}))

    def get_positions(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/v1/agents/me/positions", params={"market": self.market}).get("positions", []))

    def get_orders(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/v1/agents/me/orders", params={"market": self.market}).get("orders", []))

    def get_balance(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/v1/balance", params={"market": self.market, "account_id": self.account_id}).get("balance", []))


def _gateway_status(settings: Settings) -> dict[str, Any]:
    client = PaperGatewayClient(settings)
    try:
        health = client.health()
        return {
            "configured": bool(settings.futu_gateway_base_url and settings.futu_gateway_agent_key),
            "healthy": str(health.get("status") or "").lower() == "ok",
            "base_url": settings.futu_gateway_base_url,
            "market": settings.futu_gateway_market,
            "agent_id": settings.futu_gateway_agent_id,
            "account_id": settings.futu_gateway_account_id,
            "details": health,
            "error": None,
        }
    except PaperGatewayError as exc:
        return {
            "configured": bool(settings.futu_gateway_base_url and settings.futu_gateway_agent_key),
            "healthy": False,
            "base_url": settings.futu_gateway_base_url,
            "market": settings.futu_gateway_market,
            "agent_id": settings.futu_gateway_agent_id,
            "account_id": settings.futu_gateway_account_id,
            "details": None,
            "error": str(exc),
        }


def _targets_snapshot(settings: Settings) -> dict[str, Any]:
    path = settings.paper_trading_targets_path
    snapshot = _path_snapshot(path)
    if snapshot is None:
        return {"path": str(path), "rows": 0, "latest_signal_date": None, "updated_at": None}
    try:
        parquet = pq.ParquetFile(path)
        tracked_columns = [column for column in ["signal_date", "code"] if column in parquet.schema.names]
        latest_signal_date = None
        if tracked_columns:
            tracked_df = parquet.read(columns=tracked_columns).to_pandas()
            if "signal_date" in tracked_df.columns:
                latest_signal_date = to_jsonable(pd.to_datetime(tracked_df["signal_date"], errors="coerce").max())
        return {
            "path": str(path),
            "rows": int(parquet.metadata.num_rows),
            "latest_signal_date": latest_signal_date,
            "updated_at": snapshot["updated_at"],
        }
    except (pa.ArrowException, OSError, ValueError):
        return {"path": str(path), "rows": 0, "latest_signal_date": None, "updated_at": snapshot["updated_at"]}


def get_paper_trading_status() -> dict[str, Any]:
    settings = get_settings()
    daemon_status = get_paper_trading_daemon_status()
    local_state = read_json(settings.paper_trading_state_path)
    history_tail = _jsonl_tail(settings.paper_trading_history_path, limit=5)
    return {
        "daemon": daemon_status,
        "gateway": _gateway_status(settings),
        "state": local_state,
        "targets": _targets_snapshot(settings),
        "history_tail": history_tail,
        "state_file": str(settings.paper_trading_state_path),
        "history_file": str(settings.paper_trading_history_path),
        "config": {
            "top_k": settings.paper_trading_top_k,
            "min_score": settings.paper_trading_min_score,
            "lot_size": settings.paper_trading_lot_size,
            "cash_buffer_pct": settings.paper_trading_cash_buffer_pct,
            "buy_limit_bps": settings.paper_trading_buy_limit_bps,
            "sell_limit_bps": settings.paper_trading_sell_limit_bps,
            "budget_total": settings.paper_trading_budget_total,
            "interval_seconds": settings.paper_trading_interval_seconds,
            "max_order_qty": settings.paper_trading_max_order_qty,
        },
    }


def get_paper_trading_overview() -> dict[str, Any]:
    settings = get_settings()
    status = get_paper_trading_status()
    client = PaperGatewayClient(settings)

    live_summary: dict[str, Any] | None = None
    live_positions: list[dict[str, Any]] = []
    live_orders: list[dict[str, Any]] = []
    live_balance: list[dict[str, Any]] = []
    live_error: str | None = None

    if status["gateway"]["healthy"]:
        try:
            client.sync()
        except PaperGatewayError:
            pass
        try:
            live_summary = client.get_summary()
            live_positions = client.get_positions()
            live_orders = client.get_orders()
            live_balance = client.get_balance()
        except PaperGatewayError as exc:
            live_error = str(exc)
    else:
        live_error = status["gateway"].get("error")

    return {
        **status,
        "live_summary": live_summary,
        "live_positions_count": len(live_positions),
        "live_orders_count": len(live_orders),
        "balance_rows": len(live_balance),
        "live_error": live_error,
    }


def get_paper_trading_targets(*, limit: int = 25) -> dict[str, Any]:
    settings = get_settings()
    targets_df = _safe_read_parquet(settings.paper_trading_targets_path)
    if targets_df.empty:
        return {"rows": 0, "targets": []}
    ordered_columns = [
        column
        for column in [
            "signal_date",
            "rank",
            "code",
            "name",
            "industry",
            "score",
            "close",
            "target_qty",
            "current_qty",
            "delta_qty",
            "buy_order_qty",
            "sell_order_qty",
            "action",
            "buy_limit_price",
            "sell_limit_price",
            "sent_price",
            "sent_status",
            "sent_order_id",
            "sent_error",
            "estimated_order_notional",
            "reason",
        ]
        if column in targets_df.columns
    ]
    if "score" in targets_df.columns:
        targets_df = targets_df.sort_values(["score", "rank"], ascending=[False, True], na_position="last")
    return {
        "rows": int(len(targets_df)),
        "targets": records_to_json(targets_df.head(limit)[ordered_columns].to_dict(orient="records")),
    }


def get_paper_trading_positions(*, limit: int = 50) -> dict[str, Any]:
    settings = get_settings()
    client = PaperGatewayClient(settings)
    try:
        positions = client.get_positions()
        return {"rows": len(positions), "positions": records_to_json(positions[:limit]), "error": None}
    except PaperGatewayError as exc:
        return {"rows": 0, "positions": [], "error": str(exc)}


def get_paper_trading_orders(*, limit: int = 50) -> dict[str, Any]:
    settings = get_settings()
    client = PaperGatewayClient(settings)
    try:
        client.sync()
    except PaperGatewayError:
        pass
    try:
        orders = client.get_orders()
        orders = sorted(
            orders,
            key=lambda row: str(row.get("updated_at") or row.get("create_time") or row.get("created_at") or ""),
            reverse=True,
        )
        return {"rows": len(orders), "orders": records_to_json(orders[:limit]), "error": None}
    except PaperGatewayError as exc:
        return {"rows": 0, "orders": [], "error": str(exc)}


def get_paper_trading_history(*, limit: int = 50) -> dict[str, Any]:
    settings = get_settings()
    rows = _jsonl_tail(settings.paper_trading_history_path, limit=limit)
    return {"rows": len(rows), "history": rows}
