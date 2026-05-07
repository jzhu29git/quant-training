#!/usr/bin/env python3
"""Small REST bridge from this project to moomoo OpenD paper trading.

This gateway intentionally defaults to US paper trading only. It exposes the
REST shape expected by paper_trade_futu.py while forwarding requests to the
local moomoo OpenD process.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd

try:
    from moomoo import (
        OpenSecTradeContext,
        RET_OK,
        SecurityFirm,
        TrdEnv,
        TrdMarket,
        TrdSide,
        OrderType,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit("moomoo-api is required. Run: python -m pip install moomoo-api") from exc


MARKET_MAP = {
    "US": TrdMarket.US,
    "HK": TrdMarket.HK,
    "CN": TrdMarket.CN,
}

SIDE_MAP = {
    "BUY": TrdSide.BUY,
    "SELL": TrdSide.SELL,
}


def frame_to_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, pd.DataFrame):
        return json.loads(value.where(pd.notna(value), None).to_json(orient="records", force_ascii=False))
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [{"value": str(value)}]


def row_first(value: Any) -> dict[str, Any]:
    records = frame_to_records(value)
    return records[0] if records else {}


class MoomooGateway:
    def __init__(
        self,
        *,
        opend_host: str,
        opend_port: int,
        default_market: str,
        security_firm: Any,
        allow_live_orders: bool,
    ) -> None:
        self.opend_host = opend_host
        self.opend_port = opend_port
        self.default_market = default_market.upper()
        self.security_firm = security_firm
        self.allow_live_orders = allow_live_orders
        self.lock = threading.Lock()
        self.started_at = time.time()

    def _context(self, market: str) -> OpenSecTradeContext:
        normalized = (market or self.default_market).upper()
        if normalized not in MARKET_MAP:
            raise ValueError(f"unsupported market: {market}")
        return OpenSecTradeContext(
            filter_trdmarket=MARKET_MAP[normalized],
            host=self.opend_host,
            port=self.opend_port,
            security_firm=self.security_firm,
        )

    def _call(self, market: str, fn_name: str, **kwargs: Any) -> tuple[int, Any]:
        with self.lock:
            ctx = self._context(market)
            try:
                fn = getattr(ctx, fn_name)
                return fn(**kwargs)
            finally:
                ctx.close()

    def balance(self, market: str) -> list[dict[str, Any]]:
        ret, data = self._call(market, "accinfo_query", trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK:
            raise RuntimeError(str(data))
        return frame_to_records(data)

    def positions(self, market: str) -> list[dict[str, Any]]:
        ret, data = self._call(market, "position_list_query", trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK:
            raise RuntimeError(str(data))
        rows = frame_to_records(data)
        out = []
        for row in rows:
            symbol = str(row.get("code") or "").split(".")[-1]
            qty = row.get("qty") or row.get("quantity") or 0
            last_price = row.get("nominal_price") or row.get("last_price") or row.get("average_cost") or 0
            out.append(
                {
                    **row,
                    "symbol": symbol,
                    "code": symbol,
                    "quantity": qty,
                    "avg_cost": row.get("average_cost") or row.get("cost_price") or 0,
                    "last_price": last_price,
                    "market_value": row.get("market_val") or 0,
                    "unrealized_pnl": row.get("unrealized_pl") or row.get("pl_val") or 0,
                    "realized_pnl": row.get("realized_pl") or 0,
                }
            )
        return out

    def orders(self, market: str) -> list[dict[str, Any]]:
        ret, data = self._call(market, "order_list_query", trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK:
            raise RuntimeError(str(data))
        rows = frame_to_records(data)
        out = []
        for row in rows:
            symbol = str(row.get("code") or "").split(".")[-1]
            out.append(
                {
                    **row,
                    "broker_order_id": str(row.get("order_id") or ""),
                    "order_id": str(row.get("order_id") or ""),
                    "symbol": symbol,
                    "code": symbol,
                    "side": str(row.get("trd_side") or row.get("side") or "").upper(),
                    "quantity": row.get("qty") or row.get("quantity") or 0,
                    "price": row.get("price") or 0,
                    "order_status": str(row.get("order_status") or ""),
                    "updated_at": str(row.get("updated_time") or row.get("create_time") or ""),
                }
            )
        return out

    def summary(self, market: str) -> dict[str, Any]:
        balance = row_first(self.balance(market))
        positions = self.positions(market)
        return {
            "market": market.upper(),
            "trd_env": "SIMULATE",
            "total_assets": balance.get("total_assets"),
            "cash": balance.get("cash"),
            "power": balance.get("power"),
            "market_value": sum(float(row.get("market_value") or 0) for row in positions),
            "position_count": len(positions),
        }

    def sync_agent(self, market: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "market": market.upper(),
            "message": "moomoo OpenD bridge has no separate agent sync step",
        }

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_live_orders:
            raise RuntimeError("order placement is disabled; restart gateway with --allow-orders to enable SIMULATE orders")
        market = str(payload.get("market") or self.default_market).upper()
        symbol = normalize_symbol(market, str(payload.get("symbol") or payload.get("code") or ""))
        side = str(payload.get("side") or "").upper()
        if side not in SIDE_MAP:
            raise ValueError(f"unsupported side: {side}")
        qty = int(float(payload.get("quantity") or payload.get("qty") or 0))
        price = float(payload.get("price") or 0)
        if qty <= 0 or price <= 0:
            raise ValueError("quantity and price must be positive")

        ret, data = self._call(
            market,
            "place_order",
            price=price,
            qty=qty,
            code=symbol,
            trd_side=SIDE_MAP[side],
            order_type=OrderType.NORMAL,
            trd_env=TrdEnv.SIMULATE,
            remark=str(payload.get("remark") or "")[:64],
        )
        if ret != RET_OK:
            raise RuntimeError(str(data))
        return row_first(data)

    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_live_orders:
            raise RuntimeError("order cancellation is disabled; restart gateway with --allow-orders to enable SIMULATE orders")
        market = str(payload.get("market") or self.default_market).upper()
        order_id = str(payload.get("order_id") or payload.get("broker_order_id") or "")
        if not order_id:
            raise ValueError("order_id is required")
        ret, data = self._call(market, "modify_order", modify_order_op="CANCEL", order_id=order_id, trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK:
            raise RuntimeError(str(data))
        return row_first(data)


def normalize_symbol(market: str, symbol: str) -> str:
    text = str(symbol).strip().upper()
    if "." in text:
        return text
    if market == "US":
        return f"US.{text}"
    if market == "HK":
        return f"HK.{text.zfill(5)}" if text.isdigit() else f"HK.{text}"
    if market == "CN":
        prefix = "SH" if text.startswith(("5", "6", "9")) else "SZ"
        return f"{prefix}.{text.zfill(6)}"
    return text


class Handler(BaseHTTPRequestHandler):
    gateway: MoomooGateway
    agent_id_header = "X-Agent-Id"
    agent_key_header = "X-Agent-Key"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[gateway] {self.address_string()} - {fmt % args}", flush=True)

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
            query = self._query()
            market = query.get("market") or self.gateway.default_market
            if parsed.path == "/health":
                self._json(
                    200,
                    {
                        "status": "ok",
                        "gateway": "moomoo_rest_gateway",
                        "market": self.gateway.default_market,
                        "trd_env": "SIMULATE",
                        "orders_enabled": self.gateway.allow_live_orders,
                        "uptime_seconds": round(time.time() - self.gateway.started_at, 2),
                    },
                )
            elif parsed.path == "/v1/balance":
                self._json(200, {"balance": self.gateway.balance(market)})
            elif parsed.path == "/v1/agents/me/summary":
                self._json(200, {"summary": self.gateway.summary(market)})
            elif parsed.path == "/v1/agents/me/positions":
                self._json(200, {"positions": self.gateway.positions(market)})
            elif parsed.path == "/v1/agents/me/orders":
                self._json(200, {"orders": self.gateway.orders(market)})
            else:
                self._json(404, {"error": f"unknown endpoint: {parsed.path}"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            query = self._query()
            payload = self._read_body()
            if query.get("market") and "market" not in payload:
                payload["market"] = query["market"]
            if parsed.path == "/v1/admin/sync":
                market = query.get("market") or payload.get("market") or self.gateway.default_market
                self._json(200, self.gateway.sync_agent(str(market)))
            elif parsed.path == "/v1/orders":
                self._json(200, {"order": self.gateway.place_order(payload)})
            elif parsed.path == "/v1/orders/cancel":
                self._json(200, {"order": self.gateway.cancel_order(payload)})
            else:
                self._json(404, {"error": f"unknown endpoint: {parsed.path}"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REST bridge for moomoo OpenD paper trading.")
    parser.add_argument("--host", default="127.0.0.1", help="REST listen host.")
    parser.add_argument("--port", type=int, default=8080, help="REST listen port.")
    parser.add_argument("--opend-host", default="127.0.0.1", help="OpenD host.")
    parser.add_argument("--opend-port", type=int, default=11111, help="OpenD port.")
    parser.add_argument("--market", default="US", choices=["US", "HK", "CN"], help="Default trading market.")
    parser.add_argument("--allow-orders", action="store_true", help="Enable SIMULATE order placement/cancellation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    Handler.gateway = MoomooGateway(
        opend_host=args.opend_host,
        opend_port=args.opend_port,
        default_market=args.market,
        security_firm=SecurityFirm.FUTUSECURITIES,
        allow_live_orders=args.allow_orders,
    )
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"moomoo REST gateway listening on http://{args.host}:{args.port} "
        f"-> OpenD {args.opend_host}:{args.opend_port}, market={args.market}, "
        f"trd_env=SIMULATE, orders_enabled={args.allow_orders}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
