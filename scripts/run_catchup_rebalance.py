#!/usr/bin/env python3
"""Replay missed 5-day paper rebalances from historical OOS predictions.

This is a research catch-up tool. It reconstructs a plausible historical paper
path from saved walk-forward predictions and daily close prices. By default it
does not touch the live local gateway.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "paper_trading_config.yaml"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def deep_get(payload: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur: Any = payload
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[-1]
    return text.zfill(6) if text.isdigit() else text


def fees(side: str, notional: float, *, commission_bps: float, min_commission: float, stamp_tax_bps: float, transfer_fee_bps: float) -> float:
    if notional <= 0:
        return 0.0
    commission = max(notional * commission_bps / 10_000.0, min_commission)
    transfer = notional * transfer_fee_bps / 10_000.0
    stamp = notional * stamp_tax_bps / 10_000.0 if side == "SELL" else 0.0
    return commission + transfer + stamp


def http_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def load_price_panel(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "ml_features_ready.parquet"
    cols = ["date", "code", "name", "industry", "close"]
    df = pd.read_parquet(path, columns=[col for col in cols if col in pd.read_parquet(path, columns=[]).columns])
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"]).drop_duplicates(["date", "code"], keep="last")


def safe_load_price_panel(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "ml_features_ready.parquet"
    sample = pd.read_parquet(path)
    cols = [col for col in ["date", "code", "name", "industry", "close"] if col in sample.columns]
    df = sample.loc[:, cols].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"]).drop_duplicates(["date", "code"], keep="last")


def load_predictions(run_dir: Path, group: str, top_k: int) -> pd.DataFrame:
    candidates = [
        run_dir / "topk_tests" / group / f"topk_{top_k}" / "oos_predictions.parquet",
        run_dir / "feature_group_tests" / group / "backtest" / "oos_predictions.parquet",
    ]
    for path in candidates:
        if path.exists():
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()
            df["code"] = df["code"].astype(str).str.zfill(6)
            df["score"] = pd.to_numeric(df["score"], errors="coerce")
            return df.dropna(subset=["score"]).copy()
    raise FileNotFoundError(f"missing OOS predictions for group={group}, top_k={top_k}")


def round_lot(quantity: float, lot_size: int) -> int:
    return int(max(quantity, 0) // lot_size * lot_size)


def replay(
    *,
    scored: pd.DataFrame,
    prices: pd.DataFrame,
    from_date: str | None,
    to_date: str | None,
    top_k: int,
    initial_cash: float,
    lot_size: int,
    buy_limit_bps: float,
    sell_limit_bps: float,
    cash_buffer_pct: float,
    commission_bps: float,
    min_commission: float,
    stamp_tax_bps: float,
    transfer_fee_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if from_date:
        scored = scored[scored["date"] > pd.to_datetime(from_date).normalize()].copy()
    if to_date:
        scored = scored[scored["date"] <= pd.to_datetime(to_date).normalize()].copy()
    if scored.empty:
        raise RuntimeError("no catch-up rebalance dates in requested window")

    price_lookup = prices.set_index(["date", "code"])["close"].to_dict()
    meta_lookup = prices.drop_duplicates("code").set_index("code").to_dict("index")
    cash = float(initial_cash)
    positions: dict[str, dict[str, float]] = {}
    order_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []

    for date, day in scored.groupby("date", sort=True):
        date = pd.Timestamp(date).normalize()

        def px(symbol: str, fallback: float = 0.0) -> float:
            return float(price_lookup.get((date, symbol), fallback) or fallback)

        market_value_before = sum(pos["qty"] * px(symbol, pos["last_price"]) for symbol, pos in positions.items())
        total_assets_before = cash + market_value_before
        picks = day.nlargest(top_k, "score").copy()
        targets = {normalize_symbol(row.code): row for row in picks.itertuples(index=False)}

        for symbol in list(positions):
            if symbol in targets:
                continue
            qty = int(positions[symbol]["qty"])
            if qty <= 0:
                continue
            base = px(symbol, positions[symbol]["last_price"])
            sell_price = round(base * (1.0 - sell_limit_bps / 10_000.0), 4)
            notional = qty * sell_price
            fee = fees("SELL", notional, commission_bps=commission_bps, min_commission=min_commission, stamp_tax_bps=stamp_tax_bps, transfer_fee_bps=transfer_fee_bps)
            cash += notional - fee
            pnl = (sell_price - positions[symbol]["avg_cost"]) * qty - fee
            order_rows.append({"date": date, "code": symbol, "side": "SELL", "qty": qty, "price": sell_price, "notional": notional, "fee": fee, "realized_pnl": pnl, "reason": "exit_non_target"})
            positions.pop(symbol, None)

        investable = max((cash + sum(pos["qty"] * px(symbol, pos["last_price"]) for symbol, pos in positions.items())) * (1.0 - cash_buffer_pct), 0.0)
        target_value = investable / max(len(targets), 1)

        for symbol, row in targets.items():
            base = px(symbol)
            if base <= 0:
                continue
            buy_price = round(base * (1.0 + buy_limit_bps / 10_000.0), 4)
            current_qty = int(positions.get(symbol, {}).get("qty", 0))
            target_qty = round_lot(target_value / buy_price, lot_size)
            delta = target_qty - current_qty
            if delta < 0:
                qty = abs(delta)
                sell_price = round(base * (1.0 - sell_limit_bps / 10_000.0), 4)
                notional = qty * sell_price
                fee = fees("SELL", notional, commission_bps=commission_bps, min_commission=min_commission, stamp_tax_bps=stamp_tax_bps, transfer_fee_bps=transfer_fee_bps)
                cash += notional - fee
                avg_cost = positions[symbol]["avg_cost"]
                positions[symbol]["qty"] = current_qty - qty
                positions[symbol]["last_price"] = base
                if positions[symbol]["qty"] <= 0:
                    positions.pop(symbol, None)
                order_rows.append({"date": date, "code": symbol, "side": "SELL", "qty": qty, "price": sell_price, "notional": notional, "fee": fee, "realized_pnl": (sell_price - avg_cost) * qty - fee, "reason": "trim_target"})
            elif delta > 0:
                qty = round_lot(delta, lot_size)
                notional = qty * buy_price
                fee = fees("BUY", notional, commission_bps=commission_bps, min_commission=min_commission, stamp_tax_bps=stamp_tax_bps, transfer_fee_bps=transfer_fee_bps)
                while qty > 0 and notional + fee > cash:
                    qty -= lot_size
                    notional = qty * buy_price
                    fee = fees("BUY", notional, commission_bps=commission_bps, min_commission=min_commission, stamp_tax_bps=stamp_tax_bps, transfer_fee_bps=transfer_fee_bps)
                if qty <= 0:
                    continue
                old = positions.get(symbol, {"qty": 0, "avg_cost": 0.0})
                new_qty = int(old["qty"]) + qty
                new_cost = old["avg_cost"] * old["qty"] + notional + fee
                positions[symbol] = {"qty": new_qty, "avg_cost": new_cost / new_qty, "last_price": base}
                cash -= notional + fee
                order_rows.append({"date": date, "code": symbol, "side": "BUY", "qty": qty, "price": buy_price, "notional": notional, "fee": fee, "realized_pnl": 0.0, "reason": "buy_or_add_target"})

        market_value_after = sum(pos["qty"] * px(symbol, pos["last_price"]) for symbol, pos in positions.items())
        equity_rows.append(
            {
                "date": date,
                "cash": cash,
                "market_value": market_value_after,
                "total_assets": cash + market_value_after,
                "position_count": len(positions),
                "target_count": len(targets),
                "total_assets_before": total_assets_before,
            }
        )

    orders = pd.DataFrame(order_rows)
    equity = pd.DataFrame(equity_rows)
    if not orders.empty:
        orders["name"] = orders["code"].map(lambda code: meta_lookup.get(code, {}).get("name", ""))
    summary = {
        "started_from_cash": initial_cash,
        "from_date": from_date,
        "to_date": to_date,
        "rebalance_count": int(equity["date"].nunique()) if not equity.empty else 0,
        "order_count": int(len(orders)),
        "final_cash": float(cash),
        "final_total_assets": float(equity["total_assets"].iloc[-1]) if not equity.empty else float(cash),
        "total_return": float(equity["total_assets"].iloc[-1] / initial_cash - 1.0) if not equity.empty and initial_cash > 0 else 0.0,
    }
    return orders, equity, summary


def apply_orders_to_gateway(orders: pd.DataFrame, gateway_base_url: str) -> list[dict[str, Any]]:
    placed: list[dict[str, Any]] = []
    for row in orders.itertuples(index=False):
        payload = {
            "market": "CN",
            "symbol": str(row.code),
            "side": str(row.side),
            "quantity": int(row.qty),
            "price": float(row.price),
            "remark": f"catchup sig={pd.Timestamp(row.date).date()} {str(row.reason)[:32]}",
        }
        response = http_json("POST", gateway_base_url.rstrip("/") + "/v1/orders", payload)
        placed.append(response.get("order", response))
    return placed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run or apply catch-up paper rebalances.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--index", choices=["csi500", "csi2000", "sse50"], default="csi500")
    parser.add_argument("--group", default="")
    parser.add_argument("--from-date", default="", help="Replay dates strictly after this date.")
    parser.add_argument("--to-date", default="", help="Replay dates up to and including this date.")
    parser.add_argument("--output-dir", default="", help="Defaults to state_dir/catchup_runs/latest.")
    parser.add_argument("--apply-to-gateway", action="store_true", help="Actually send reconstructed orders to the local gateway.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(Path(args.config))
    index_cfg = deep_get(cfg, ["indices", args.index], {})
    broker_cfg = deep_get(cfg, ["broker"], {})
    exec_cfg = deep_get(cfg, ["execution"], {})
    model_cfg = deep_get(cfg, ["model"], {})
    group = args.group or str(index_cfg.get("group") or "momentum_liquidity")
    run_dir = ROOT / str(index_cfg.get("run_dir"))
    state_dir = ROOT / str(index_cfg.get("state_dir"))
    top_k = int(index_cfg.get("top_k") or 10)
    initial_cash = float(index_cfg.get("budget_total") or broker_cfg.get("initial_cash") or 1_000_000)
    output_dir = Path(args.output_dir) if args.output_dir else state_dir / "catchup_runs" / "latest"
    output_dir.mkdir(parents=True, exist_ok=True)

    scored = load_predictions(run_dir, group, top_k)
    prices = safe_load_price_panel(run_dir)
    orders, equity, summary = replay(
        scored=scored,
        prices=prices,
        from_date=args.from_date or None,
        to_date=args.to_date or None,
        top_k=top_k,
        initial_cash=initial_cash,
        lot_size=int(broker_cfg.get("lot_size") or 100),
        buy_limit_bps=float(exec_cfg.get("buy_limit_bps") or 50.0),
        sell_limit_bps=float(exec_cfg.get("sell_limit_bps") or 50.0),
        cash_buffer_pct=float(exec_cfg.get("cash_buffer_pct") or 0.02),
        commission_bps=float(broker_cfg.get("commission_bps") or 3.0),
        min_commission=float(broker_cfg.get("min_commission") or 5.0),
        stamp_tax_bps=float(broker_cfg.get("stamp_tax_bps") or 5.0),
        transfer_fee_bps=float(broker_cfg.get("transfer_fee_bps") or 0.1),
    )
    if not orders.empty:
        orders.to_parquet(output_dir / "catchup_orders.parquet", index=False)
        orders.to_csv(output_dir / "catchup_orders.csv", index=False, encoding="utf-8-sig")
    if not equity.empty:
        equity.to_parquet(output_dir / "catchup_equity.parquet", index=False)
        equity.to_csv(output_dir / "catchup_equity.csv", index=False, encoding="utf-8-sig")

    summary.update(
        {
            "generated_at": now_iso(),
            "index": args.index,
            "group": group,
            "mode": "historical_oos_catchup",
            "applied_to_gateway": bool(args.apply_to_gateway),
            "warning": "This reconstructs a historical research path. It is not proof that the live paper account really traded then.",
            "retrain_every_trade_days": model_cfg.get("retrain_every_trade_days"),
        }
    )
    if args.apply_to_gateway and not orders.empty:
        summary["gateway_orders"] = apply_orders_to_gateway(orders, str(broker_cfg.get("gateway_base_url") or "http://127.0.0.1:18080"))
    (output_dir / "catchup_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"catch-up outputs written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
