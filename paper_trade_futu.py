#!/usr/bin/env python3
"""Reconcile latest model picks with a Futu gateway paper-trading agent."""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


DEFAULT_SCORES_PATH = "quant_data/models/inference_scores_latest.parquet"
DEFAULT_STATE_DIR = "quant_data/paper_trading"
DEFAULT_MARKET = "CN"
DEFAULT_GATEWAY_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_AGENT_ID = "aistockcn-paper-cn"
DEFAULT_AGENT_KEY = "local-dev-agent-key"
DEFAULT_AGENT_ID_HEADER = "X-Agent-Id"
DEFAULT_AGENT_KEY_HEADER = "X-Agent-Key"
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.5
DEFAULT_LOT_SIZE = 100
DEFAULT_CASH_BUFFER_PCT = 0.02
DEFAULT_BUY_LIMIT_BPS = 50.0
DEFAULT_SELL_LIMIT_BPS = 50.0
DEFAULT_MAX_ORDER_QTY = 1000

TERMINAL_ORDER_STATUSES = {
    "CANCELLED",
    "CANCELLED_ALL",
    "CANCELLED_PART",
    "CANCELLED_PART_ALL",
    "DELETED",
    "DISABLED",
    "EXPIRED",
    "FAILED",
    "FILLED_ALL",
    "REJECTED",
    "SUBMIT_FAILED",
}

PRICE_LIMIT_ERROR_TEXT = "报单价格不在涨跌停区间"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_date_text(value: Any) -> str | None:
    if value in (None, "", "NaT"):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return str(pd.Timestamp(parsed).date())


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # pragma: no cover - defensive fallback
            return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=json_default) + "\n")


def normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        return text.split(".", 1)[-1]
    return text.zfill(6) if text.isdigit() else text


def normalize_status(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    for old, new in [("-", "_"), (" ", "_"), ("/", "_")]:
        text = text.replace(old, new)
    return text


def is_active_order(status: Any) -> bool:
    normalized = normalize_status(status)
    return bool(normalized) and normalized not in TERMINAL_ORDER_STATUSES


def to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "N/A"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def round_price(value: float) -> float:
    return round(float(value), 2)


def clamp_non_negative(value: float) -> float:
    return max(float(value), 0.0)


def build_price(base_price: float, side: str, *, buy_limit_bps: float, sell_limit_bps: float) -> float:
    if base_price <= 0:
        return 0.0
    if side == "BUY":
        return round_price(base_price * (1.0 + buy_limit_bps / 10_000.0))
    return round_price(base_price * (1.0 - sell_limit_bps / 10_000.0))


def is_price_limit_error(message: str) -> bool:
    return PRICE_LIMIT_ERROR_TEXT in str(message or "")


def candidate_prices(row: pd.Series, primary_field: str) -> list[float]:
    prices: list[float] = []
    for field in [primary_field, "close", "current_last_price", "current_avg_cost"]:
        if field not in row:
            continue
        price = round_price(to_float(row.get(field)))
        if price <= 0:
            continue
        if any(abs(existing - price) < 0.0001 for existing in prices):
            continue
        prices.append(price)
    return prices


def choose_balance_record(records: list[dict[str, Any]], account_id: int | None) -> dict[str, Any]:
    if not records:
        return {}
    if account_id is None:
        return records[0]
    for record in records:
        if str(record.get("acc_id") or record.get("account_id") or "") == str(account_id):
            return record
    return records[0]


def extract_balance_metrics(records: list[dict[str, Any]], account_id: int | None) -> dict[str, float | str | None]:
    record = choose_balance_record(records, account_id)
    power_keys = ["power", "buying_power", "max_power_short", "available_funds", "avl_withdrawal_cash"]
    cash_keys = ["cash", "cash_balance", "cash_and_cash_equivalents", "available_cash", "withdraw_cash"]
    asset_keys = ["total_assets", "total_asset", "assets", "net_assets", "market_val"]

    def first(keys: list[str]) -> float:
        for key in keys:
            if key in record:
                value = to_float(record.get(key), default=float("nan"))
                if not math.isnan(value):
                    return value
        return 0.0

    return {
        "power": first(power_keys),
        "cash": first(cash_keys),
        "total_assets": first(asset_keys),
        "currency": str(record.get("currency") or record.get("base_currency") or DEFAULT_MARKET),
    }


def score_file_signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


@dataclass(frozen=True)
class SyncConfig:
    scores_path: Path
    state_dir: Path
    gateway_base_url: str
    market: str
    agent_id: str
    agent_key: str
    agent_id_header: str
    agent_key_header: str
    account_id: int | None
    top_k: int
    min_score: float
    lot_size: int
    cash_buffer_pct: float
    buy_limit_bps: float
    sell_limit_bps: float
    budget_total: float | None
    max_order_qty: int
    cancel_open_orders: bool
    sync_existing_orders: bool
    force: bool
    dry_run: bool


class GatewayError(RuntimeError):
    pass


class GatewayClient:
    def __init__(self, config: SyncConfig) -> None:
        self.base_url = config.gateway_base_url.rstrip("/")
        self.agent_id = config.agent_id
        self.agent_key = config.agent_key
        self.agent_id_header = config.agent_id_header
        self.agent_key_header = config.agent_key_header
        self.market = config.market
        self.account_id = config.account_id

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers = {
            self.agent_id_header: self.agent_id,
            self.agent_key_header: self.agent_key,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query_params = {key: value for key, value in (params or {}).items() if value is not None and value != ""}
        query = f"?{urlencode(query_params)}" if query_params else ""
        data = None
        headers = self._headers()
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers = self._headers(content_type="application/json")
        request = Request(f"{self.base_url}{path}{query}", data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GatewayError(f"gateway {method} {path} failed: HTTP {exc.code} {detail}") from exc
        except URLError as exc:
            raise GatewayError(f"gateway {method} {path} failed: {exc.reason}") from exc
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise GatewayError(f"gateway {method} {path} returned invalid JSON") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def sync_agent(self) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/admin/sync",
            params={
                "market": self.market,
                "target_agent_id": self.agent_id,
                "account_id": self.account_id,
            },
        )

    def get_balance(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/v1/balance", params={"market": self.market, "account_id": self.account_id}).get("balance", []))

    def get_agent_summary(self) -> dict[str, Any]:
        return dict(self._request("GET", "/v1/agents/me/summary", params={"market": self.market}).get("summary", {}))

    def get_agent_positions(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/v1/agents/me/positions", params={"market": self.market}).get("positions", []))

    def get_agent_orders(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/v1/agents/me/orders", params={"market": self.market}).get("orders", []))

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        remark: str,
    ) -> dict[str, Any]:
        payload = {
            "market": self.market,
            "symbol": symbol,
            "side": side,
            "order_type": "NORMAL",
            "quantity": quantity,
            "price": price,
            "remark": remark[:128],
        }
        response = self._request("POST", "/v1/orders", params={"account_id": self.account_id}, payload=payload)
        return dict(response.get("order", {}))

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        payload = {"market": self.market, "order_id": str(order_id)}
        response = self._request("POST", "/v1/orders/cancel", params={"account_id": self.account_id}, payload=payload)
        return dict(response.get("order", {}))


def load_latest_scores(config: SyncConfig) -> tuple[pd.DataFrame, str, str]:
    columns = ["date", "code", "exchange", "name", "industry", "score", "close"]
    scores = pd.read_parquet(config.scores_path, columns=columns)
    if scores.empty:
        raise RuntimeError("inference_scores_latest.parquet is empty")
    scores["date"] = pd.to_datetime(scores["date"], errors="coerce")
    if scores["date"].isna().all():
        raise RuntimeError("latest score file has no valid dates")
    scores["code"] = scores["code"].astype(str).str.zfill(6)
    latest_date = pd.Timestamp(scores["date"].max()).normalize()
    latest_text = str(latest_date.date())
    latest_scores = scores[scores["date"].dt.normalize() == latest_date].copy()
    latest_scores["score"] = pd.to_numeric(latest_scores["score"], errors="coerce")
    latest_scores["close"] = pd.to_numeric(latest_scores["close"], errors="coerce")
    latest_scores = latest_scores.dropna(subset=["score", "close"])
    latest_scores = latest_scores[latest_scores["score"] >= config.min_score].sort_values("score", ascending=False).head(config.top_k)
    if latest_scores.empty:
        raise RuntimeError(f"no candidates reached score >= {config.min_score} on {latest_text}")
    latest_scores = latest_scores.reset_index(drop=True)
    latest_scores["rank"] = latest_scores.index + 1
    return latest_scores, latest_text, score_file_signature(config.scores_path)


def ensure_dirs(state_dir: Path) -> dict[str, Path]:
    state_dir.mkdir(parents=True, exist_ok=True)
    return {
        "state": state_dir / "state.json",
        "targets": state_dir / "targets_latest.parquet",
        "history": state_dir / "sync_history.jsonl",
    }


def update_state(paths: dict[str, Path], **updates: Any) -> dict[str, Any]:
    state = read_json(paths["state"])
    state.update(updates)
    state["updated_at"] = now_iso()
    write_json(paths["state"], state)
    return state


def normalize_positions(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = normalize_symbol(row.get("symbol") or row.get("code"))
        if not symbol:
            continue
        normalized[symbol] = {
            **row,
            "symbol": symbol,
            "quantity": int(round(to_float(row.get("quantity")))),
            "avg_cost": to_float(row.get("avg_cost")),
            "last_price": to_float(row.get("last_price")),
            "market_value": to_float(row.get("market_value")),
            "realized_pnl": to_float(row.get("realized_pnl")),
            "unrealized_pnl": to_float(row.get("unrealized_pnl")),
        }
    return normalized


def normalize_orders(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                **row,
                "broker_order_id": str(row.get("broker_order_id") or row.get("order_id") or ""),
                "symbol": normalize_symbol(row.get("symbol") or row.get("code")),
                "order_status": normalize_status(row.get("order_status")),
                "side": str(row.get("side") or row.get("trd_side") or "").upper(),
                "quantity": int(round(to_float(row.get("quantity") or row.get("qty")))),
                "price": to_float(row.get("price")),
                "dealt_qty": to_float(row.get("dealt_qty")),
                "updated_at": str(row.get("updated_at") or row.get("create_time") or ""),
            }
        )
    return normalized


def determine_total_capital(
    config: SyncConfig,
    *,
    balance_metrics: dict[str, float | str | None],
    current_market_value: float,
) -> float:
    if config.budget_total is not None and config.budget_total > 0:
        return config.budget_total
    total_assets = to_float(balance_metrics.get("total_assets"))
    if total_assets > 0:
        return total_assets
    cash = max(to_float(balance_metrics.get("power")), to_float(balance_metrics.get("cash")))
    return cash + current_market_value


def buy_capacity(
    config: SyncConfig,
    *,
    balance_metrics: dict[str, float | str | None],
    current_market_value: float,
    planned_sale_notional: float,
) -> float:
    if config.budget_total is not None and config.budget_total > 0:
        remaining = config.budget_total - current_market_value + planned_sale_notional
        return clamp_non_negative(remaining)
    power = max(to_float(balance_metrics.get("power")), to_float(balance_metrics.get("cash")))
    return clamp_non_negative(power + planned_sale_notional)


def compute_order_quantity(
    *,
    side: str,
    raw_quantity: int,
    lot_size: int,
    full_exit: bool = False,
) -> int:
    quantity = int(max(raw_quantity, 0))
    if quantity <= 0:
        return 0
    if side == "SELL" and full_exit:
        return quantity
    lots = quantity // max(lot_size, 1)
    return lots * max(lot_size, 1)


def build_plan(
    config: SyncConfig,
    *,
    latest_scores: pd.DataFrame,
    positions: dict[str, dict[str, Any]],
    balance_metrics: dict[str, float | str | None],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    current_market_value = sum(to_float(item.get("market_value")) for item in positions.values())
    total_capital = determine_total_capital(config, balance_metrics=balance_metrics, current_market_value=current_market_value)
    investable_capital = clamp_non_negative(total_capital * (1.0 - config.cash_buffer_pct))
    target_count = int(len(latest_scores))
    target_value = investable_capital / target_count if target_count else 0.0

    score_lookup: dict[str, dict[str, Any]] = {}
    plan_rows: list[dict[str, Any]] = []
    target_symbols: list[str] = []
    for _, row in latest_scores.iterrows():
        symbol = normalize_symbol(row["code"])
        target_symbols.append(symbol)
        score_row = row.to_dict()
        score_lookup[symbol] = score_row
        current = positions.get(symbol, {})
        current_qty = int(round(to_float(current.get("quantity"))))
        close_price = to_float(row["close"])
        buy_price = build_price(close_price, "BUY", buy_limit_bps=config.buy_limit_bps, sell_limit_bps=config.sell_limit_bps)
        sell_price = build_price(close_price, "SELL", buy_limit_bps=config.buy_limit_bps, sell_limit_bps=config.sell_limit_bps)
        theoretical_qty = int(target_value / buy_price) if buy_price > 0 else 0
        target_qty = compute_order_quantity(side="BUY", raw_quantity=theoretical_qty, lot_size=config.lot_size)
        plan_rows.append(
            {
                "signal_date": normalize_date_text(row["date"]),
                "rank": int(score_row["rank"]),
                "code": symbol,
                "exchange": str(row.get("exchange") or ""),
                "name": str(row.get("name") or ""),
                "industry": str(row.get("industry") or ""),
                "score": to_float(row.get("score")),
                "close": close_price,
                "buy_limit_price": buy_price,
                "sell_limit_price": sell_price,
                "target_weight": 1.0 / target_count if target_count else 0.0,
                "target_value": target_value,
                "target_qty": target_qty,
                "current_qty": current_qty,
                "delta_qty": target_qty - current_qty,
                "current_market_value": to_float(current.get("market_value")),
                "current_avg_cost": to_float(current.get("avg_cost")),
                "current_last_price": to_float(current.get("last_price")),
                "reason": "ranked_target",
            }
        )

    for symbol, current in positions.items():
        if symbol in score_lookup:
            continue
        current_qty = int(round(to_float(current.get("quantity"))))
        if current_qty <= 0:
            continue
        base_price = to_float(current.get("last_price")) or to_float(current.get("avg_cost"))
        plan_rows.append(
            {
                "signal_date": normalize_date_text(latest_scores["date"].iloc[0]),
                "rank": None,
                "code": symbol,
                "exchange": "",
                "name": str(current.get("symbol") or symbol),
                "industry": "",
                "score": None,
                "close": base_price,
                "buy_limit_price": build_price(base_price, "BUY", buy_limit_bps=config.buy_limit_bps, sell_limit_bps=config.sell_limit_bps),
                "sell_limit_price": build_price(base_price, "SELL", buy_limit_bps=config.buy_limit_bps, sell_limit_bps=config.sell_limit_bps),
                "target_weight": 0.0,
                "target_value": 0.0,
                "target_qty": 0,
                "current_qty": current_qty,
                "delta_qty": -current_qty,
                "current_market_value": to_float(current.get("market_value")),
                "current_avg_cost": to_float(current.get("avg_cost")),
                "current_last_price": to_float(current.get("last_price")),
                "reason": "exit_non_target",
            }
        )

    plan = pd.DataFrame(plan_rows)
    if plan.empty:
        raise RuntimeError("rebalance plan is empty")

    plan["sell_qty"] = plan["delta_qty"].apply(lambda value: abs(int(value)) if value < 0 else 0)
    plan["buy_qty"] = plan["delta_qty"].apply(lambda value: int(value) if value > 0 else 0)
    plan["action"] = "HOLD"
    plan.loc[plan["sell_qty"] > 0, "action"] = "SELL"
    plan.loc[(plan["sell_qty"] == 0) & (plan["buy_qty"] > 0), "action"] = "BUY"

    plan["sell_order_qty"] = plan.apply(
        lambda row: compute_order_quantity(
            side="SELL",
            raw_quantity=int(row["sell_qty"]),
            lot_size=config.lot_size,
            full_exit=int(row["target_qty"]) == 0 and int(row["current_qty"]) > 0,
        ),
        axis=1,
    )
    plan["buy_order_qty"] = plan.apply(
        lambda row: compute_order_quantity(side="BUY", raw_quantity=int(row["buy_qty"]), lot_size=config.lot_size),
        axis=1,
    )

    planned_sale_notional = float((plan["sell_order_qty"] * plan["sell_limit_price"]).sum())
    remaining_buy_capacity = buy_capacity(
        config,
        balance_metrics=balance_metrics,
        current_market_value=current_market_value,
        planned_sale_notional=planned_sale_notional,
    )

    for index, row in plan.sort_values(["rank", "score"], ascending=[True, False], na_position="last").iterrows():
        buy_qty = int(row["buy_order_qty"])
        if buy_qty <= 0:
            continue
        max_notional = remaining_buy_capacity
        price = to_float(row["buy_limit_price"])
        if price <= 0:
            plan.at[index, "buy_order_qty"] = 0
            plan.at[index, "action"] = "SKIP_INVALID_PRICE"
            continue
        affordable_qty = compute_order_quantity(
            side="BUY",
            raw_quantity=int(max_notional / price),
            lot_size=config.lot_size,
        )
        actual_qty = min(buy_qty, affordable_qty, config.max_order_qty)
        if actual_qty <= 0:
            plan.at[index, "buy_order_qty"] = 0
            plan.at[index, "action"] = "SKIP_NO_CASH"
            continue
        plan.at[index, "buy_order_qty"] = actual_qty
        remaining_buy_capacity -= actual_qty * price

    plan["estimated_order_notional"] = 0.0
    sell_mask = plan["sell_order_qty"] > 0
    buy_mask = plan["buy_order_qty"] > 0
    plan.loc[sell_mask, "estimated_order_notional"] = plan.loc[sell_mask, "sell_order_qty"] * plan.loc[sell_mask, "sell_limit_price"]
    plan.loc[buy_mask, "estimated_order_notional"] = plan.loc[buy_mask, "buy_order_qty"] * plan.loc[buy_mask, "buy_limit_price"]

    summary = {
        "target_symbols": target_symbols,
        "target_count": target_count,
        "current_market_value": current_market_value,
        "total_capital": total_capital,
        "investable_capital": investable_capital,
        "planned_sale_notional": planned_sale_notional,
        "buy_capacity": buy_capacity(
            config,
            balance_metrics=balance_metrics,
            current_market_value=current_market_value,
            planned_sale_notional=planned_sale_notional,
        ),
        "sell_order_count": int((plan["sell_order_qty"] > 0).sum()),
        "buy_order_count": int((plan["buy_order_qty"] > 0).sum()),
        "skip_count": int(plan["action"].astype(str).str.startswith("SKIP_").sum()),
    }
    return plan, summary


def persist_targets(paths: dict[str, Path], plan: pd.DataFrame) -> None:
    ordered_cols = [
        "signal_date",
        "rank",
        "code",
        "exchange",
        "name",
        "industry",
        "score",
        "close",
        "buy_limit_price",
        "sell_limit_price",
        "target_weight",
        "target_value",
        "target_qty",
        "current_qty",
        "delta_qty",
        "sell_order_qty",
        "buy_order_qty",
        "action",
        "sent_order_id",
        "sent_status",
        "sent_price",
        "sent_error",
        "estimated_order_notional",
        "reason",
        "current_market_value",
        "current_avg_cost",
        "current_last_price",
    ]
    available_cols = [column for column in ordered_cols if column in plan.columns]
    plan.loc[:, available_cols].sort_values(["rank", "score"], ascending=[True, False], na_position="last").to_parquet(
        paths["targets"],
        index=False,
    )


def execute_plan(
    client: GatewayClient,
    config: SyncConfig,
    *,
    plan: pd.DataFrame,
    signal_date: str,
    active_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    cancelled_orders: list[dict[str, Any]] = []
    placed_orders: list[dict[str, Any]] = []
    skipped_orders: list[dict[str, Any]] = []

    if config.cancel_open_orders:
        for order in active_orders:
            order_id = str(order.get("broker_order_id") or order.get("order_id") or "").strip()
            if not order_id:
                continue
            cancelled_orders.append(client.cancel_order(order_id))

    execution_rows = plan.copy()
    execution_rows["sent_order_id"] = None
    execution_rows["sent_status"] = None
    execution_rows["sent_price"] = None
    execution_rows["sent_error"] = None

    sell_rows = execution_rows[execution_rows["sell_order_qty"] > 0].sort_values(["score", "rank"], ascending=[True, True], na_position="last")
    buy_rows = execution_rows[execution_rows["buy_order_qty"] > 0].sort_values(["rank", "score"], ascending=[True, False], na_position="last")

    for side, rows, qty_col, price_col in [
        ("SELL", sell_rows, "sell_order_qty", "sell_limit_price"),
        ("BUY", buy_rows, "buy_order_qty", "buy_limit_price"),
    ]:
        for index, row in rows.iterrows():
            quantity = int(row[qty_col])
            if quantity <= 0:
                continue
            quantity = min(quantity, config.max_order_qty)
            prices = candidate_prices(row, price_col)
            if not prices:
                continue
            remark = f"aistock sig={signal_date} r={row['rank'] or '-'}"
            last_error: str | None = None
            for price in prices:
                try:
                    order = client.place_order(
                        symbol=str(row["code"]),
                        side=side,
                        quantity=quantity,
                        price=price,
                        remark=remark,
                    )
                    execution_rows.at[index, "sent_order_id"] = str(order.get("order_id") or order.get("broker_order_id") or "")
                    execution_rows.at[index, "sent_status"] = str(order.get("order_status") or "")
                    execution_rows.at[index, "sent_price"] = price
                    placed_orders.append(order)
                    last_error = None
                    break
                except GatewayError as exc:
                    last_error = str(exc)
                    if is_price_limit_error(last_error):
                        continue
                    raise

            if last_error:
                execution_rows.at[index, "sent_status"] = "SKIPPED_PRICE_LIMIT"
                execution_rows.at[index, "sent_error"] = last_error
                execution_rows.at[index, "action"] = "SKIP_PRICE_LIMIT"
                skipped_orders.append(
                    {
                        "symbol": str(row["code"]),
                        "side": side,
                        "quantity": quantity,
                        "attempted_prices": prices,
                        "error": last_error,
                    }
                )
                print(
                    f"skip {side} {row['code']} qty={quantity} after price retries {prices}: {last_error}",
                    file=sys.stderr,
                    flush=True,
                )

    return {
        "execution_rows": execution_rows,
        "cancelled_orders": cancelled_orders,
        "placed_orders": placed_orders,
        "skipped_orders": skipped_orders,
    }


def sync_once(config: SyncConfig) -> tuple[int, dict[str, Any]]:
    paths = ensure_dirs(config.state_dir)
    state = read_json(paths["state"])
    gateway = GatewayClient(config)
    last_signal_date = None
    try:
        latest_scores, signal_date, signature = load_latest_scores(config)
        last_signal_date = signal_date
        previous_signature = str(state.get("last_score_signature") or "")

        health_payload = gateway.health()
        health_ok = str(health_payload.get("status") or "").lower() == "ok"

        if config.sync_existing_orders:
            try:
                gateway.sync_agent()
            except GatewayError:
                # The sync endpoint is helpful but not critical enough to block order planning.
                pass

        positions = normalize_positions(gateway.get_agent_positions())
        orders = normalize_orders(gateway.get_agent_orders())
        active_orders = [row for row in orders if is_active_order(row.get("order_status"))]
        balance_rows = gateway.get_balance()
        balance_metrics = extract_balance_metrics(balance_rows, config.account_id)
        live_summary = gateway.get_agent_summary()

        plan, plan_summary = build_plan(
            config,
            latest_scores=latest_scores,
            positions=positions,
            balance_metrics=balance_metrics,
        )

        if not config.force and previous_signature == signature:
            has_pending_actions = bool(plan_summary.get("buy_order_count")) or bool(plan_summary.get("sell_order_count"))
            noop_message: str | None
            if active_orders:
                noop_message = f"score snapshot {signal_date} is unchanged and {len(active_orders)} active orders are still working"
            elif not has_pending_actions:
                noop_message = f"score snapshot {signal_date} is unchanged and portfolio is already aligned"
            else:
                noop_message = None

            if noop_message is not None:
                summary = {
                    "status": "noop",
                    "message": noop_message,
                    "score_signal_date": signal_date,
                    "last_score_signature": signature,
                    "gateway_healthy": health_ok,
                    "plan_summary": plan_summary,
                    "live_summary": live_summary,
                    "active_order_count": len(active_orders),
                    "position_count": len(positions),
                    "cancelled_order_ids": [],
                    "placed_order_ids": [],
                    "skipped_symbols": [],
                }
                updated = update_state(
                    paths,
                    strategy="futu_gateway_auto_paper_trading",
                    market=config.market,
                    agent_id=config.agent_id,
                    gateway_base_url=config.gateway_base_url,
                    config_snapshot={
                        "top_k": config.top_k,
                        "min_score": config.min_score,
                        "lot_size": config.lot_size,
                        "cash_buffer_pct": config.cash_buffer_pct,
                        "buy_limit_bps": config.buy_limit_bps,
                        "sell_limit_bps": config.sell_limit_bps,
                        "budget_total": config.budget_total,
                    },
                    last_attempt_at=now_iso(),
                    last_status="noop",
                    last_message=summary["message"],
                    score_signal_date=signal_date,
                    last_score_signature=signature,
                    last_error=None,
                    last_traceback=None,
                    gateway_healthy=health_ok,
                    live_summary=live_summary,
                    balance_metrics=balance_metrics,
                    plan_summary=plan_summary,
                    active_order_count=len(active_orders),
                    position_count=len(positions),
                    cancelled_order_ids=[],
                    placed_order_ids=[],
                    skipped_symbols=[],
                )
                append_jsonl(paths["history"], {**summary, "recorded_at": now_iso()})
                return 0, updated

        if config.dry_run:
            persist_targets(paths, plan)
            result = {
                "status": "dry_run",
                "message": f"dry run built a rebalance plan for {signal_date}",
                "score_signal_date": signal_date,
                "last_score_signature": signature,
                "gateway_healthy": health_ok,
                "plan_summary": plan_summary,
                "live_summary": live_summary,
                "active_order_count": len(active_orders),
                "position_count": len(positions),
            }
            updated = update_state(
                paths,
                strategy="futu_gateway_auto_paper_trading",
                market=config.market,
                agent_id=config.agent_id,
                gateway_base_url=config.gateway_base_url,
                config_snapshot={
                    "top_k": config.top_k,
                    "min_score": config.min_score,
                    "lot_size": config.lot_size,
                    "cash_buffer_pct": config.cash_buffer_pct,
                    "buy_limit_bps": config.buy_limit_bps,
                    "sell_limit_bps": config.sell_limit_bps,
                    "budget_total": config.budget_total,
                },
                last_attempt_at=now_iso(),
                last_status="dry_run",
                last_message=result["message"],
                score_signal_date=signal_date,
                last_score_signature=signature,
                last_error=None,
                last_traceback=None,
                last_success_at=now_iso(),
                gateway_healthy=health_ok,
                live_summary=live_summary,
                balance_metrics=balance_metrics,
                plan_summary=plan_summary,
                active_order_count=len(active_orders),
                position_count=len(positions),
            )
            append_jsonl(paths["history"], {**result, "recorded_at": now_iso()})
            return 0, updated

        execution = execute_plan(
            gateway,
            config,
            plan=plan,
            signal_date=signal_date,
            active_orders=active_orders,
        )
        execution_rows = execution["execution_rows"]
        persist_targets(paths, execution_rows)

        try:
            gateway.sync_agent()
        except GatewayError:
            pass

        live_summary = gateway.get_agent_summary()
        refreshed_orders = normalize_orders(gateway.get_agent_orders())
        execution_skip_count = len(execution.get("skipped_orders", []))
        plan_summary = {**plan_summary, "execution_skip_count": execution_skip_count}
        skipped_symbols = [str(item.get("symbol") or "") for item in execution.get("skipped_orders", []) if item]
        message = (
            f"rebalance synced for {signal_date}: "
            f"{len(execution['cancelled_orders'])} cancellations, "
            f"{len(execution['placed_orders'])} new orders"
        )
        if skipped_symbols:
            message += f", skipped {len(skipped_symbols)} symbols ({', '.join(skipped_symbols)})"
        result = {
            "status": "success",
            "message": message,
            "score_signal_date": signal_date,
            "last_score_signature": signature,
            "gateway_healthy": health_ok,
            "plan_summary": plan_summary,
            "live_summary": live_summary,
            "active_order_count": len([row for row in refreshed_orders if is_active_order(row.get('order_status'))]),
            "position_count": len(positions),
            "cancelled_order_ids": [
                str(item.get("order_id") or item.get("broker_order_id") or "")
                for item in execution["cancelled_orders"]
                if item
            ],
            "placed_order_ids": [
                str(item.get("order_id") or item.get("broker_order_id") or "")
                for item in execution["placed_orders"]
                if item
            ],
            "skipped_symbols": skipped_symbols,
        }
        updated = update_state(
            paths,
            strategy="futu_gateway_auto_paper_trading",
            market=config.market,
            agent_id=config.agent_id,
            gateway_base_url=config.gateway_base_url,
            config_snapshot={
                "top_k": config.top_k,
                "min_score": config.min_score,
                "lot_size": config.lot_size,
                "cash_buffer_pct": config.cash_buffer_pct,
                "buy_limit_bps": config.buy_limit_bps,
                "sell_limit_bps": config.sell_limit_bps,
                "budget_total": config.budget_total,
            },
            last_attempt_at=now_iso(),
            last_success_at=now_iso(),
            last_status="success",
            last_message=result["message"],
            score_signal_date=signal_date,
            last_applied_signal_date=signal_date,
            last_score_signature=signature,
            last_error=None,
            last_traceback=None,
            gateway_healthy=health_ok,
            live_summary=live_summary,
            balance_metrics=balance_metrics,
            plan_summary=plan_summary,
            active_order_count=result["active_order_count"],
            position_count=len(positions),
            cancelled_order_ids=result["cancelled_order_ids"],
            placed_order_ids=result["placed_order_ids"],
            skipped_symbols=result["skipped_symbols"],
        )
        append_jsonl(paths["history"], {**result, "recorded_at": now_iso()})
        return 0, updated
    except Exception as exc:
        message = str(exc)
        failure = update_state(
            paths,
            strategy="futu_gateway_auto_paper_trading",
            market=config.market,
            agent_id=config.agent_id,
            gateway_base_url=config.gateway_base_url,
            last_attempt_at=now_iso(),
            last_status="error",
            last_message=message,
            score_signal_date=last_signal_date,
            last_error=message,
            last_traceback=traceback.format_exc(limit=20),
        )
        append_jsonl(
            paths["history"],
            {
                "status": "error",
                "message": message,
                "score_signal_date": last_signal_date,
                "recorded_at": now_iso(),
            },
        )
        print(message, file=sys.stderr, flush=True)
        return 1, failure


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto paper-trading reconciler for the Futu gateway.")
    parser.add_argument("--scores-path", default=DEFAULT_SCORES_PATH)
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument("--gateway-base-url", default=DEFAULT_GATEWAY_BASE_URL)
    parser.add_argument("--market", default=DEFAULT_MARKET)
    parser.add_argument("--agent-id", default=DEFAULT_AGENT_ID)
    parser.add_argument("--agent-key", default=DEFAULT_AGENT_KEY)
    parser.add_argument("--agent-id-header", default=DEFAULT_AGENT_ID_HEADER)
    parser.add_argument("--agent-key-header", default=DEFAULT_AGENT_KEY_HEADER)
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--lot-size", type=int, default=DEFAULT_LOT_SIZE)
    parser.add_argument("--cash-buffer-pct", type=float, default=DEFAULT_CASH_BUFFER_PCT)
    parser.add_argument("--buy-limit-bps", type=float, default=DEFAULT_BUY_LIMIT_BPS)
    parser.add_argument("--sell-limit-bps", type=float, default=DEFAULT_SELL_LIMIT_BPS)
    parser.add_argument("--budget-total", type=float, default=None)
    parser.add_argument("--max-order-qty", type=int, default=DEFAULT_MAX_ORDER_QTY)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-cancel-open-orders", action="store_true")
    parser.add_argument("--no-sync-existing-orders", action="store_true")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> SyncConfig:
    return SyncConfig(
        scores_path=Path(args.scores_path),
        state_dir=Path(args.state_dir),
        gateway_base_url=str(args.gateway_base_url).strip() or DEFAULT_GATEWAY_BASE_URL,
        market=str(args.market).strip().upper() or DEFAULT_MARKET,
        agent_id=str(args.agent_id).strip() or DEFAULT_AGENT_ID,
        agent_key=str(args.agent_key).strip() or DEFAULT_AGENT_KEY,
        agent_id_header=str(args.agent_id_header).strip() or DEFAULT_AGENT_ID_HEADER,
        agent_key_header=str(args.agent_key_header).strip() or DEFAULT_AGENT_KEY_HEADER,
        account_id=args.account_id,
        top_k=max(int(args.top_k), 1),
        min_score=float(args.min_score),
        lot_size=max(int(args.lot_size), 1),
        cash_buffer_pct=max(min(float(args.cash_buffer_pct), 0.95), 0.0),
        buy_limit_bps=max(float(args.buy_limit_bps), 0.0),
        sell_limit_bps=max(float(args.sell_limit_bps), 0.0),
        budget_total=float(args.budget_total) if args.budget_total is not None else None,
        max_order_qty=max(int(args.max_order_qty), 1),
        cancel_open_orders=not bool(args.no_cancel_open_orders),
        sync_existing_orders=not bool(args.no_sync_existing_orders),
        force=bool(args.force),
        dry_run=bool(args.dry_run),
    )


def main() -> int:
    args = parse_args()
    config = build_config(args)
    code, state = sync_once(config)
    print(json.dumps(state, ensure_ascii=False, indent=2, default=json_default))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
