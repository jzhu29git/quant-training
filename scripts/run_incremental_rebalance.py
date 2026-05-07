#!/usr/bin/env python3
"""Incremental latest-signal rebalance runner for local A-share paper trading."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import download_data as dd

INDEX_CONFIG = {
    "csi500": {
        "run_dir": ROOT / "quant_data/csi500_2y_run",
        "best_group": "momentum_liquidity",
        "state_dir": ROOT / "quant_data/paper_trading_local_csi500",
    },
    "csi2000": {
        "run_dir": ROOT / "quant_data/csi2000_2y_run",
        "best_group": "momentum_liquidity",
        "state_dir": ROOT / "quant_data/paper_trading_local_csi2000",
    },
    "sse50": {
        "run_dir": ROOT / "quant_data/sse50_2y_run",
        "best_group": "valuation_momentum",
        "state_dir": ROOT / "quant_data/paper_trading_local_sse50",
    },
}

DEFAULT_CONFIG_PATH = ROOT / "paper_trading_config.yaml"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_cmd(args: list[str], *, dry_run: bool = False) -> None:
    print("+ " + " ".join(args), flush=True)
    if not dry_run:
        subprocess.run(args, cwd=ROOT, check=True)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config must be a mapping: {path}")
    return data


def deep_get(payload: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur: Any = payload
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def latest_score_date(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["date"])
    except Exception:
        return None
    if df.empty:
        return None
    date = pd.to_datetime(df["date"], errors="coerce").max()
    if pd.isna(date):
        return None
    return str(pd.Timestamp(date).date())


def archive_scores(scores_path: Path, state_dir: Path, *, index_name: str, group: str) -> Path | None:
    score_date = latest_score_date(scores_path)
    if not score_date:
        return None
    out_dir = state_dir / "score_snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{index_name}_{group}_{score_date}.parquet"
    shutil.copy2(scores_path, out_path)
    return out_path


def http_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def prepare_group_inference(run_dir: Path, group: str) -> tuple[Path, Path, Path]:
    base_inference = run_dir / "inference_features_latest.parquet"
    feature_dir = run_dir / "feature_group_tests" / group
    train_path = feature_dir / "features.parquet"
    model_dir = feature_dir / "models"
    group_inference = feature_dir / "inference_features_latest.parquet"

    metadata = read_json(model_dir / "training_metadata.json")
    feature_cols = [str(col) for col in metadata.get("feature_cols", [])]
    meta_cols = ["date", "code", "exchange", "name", "industry", "open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg", "change"]
    cols = list(dict.fromkeys([col for col in meta_cols + feature_cols if col]))
    source = pd.read_parquet(base_inference)
    available = [col for col in cols if col in source.columns]
    source.loc[:, available].to_parquet(group_inference, index=False)
    return train_path, model_dir, group_inference


def build_basic_valuation_df(bundle_df: pd.DataFrame, code: str) -> pd.DataFrame:
    df = bundle_df.copy()
    df["code"] = str(code).zfill(6)
    if "pctChg" in df.columns:
        df["pct_chg"] = df["pctChg"]
    df = df.rename(columns={"peTTM": "pe_ttm", "pbMRQ": "pb", "psTTM": "ps", "pcfNcfTTM": "pcf"})
    cols = ["date", "code", "exchange", "close", "pct_chg", "pe_ttm", "pb", "ps", "pcf"]
    return df[[col for col in cols if col in df.columns]].copy()


def append_unique(existing_path: Path, new_df: pd.DataFrame, keys: list[str]) -> int:
    if new_df.empty:
        return 0
    if existing_path.exists():
        old = pd.read_parquet(existing_path)
        old_len = len(old)
        out = pd.concat([old, new_df], ignore_index=True)
    else:
        old_len = 0
        out = new_df.copy()
    for key in keys:
        if key in out.columns:
            if key == "date":
                out[key] = pd.to_datetime(out[key], errors="coerce")
            else:
                out[key] = out[key].astype(str)
    out = out.drop_duplicates(subset=[key for key in keys if key in out.columns], keep="last")
    if "date" in out.columns:
        out = out.sort_values(["date", "code"] if "code" in out.columns else ["date"])
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(existing_path, index=False)
    return max(len(out) - old_len, 0)


def latest_local_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["date"])
    except Exception:
        return None
    if df.empty:
        return None
    value = pd.to_datetime(df["date"], errors="coerce").max()
    if pd.isna(value):
        return None
    return pd.Timestamp(value).normalize()


def update_market_data(run_dir: Path, *, end_date: str, sleep: float, max_stocks: int) -> dict[str, Any]:
    stock_path = run_dir / "stock_list.parquet"
    if not stock_path.exists():
        raise FileNotFoundError(f"missing stock list: {stock_path}")
    dd.load_dependencies()
    stock_df = pd.read_parquet(stock_path)
    if max_stocks > 0:
        stock_df = stock_df.head(max_stocks).copy()
    target_trade_date = pd.Timestamp(dd.get_latest_trade_date(end_date.replace("-", ""))).normalize()
    kline_dir, valuation_dir = dd.ensure_dirs(run_dir)
    summary: dict[str, Any] = {
        "target_trade_date": str(target_trade_date.date()),
        "stock_count": int(len(stock_df)),
        "updated_symbols": 0,
        "skipped_up_to_date": 0,
        "failures": [],
    }
    dd.baostock_login()
    try:
        for idx, row in enumerate(stock_df[["code", "exchange"]].itertuples(index=False), start=1):
            code = str(row.code).zfill(6)
            exchange = str(row.exchange).lower()
            kline_path = kline_dir / f"{code}.parquet"
            latest = latest_local_date(kline_path)
            if latest is not None and latest >= target_trade_date:
                summary["skipped_up_to_date"] += 1
                continue
            start_dt = (latest + pd.Timedelta(days=1)) if latest is not None else target_trade_date
            if start_dt > target_trade_date:
                summary["skipped_up_to_date"] += 1
                continue
            start_text = str(start_dt.date()).replace("-", "")
            end_text = str(target_trade_date.date()).replace("-", "")
            print(f"[data] {idx}/{len(stock_df)} {code} {start_text}->{end_text}", flush=True)
            bundle_df, reason = dd.download_baostock_daily_bundle(
                code,
                exchange=exchange,
                start_date=start_text,
                end_date=end_text,
            )
            if bundle_df is None or bundle_df.empty:
                summary["failures"].append({"code": code, "exchange": exchange, "reason": reason or "empty"})
                continue
            kline_df = dd.build_kline_df(bundle_df, code)
            valuation_df = build_basic_valuation_df(bundle_df, code)
            added_kline = append_unique(kline_path, kline_df, ["date", "code"])
            append_unique(valuation_dir / f"{code}.parquet", valuation_df, ["date", "code"])
            if added_kline > 0:
                summary["updated_symbols"] += 1
            if sleep > 0:
                import time

                time.sleep(sleep)
    finally:
        dd.baostock_logout()
    summary["failure_count"] = len(summary["failures"])
    write_json(run_dir / "incremental_data_update_summary.json", summary)
    return summary


def estimate_rebalance_gap(state_path: Path, score_date: str | None, rebalance_every: int) -> dict[str, Any]:
    state = read_json(state_path)
    last_applied = state.get("last_applied_signal_date") or state.get("score_signal_date")
    if not last_applied or not score_date:
        return {
            "last_applied_signal_date": last_applied,
            "latest_score_date": score_date,
            "missed_window_warning": None,
        }
    try:
        last_dt = pd.to_datetime(last_applied)
        score_dt = pd.to_datetime(score_date)
        days = len(pd.bdate_range(last_dt, score_dt)) - 1
    except Exception:
        days = None
    missed = days is not None and days > rebalance_every
    return {
        "last_applied_signal_date": str(last_applied),
        "latest_score_date": str(score_date),
        "business_days_since_last_signal": days,
        "rebalance_every": rebalance_every,
        "missed_window_warning": (
            f"Latest-only mode does not replay {days} business days of missed rebalance windows."
            if missed
            else None
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run latest incremental scoring and local paper rebalance.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="YAML config path.")
    parser.add_argument("--index", choices=sorted(INDEX_CONFIG), default="csi500")
    parser.add_argument("--group", default="", help="Feature group. Defaults to the trader-preferred group for each index.")
    parser.add_argument("--gateway-base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--budget-total", type=float, default=1_000_000.0)
    parser.add_argument("--lot-size", type=int, default=100)
    parser.add_argument("--max-order-qty", type=int, default=20_000)
    parser.add_argument("--rebalance-every", type=int, default=5)
    parser.add_argument("--skip-feature-build", action="store_true", help="Use existing inference_features_latest.parquet.")
    parser.add_argument("--update-data", action="store_true", help="Incrementally download missing daily kline/valuation before scoring.")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y%m%d"), help="Data update end date, YYYYMMDD.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between data requests when --update-data is used.")
    parser.add_argument("--max-stocks", type=int, default=0, help="Limit symbols for data update testing; 0 means all.")
    parser.add_argument("--skip-rebalance", action="store_true", help="Only refresh score and mark-to-market.")
    parser.add_argument("--dry-run", action="store_true", help="Build target plan but do not place orders.")
    parser.add_argument("--force", action="store_true", help="Force paper_trade_futu even when score file signature is unchanged.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    yaml_cfg = load_yaml_config(Path(args.config))
    index_yaml = deep_get(yaml_cfg, ["indices", args.index], {}) or {}
    broker_yaml = deep_get(yaml_cfg, ["broker"], {}) or {}
    execution_yaml = deep_get(yaml_cfg, ["execution"], {}) or {}
    cfg = INDEX_CONFIG[args.index]
    run_dir = ROOT / str(index_yaml.get("run_dir") or cfg["run_dir"])
    group = args.group or str(index_yaml.get("group") or cfg["best_group"])
    state_dir = ROOT / str(index_yaml.get("state_dir") or cfg["state_dir"])

    gateway_base_url = args.gateway_base_url or str(broker_yaml.get("gateway_base_url") or "http://127.0.0.1:18080")
    top_k = int(args.top_k or index_yaml.get("top_k") or 10)
    min_score = float(args.min_score if args.min_score is not None else deep_get(yaml_cfg, ["model", "default_min_score"], 0.5))
    budget_total = float(args.budget_total or index_yaml.get("budget_total") or 1_000_000.0)
    lot_size = int(args.lot_size or broker_yaml.get("lot_size") or 100)
    max_order_qty = int(args.max_order_qty or execution_yaml.get("max_order_qty") or 20_000)
    rebalance_every = int(args.rebalance_every or execution_yaml.get("rebalance_every_trade_days") or 5)

    base_inference = run_dir / "inference_features_latest.parquet"
    output_scores = run_dir / "feature_group_tests" / group / "models" / "inference_scores_latest.parquet"

    summary: dict[str, Any] = {
        "started_at": now_iso(),
        "index": args.index,
        "group": group,
        "run_dir": str(run_dir),
        "gateway_base_url": gateway_base_url,
        "mode": str(execution_yaml.get("mode") or "latest_only"),
        "config_path": str(Path(args.config)),
        "execution_price_mode": str(execution_yaml.get("execution_price_mode") or "close_with_slippage"),
        "price_source": str(execution_yaml.get("price_source") or "inference_scores_latest.parquet close"),
    }

    if args.update_data:
        summary["data_update"] = update_market_data(run_dir, end_date=args.end_date, sleep=args.sleep, max_stocks=args.max_stocks)

    if not args.skip_feature_build:
        run_cmd(
            [
                sys.executable,
                "build_inference_features.py",
                "--data-dir",
                str(run_dir),
                "--output",
                str(base_inference),
            ]
        )

    train_path, model_dir, group_inference = prepare_group_inference(run_dir, group)
    run_cmd(
        [
            sys.executable,
            "scripts/score_inference_with_existing_model.py",
            "--model-dir",
            str(model_dir),
            "--train-path",
            str(train_path),
            "--inference-path",
            str(group_inference),
            "--output",
            str(output_scores),
            "--top-k",
            str(top_k),
        ]
    )

    archived_scores = archive_scores(output_scores, state_dir, index_name=args.index, group=group)
    score_date = latest_score_date(output_scores)
    gap = estimate_rebalance_gap(state_dir / "state.json", score_date, rebalance_every)
    summary["rebalance_gap"] = gap
    if gap.get("missed_window_warning"):
        print("WARNING: " + str(gap["missed_window_warning"]), flush=True)

    try:
        summary["broker_health"] = http_json(gateway_base_url.rstrip("/") + "/health")
        summary["broker_summary_before"] = http_json(gateway_base_url.rstrip("/") + "/v1/agents/me/summary").get("summary", {})
    except Exception as exc:
        summary["broker_error"] = str(exc)
        raise

    if not args.skip_rebalance:
        cmd = [
            sys.executable,
            "paper_trade_futu.py",
            "--scores-path",
            str(output_scores),
            "--state-dir",
            str(state_dir),
            "--gateway-base-url",
            gateway_base_url,
            "--market",
            "CN",
            "--top-k",
            str(top_k),
            "--min-score",
            str(min_score),
            "--budget-total",
            str(budget_total),
            "--lot-size",
            str(lot_size),
            "--max-order-qty",
            str(max_order_qty),
        ]
        if args.force:
            cmd.append("--force")
        if args.dry_run:
            cmd.append("--dry-run")
        run_cmd(cmd)

    summary["broker_summary_after"] = http_json(gateway_base_url.rstrip("/") + "/v1/agents/me/summary").get("summary", {})
    summary["score_date"] = score_date
    summary["scores_path"] = str(output_scores)
    summary["archived_scores_path"] = str(archived_scores) if archived_scores else None
    summary["state_dir"] = str(state_dir)
    summary["finished_at"] = now_iso()

    summary_path = state_dir / "incremental_rebalance_summary.json"
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
