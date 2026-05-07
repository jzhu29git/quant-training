#!/usr/bin/env python3
"""Local A-share paper-trading REST gateway.

This gateway implements the REST shape consumed by paper_trade_futu.py without
requiring a broker-side China paper account. Orders are filled immediately using
the submitted limit price, so the slippage assumptions live in the upstream
rebalance script. State is persisted as JSON for auditability.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


DEFAULT_STATE_DIR = "quant_data/local_a_share_paper_gateway"
DEFAULT_INITIAL_CASH = 1_000_000.0
DEFAULT_COMMISSION_BPS = 3.0
DEFAULT_MIN_COMMISSION = 5.0
DEFAULT_STAMP_TAX_BPS = 5.0
DEFAULT_TRANSFER_FEE_BPS = 0.1
DEFAULT_LOT_SIZE = 100
DEFAULT_QUOTE_PATHS = [
    "quant_data/csi500_2y_run/models/inference_scores_latest.parquet",
    "quant_data/csi2000_2y_run/models/inference_scores_latest.parquet",
    "quant_data/sse50_2y_run/models/inference_scores_latest.parquet",
]

TERMINAL_STATUS = "FILLED_ALL"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        text = text.split(".", 1)[-1]
    return text.zfill(6) if text.isdigit() else text


def parse_signal_date(payload: dict[str, Any]) -> str:
    for field in ["signal_date", "trade_date", "date"]:
        if payload.get(field):
            return str(payload[field])[:10]
    remark = str(payload.get("remark") or "")
    match = re.search(r"sig=(\d{4}-\d{2}-\d{2})", remark)
    if match:
        return match.group(1)
    return str(datetime.now().date())


class LocalASharePaperGateway:
    def __init__(
        self,
        *,
        state_dir: Path,
        initial_cash: float,
        commission_bps: float,
        min_commission: float,
        stamp_tax_bps: float,
        transfer_fee_bps: float,
        lot_size: int,
        enforce_t_plus_one: bool,
        allow_short: bool,
        reset: bool,
        quote_paths: list[Path],
    ) -> None:
        self.state_dir = state_dir
        self.state_path = state_dir / "broker_state.json"
        self.orders_path = state_dir / "orders.jsonl"
        self.fills_path = state_dir / "fills.jsonl"
        self.equity_path = state_dir / "equity_curve.jsonl"
        self.initial_cash = float(initial_cash)
        self.commission_bps = float(commission_bps)
        self.min_commission = float(min_commission)
        self.stamp_tax_bps = float(stamp_tax_bps)
        self.transfer_fee_bps = float(transfer_fee_bps)
        self.lot_size = max(int(lot_size), 1)
        self.enforce_t_plus_one = bool(enforce_t_plus_one)
        self.allow_short = bool(allow_short)
        self.quote_paths = quote_paths
        self.quote_cache: dict[str, dict[str, Any]] = {}
        self.quote_signature = ""
        self.lock = threading.RLock()
        self.started_at = time.time()
        if reset and self.state_path.exists():
            self.state_path.unlink()
        self.state = self._load_or_init_state()
        self.refresh_quotes()
        self._save()

    def _load_or_init_state(self) -> dict[str, Any]:
        state = read_json(self.state_path)
        if state:
            state.setdefault("positions", {})
            state.setdefault("orders", [])
            state.setdefault("cash", self.initial_cash)
            return state
        return {
            "broker": "local_a_share_paper_gateway",
            "market": "CN",
            "currency": "CNY",
            "initial_cash": self.initial_cash,
            "cash": self.initial_cash,
            "realized_pnl": 0.0,
            "positions": {},
            "orders": [],
            "next_order_id": 1,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

    def _save(self) -> None:
        self.state["updated_at"] = now_iso()
        write_json(self.state_path, self.state)

    def refresh_quotes(self) -> None:
        if pd is None:
            return
        signatures: list[str] = []
        rows: dict[str, dict[str, Any]] = {}
        for path in self.quote_paths:
            if not path.exists():
                continue
            try:
                stat = path.stat()
                signatures.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
                frame = pd.read_parquet(path)
            except Exception:
                continue
            if frame.empty or "code" not in frame.columns:
                continue
            date_col = "date" if "date" in frame.columns else None
            if date_col:
                frame = frame.copy()
                frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
                latest = frame[date_col].max()
                if pd.notna(latest):
                    frame = frame[frame[date_col].dt.normalize() == pd.Timestamp(latest).normalize()]
            for _, row in frame.iterrows():
                symbol = normalize_symbol(row.get("code"))
                price = to_float(row.get("close"))
                if not symbol or price <= 0:
                    continue
                rows[symbol] = {
                    "symbol": symbol,
                    "last_price": price,
                    "quote_date": str(pd.to_datetime(row.get("date")).date()) if date_col and pd.notna(row.get("date")) else None,
                    "name": str(row.get("name") or ""),
                    "pct_chg": to_float(row.get("pct_chg")),
                    "amount": to_float(row.get("amount")),
                    "volume": to_float(row.get("volume")),
                }
        signature = "|".join(signatures)
        if signature == self.quote_signature:
            return
        self.quote_signature = signature
        self.quote_cache = rows
        for symbol, position in self.state.get("positions", {}).items():
            quote = self.quote_cache.get(symbol)
            if quote and to_float(quote.get("last_price")) > 0:
                position["last_price"] = round(to_float(quote.get("last_price")), 4)
                position["last_quote_date"] = quote.get("quote_date")

    def _next_order_id(self) -> str:
        order_id = int(self.state.get("next_order_id") or 1)
        self.state["next_order_id"] = order_id + 1
        return f"LOCAL-CN-{order_id:08d}"

    def _fees(self, side: str, notional: float) -> dict[str, float]:
        commission = max(notional * self.commission_bps / 10_000.0, self.min_commission) if notional > 0 else 0.0
        transfer_fee = notional * self.transfer_fee_bps / 10_000.0 if notional > 0 else 0.0
        stamp_tax = notional * self.stamp_tax_bps / 10_000.0 if side == "SELL" else 0.0
        total = commission + transfer_fee + stamp_tax
        return {
            "commission": round(commission, 4),
            "transfer_fee": round(transfer_fee, 4),
            "stamp_tax": round(stamp_tax, 4),
            "total_fee": round(total, 4),
        }

    def _position_rows(self) -> list[dict[str, Any]]:
        self.refresh_quotes()
        rows: list[dict[str, Any]] = []
        for symbol, position in sorted(self.state.get("positions", {}).items()):
            quote = self.quote_cache.get(symbol)
            if quote and to_float(quote.get("last_price")) > 0:
                position["last_price"] = round(to_float(quote.get("last_price")), 4)
                position["last_quote_date"] = quote.get("quote_date")
            qty = int(position.get("quantity") or 0)
            if qty <= 0:
                continue
            last_price = to_float(position.get("last_price") or position.get("avg_cost"))
            avg_cost = to_float(position.get("avg_cost"))
            market_value = qty * last_price
            unrealized = (last_price - avg_cost) * qty
            rows.append(
                {
                    "symbol": symbol,
                    "code": symbol,
                    "quantity": qty,
                    "qty": qty,
                    "avg_cost": round(avg_cost, 4),
                    "last_price": round(last_price, 4),
                    "market_value": round(market_value, 4),
                    "realized_pnl": round(to_float(position.get("realized_pnl")), 4),
                    "unrealized_pnl": round(unrealized, 4),
                    "last_buy_signal_date": position.get("last_buy_signal_date"),
                    "last_quote_date": position.get("last_quote_date"),
                    "updated_at": position.get("updated_at"),
                }
            )
        return rows

    def _equity_snapshot(self, *, event: str) -> dict[str, Any]:
        positions = self._position_rows()
        market_value = sum(to_float(row.get("market_value")) for row in positions)
        cash = to_float(self.state.get("cash"))
        total_assets = cash + market_value
        snapshot = {
            "recorded_at": now_iso(),
            "event": event,
            "cash": round(cash, 4),
            "market_value": round(market_value, 4),
            "total_assets": round(total_assets, 4),
            "realized_pnl": round(to_float(self.state.get("realized_pnl")), 4),
            "position_count": len(positions),
        }
        append_jsonl(self.equity_path, snapshot)
        return snapshot

    def health(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": "ok",
                "gateway": "local_a_share_paper_gateway",
                "market": "CN",
                "trd_env": "SIMULATE",
                "orders_enabled": True,
                "state_path": str(self.state_path),
                "quote_count": len(self.quote_cache),
                "quote_signature": self.quote_signature,
                "uptime_seconds": round(time.time() - self.started_at, 2),
            }

    def balance(self) -> list[dict[str, Any]]:
        with self.lock:
            snapshot = self._equity_snapshot(event="balance")
            return [
                {
                    "acc_id": "LOCAL-CN-PAPER",
                    "currency": "CNY",
                    "cash": snapshot["cash"],
                    "cash_balance": snapshot["cash"],
                    "power": snapshot["cash"],
                    "available_cash": snapshot["cash"],
                    "total_assets": snapshot["total_assets"],
                    "market_val": snapshot["market_value"],
                    "initial_cash": self.state.get("initial_cash"),
                }
            ]

    def positions(self) -> list[dict[str, Any]]:
        with self.lock:
            return self._position_rows()

    def orders(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.state.get("orders", []))

    def summary(self) -> dict[str, Any]:
        with self.lock:
            snapshot = self._equity_snapshot(event="summary")
            return {
                "market": "CN",
                "trd_env": "SIMULATE",
                "cash": snapshot["cash"],
                "power": snapshot["cash"],
                "total_assets": snapshot["total_assets"],
                "market_value": snapshot["market_value"],
                "position_count": snapshot["position_count"],
                "realized_pnl": snapshot["realized_pnl"],
            }

    def sync_agent(self) -> dict[str, Any]:
        with self.lock:
            self.refresh_quotes()
            snapshot = self._equity_snapshot(event="sync")
            self._save()
            return {
                "status": "ok",
                "market": "CN",
                "message": "local paper broker state synced",
                "summary": snapshot,
            }

    def _validate_order(self, side: str, symbol: str, quantity: int, price: float, trade_date: str) -> None:
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"unsupported side: {side}")
        if not symbol:
            raise ValueError("symbol is required")
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be positive")
        if side == "BUY" and quantity % self.lot_size != 0:
            raise ValueError(f"A-share buy quantity must be a multiple of {self.lot_size}")
        if side == "SELL":
            position = self.state.get("positions", {}).get(symbol, {})
            available = int(position.get("quantity") or 0)
            if not self.allow_short and quantity > available:
                raise ValueError(f"not enough shares to sell: {symbol} have={available} sell={quantity}")
            if self.enforce_t_plus_one and position.get("last_buy_signal_date") == trade_date:
                raise ValueError(f"T+1 rule blocks same-day sell for {symbol} on {trade_date}")

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            symbol = normalize_symbol(payload.get("symbol") or payload.get("code"))
            side = str(payload.get("side") or "").strip().upper()
            quantity = int(to_float(payload.get("quantity") or payload.get("qty")))
            price = round(to_float(payload.get("price")), 4)
            trade_date = parse_signal_date(payload)
            self._validate_order(side, symbol, quantity, price, trade_date)

            notional = quantity * price
            fees = self._fees(side, notional)
            total_fee = to_float(fees.get("total_fee"))
            cash_before = to_float(self.state.get("cash"))
            positions = self.state.setdefault("positions", {})
            position = positions.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "quantity": 0,
                    "avg_cost": 0.0,
                    "last_price": price,
                    "realized_pnl": 0.0,
                    "last_buy_signal_date": None,
                    "updated_at": now_iso(),
                },
            )

            if side == "BUY":
                cash_required = notional + total_fee
                if cash_required > cash_before + 1e-6:
                    raise ValueError(f"not enough cash: required={cash_required:.2f} cash={cash_before:.2f}")
                old_qty = int(position.get("quantity") or 0)
                old_cost = to_float(position.get("avg_cost")) * old_qty
                new_qty = old_qty + quantity
                position["quantity"] = new_qty
                position["avg_cost"] = round((old_cost + notional + total_fee) / new_qty, 6)
                position["last_price"] = price
                position["last_buy_signal_date"] = trade_date
                self.state["cash"] = round(cash_before - cash_required, 4)
                realized_pnl = 0.0
            else:
                old_qty = int(position.get("quantity") or 0)
                avg_cost = to_float(position.get("avg_cost"))
                realized_pnl = (price - avg_cost) * quantity - total_fee
                new_qty = old_qty - quantity
                position["quantity"] = max(new_qty, 0)
                position["last_price"] = price
                position["realized_pnl"] = round(to_float(position.get("realized_pnl")) + realized_pnl, 4)
                self.state["realized_pnl"] = round(to_float(self.state.get("realized_pnl")) + realized_pnl, 4)
                self.state["cash"] = round(cash_before + notional - total_fee, 4)
                if new_qty <= 0:
                    positions.pop(symbol, None)

            if symbol in positions:
                positions[symbol]["updated_at"] = now_iso()

            order_id = self._next_order_id()
            order = {
                "broker_order_id": order_id,
                "order_id": order_id,
                "symbol": symbol,
                "code": symbol,
                "market": "CN",
                "side": side,
                "order_type": str(payload.get("order_type") or "NORMAL"),
                "quantity": quantity,
                "qty": quantity,
                "price": price,
                "dealt_qty": quantity,
                "dealt_avg_price": price,
                "order_status": TERMINAL_STATUS,
                "notional": round(notional, 4),
                **fees,
                "realized_pnl": round(realized_pnl, 4),
                "trade_date": trade_date,
                "remark": str(payload.get("remark") or ""),
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            self.state.setdefault("orders", []).append(order)
            append_jsonl(self.orders_path, order)
            append_jsonl(self.fills_path, {**order, "fill_id": f"{order_id}-FILL"})
            snapshot = self._equity_snapshot(event=f"fill:{order_id}")
            self._save()
            return {**order, "portfolio_after": snapshot}

    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            order_id = str(payload.get("order_id") or payload.get("broker_order_id") or "")
            if not order_id:
                raise ValueError("order_id is required")
            for order in self.state.get("orders", []):
                if str(order.get("order_id")) == order_id or str(order.get("broker_order_id")) == order_id:
                    return {**order, "cancel_status": "already_terminal"}
            raise ValueError(f"order not found: {order_id}")


class Handler(BaseHTTPRequestHandler):
    gateway: LocalASharePaperGateway

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[local-a-paper] {self.address_string()} - {fmt % args}", flush=True)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        return {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._json(200, self.gateway.health())
            elif parsed.path == "/v1/balance":
                self._json(200, {"balance": self.gateway.balance()})
            elif parsed.path == "/v1/agents/me/summary":
                self._json(200, {"summary": self.gateway.summary()})
            elif parsed.path == "/v1/agents/me/positions":
                self._json(200, {"positions": self.gateway.positions()})
            elif parsed.path == "/v1/agents/me/orders":
                self._json(200, {"orders": self.gateway.orders()})
            else:
                self._json(404, {"error": f"unknown endpoint: {parsed.path}"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            payload = self._read_body()
            if parsed.path == "/v1/admin/sync":
                self._json(200, self.gateway.sync_agent())
            elif parsed.path == "/v1/orders":
                self._json(200, {"order": self.gateway.place_order(payload)})
            elif parsed.path == "/v1/orders/cancel":
                self._json(200, {"order": self.gateway.cancel_order(payload)})
            else:
                self._json(404, {"error": f"unknown endpoint: {parsed.path}"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local REST paper broker for A-share strategy validation.")
    parser.add_argument("--host", default="127.0.0.1", help="REST listen host.")
    parser.add_argument("--port", type=int, default=18080, help="REST listen port.")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR, help="Persistent paper broker state directory.")
    parser.add_argument("--initial-cash", type=float, default=DEFAULT_INITIAL_CASH)
    parser.add_argument("--commission-bps", type=float, default=DEFAULT_COMMISSION_BPS)
    parser.add_argument("--min-commission", type=float, default=DEFAULT_MIN_COMMISSION)
    parser.add_argument("--stamp-tax-bps", type=float, default=DEFAULT_STAMP_TAX_BPS)
    parser.add_argument("--transfer-fee-bps", type=float, default=DEFAULT_TRANSFER_FEE_BPS)
    parser.add_argument("--lot-size", type=int, default=DEFAULT_LOT_SIZE)
    parser.add_argument("--disable-t-plus-one", action="store_true", help="Allow same-signal-date sells.")
    parser.add_argument("--allow-short", action="store_true", help="Allow selling more shares than currently held.")
    parser.add_argument("--reset", action="store_true", help="Reset broker_state.json before starting.")
    parser.add_argument(
        "--quote-path",
        action="append",
        default=[],
        help="Parquet score/feature file with code and close columns. Can be passed multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    Handler.gateway = LocalASharePaperGateway(
        state_dir=Path(args.state_dir),
        initial_cash=args.initial_cash,
        commission_bps=args.commission_bps,
        min_commission=args.min_commission,
        stamp_tax_bps=args.stamp_tax_bps,
        transfer_fee_bps=args.transfer_fee_bps,
        lot_size=args.lot_size,
        enforce_t_plus_one=not bool(args.disable_t_plus_one),
        allow_short=bool(args.allow_short),
        reset=bool(args.reset),
        quote_paths=[Path(item) for item in (args.quote_path or DEFAULT_QUOTE_PATHS)],
    )
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"local A-share paper gateway listening on http://{args.host}:{args.port}, "
        f"state_dir={args.state_dir}, initial_cash={args.initial_cash:.2f}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
