#!/usr/bin/env python3
"""Robust long-running batch downloader for full A-share history."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from download_data import (
    DEFAULT_DATA_DIR,
    baostock_login,
    baostock_logout,
    build_kline_df,
    build_stock_list,
    build_valuation_df,
    download_baostock_daily_bundle,
    ensure_dirs,
    get_selected_universe,
    load_dependencies,
    load_existing_stock_list,
    normalize_exchange,
    sync_stock_registry,
    write_canonical_stock_lists,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Long-running resilient batch downloader for all A-shares.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Output data directory.")
    parser.add_argument("--start-date", required=True, help="Start date in YYYYMMDD format.")
    parser.add_argument("--end-date", required=True, help="End date in YYYYMMDD format.")
    parser.add_argument("--sleep", type=float, default=1.2, help="Sleep seconds between stocks.")
    parser.add_argument("--pause-minutes", type=float, default=15.0, help="Pause between retry passes.")
    parser.add_argument("--max-passes", type=int, default=5, help="Maximum retry passes over pending stocks.")
    parser.add_argument("--max-attempts", type=int, default=6, help="Maximum attempts per stock.")
    parser.add_argument("--relogin-every", type=int, default=300, help="Relogin Baostock every N stocks.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing parquet files.")
    parser.add_argument("--include-industry", action="store_true", help="Also enrich stock_list with industry data.")
    parser.add_argument("--universe", choices=("all",), default="all", help="Universe to download.")
    parser.add_argument(
        "--state-file",
        default="quant_data/batch_state/all_a_3y_state.json",
        help="State file path for resume.",
    )
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_date(value: Any) -> pd.Timestamp | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.normalize()


def latest_parquet_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["date"])
    except Exception:
        return None
    if df.empty or "date" not in df.columns:
        return None
    return _coerce_date(df["date"].max())


def merge_existing_output(path: Path, fresh_df: pd.DataFrame) -> pd.DataFrame:
    if not path.exists():
        return fresh_df.reset_index(drop=True)
    try:
        existing_df = pd.read_parquet(path)
    except Exception:
        return fresh_df.reset_index(drop=True)

    merged = pd.concat([existing_df, fresh_df], ignore_index=True, sort=False)
    if "date" in merged.columns:
        merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    dedupe_columns = [col for col in ["date", "code"] if col in merged.columns]
    if dedupe_columns:
        merged = merged.drop_duplicates(subset=dedupe_columns, keep="last")
    else:
        merged = merged.drop_duplicates(keep="last")
    sort_columns = [col for col in ["date", "code"] if col in merged.columns]
    if sort_columns:
        merged = merged.sort_values(sort_columns)
    return merged.reset_index(drop=True)


def normalize_codes(codes: list[str]) -> list[str]:
    return [str(code).zfill(6) for code in codes]


def build_exchange_by_code(stock_df: Any) -> dict[str, str | None]:
    return {
        str(row.code).zfill(6): normalize_exchange(row.exchange)
        for row in stock_df[["code", "exchange"]].itertuples(index=False)
    }


def load_state(state_path: Path, codes: list[str]) -> dict[str, Any]:
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {}

    attempts = {str(code).zfill(6): int(v) for code, v in state.get("attempts", {}).items()}
    done_codes = normalize_codes(state.get("done_codes", []))
    failed_codes = {str(code).zfill(6): str(v) for code, v in state.get("failed_codes", {}).items()}

    return {
        "created_at": state.get("created_at", utc_now_iso()),
        "updated_at": utc_now_iso(),
        "pass_index": int(state.get("pass_index", 0)),
        "done_codes": [code for code in done_codes if code in codes],
        "failed_codes": {code: reason for code, reason in failed_codes.items() if code in codes},
        "attempts": {code: attempts.get(code, 0) for code in codes},
        "last_code": state.get("last_code", ""),
        "start_date": state.get("start_date"),
        "end_date": state.get("end_date"),
    }


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now_iso()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_existing_outputs(
    codes: list[str],
    *,
    state: dict[str, Any],
    kline_dir: Path,
    valuation_dir: Path,
    overwrite: bool,
    target_trade_date: str,
) -> None:
    if overwrite:
        return
    target_trade_ts = _coerce_date(target_trade_date)
    done_set: set[str] = set()
    for code in codes:
        kline_path = kline_dir / f"{code}.parquet"
        valuation_path = valuation_dir / f"{code}.parquet"
        if not kline_path.exists() or not valuation_path.exists():
            continue
        if target_trade_ts is None:
            done_set.add(code)
            continue
        kline_max = latest_parquet_date(kline_path)
        valuation_max = latest_parquet_date(valuation_path)
        if kline_max is not None and valuation_max is not None and kline_max >= target_trade_ts and valuation_max >= target_trade_ts:
            done_set.add(code)
    state["done_codes"] = sorted(done_set)


def pending_codes(codes: list[str], state: dict[str, Any], max_attempts: int) -> list[str]:
    done_set = set(state["done_codes"])
    return [code for code in codes if code not in done_set and int(state["attempts"].get(code, 0)) < max_attempts]


def refresh_stock_list(
    *,
    data_dir: Path,
    end_date: str,
    include_industry: bool,
    sleep: float,
) -> tuple[Any, str]:
    universe_df, trade_date = get_selected_universe("all", end_date)
    existing_stock_df = load_existing_stock_list(data_dir)
    stock_df = build_stock_list(
        universe_df,
        universe_name="all",
        include_industry=include_industry,
        sleep_seconds=sleep,
        trade_date=trade_date,
        existing_stock_df=existing_stock_df,
    )
    registry_df, active_df, sync_summary = sync_stock_registry(
        stock_df,
        existing_stock_df=existing_stock_df,
        trade_date=trade_date,
    )
    stock_list_path, registry_path = write_canonical_stock_lists(
        data_dir,
        registry_df=registry_df,
        active_df=active_df,
    )
    print(f"活跃股票池已保存至 {stock_list_path}，共 {len(active_df)} 只股票。")
    print(f"主注册表已保存至 {registry_path}，共 {len(registry_df)} 只股票。")
    print(
        "股票池同步结果: "
        f"新增 {sync_summary['new_count']}，"
        f"恢复 {sync_summary['reactivated_count']}，"
        f"停用 {sync_summary['deactivated_count']}"
    )
    return active_df, trade_date


def process_code(
    code: str,
    *,
    exchange: str | None,
    args: argparse.Namespace,
    kline_dir: Path,
    valuation_dir: Path,
    target_trade_date: str,
) -> tuple[bool, str | None]:
    kline_path = kline_dir / f"{code}.parquet"
    valuation_path = valuation_dir / f"{code}.parquet"
    target_trade_ts = _coerce_date(target_trade_date)
    download_start = args.start_date
    if not args.overwrite:
        kline_max = latest_parquet_date(kline_path)
        valuation_max = latest_parquet_date(valuation_path)
        if (
            target_trade_ts is not None
            and kline_max is not None
            and valuation_max is not None
            and kline_max >= target_trade_ts
            and valuation_max >= target_trade_ts
        ):
            return True, None
        existing_dates = [ts for ts in [kline_max, valuation_max] if ts is not None]
        if existing_dates:
            incremental_start = min(existing_dates).strftime("%Y%m%d")
            if incremental_start > download_start:
                download_start = incremental_start

    bundle_df, reason = download_baostock_daily_bundle(
        code,
        exchange=exchange,
        start_date=download_start,
        end_date=args.end_date,
    )
    if bundle_df is None:
        return False, reason or "bundle_empty"

    try:
        kline_df = build_kline_df(bundle_df, code)
        valuation_df, warning = build_valuation_df(
            bundle_df,
            code,
            start_date=download_start,
            end_date=args.end_date,
        )
        if not args.overwrite:
            kline_df = merge_existing_output(kline_path, kline_df)
            valuation_df = merge_existing_output(valuation_path, valuation_df)
        kline_df.to_parquet(kline_path, index=False)
        valuation_df.to_parquet(valuation_path, index=False)
        if warning:
            return True, warning
        return True, None
    except Exception as exc:  # pragma: no cover - file/data dependent
        return False, str(exc)


def run_batch(args: argparse.Namespace) -> int:
    load_dependencies()
    data_dir = Path(args.data_dir)
    state_path = Path(args.state_file)
    kline_dir, valuation_dir = ensure_dirs(data_dir)

    processed_since_login = 0
    baostock_login()
    try:
        stock_df, trade_date = refresh_stock_list(
            data_dir=data_dir,
            end_date=args.end_date,
            include_industry=args.include_industry,
            sleep=args.sleep,
        )
        codes = normalize_codes(stock_df["code"].tolist())
        exchange_by_code = build_exchange_by_code(stock_df)
        state = load_state(state_path, codes)
        previous_done_count = len(state["done_codes"])
        previous_start_date = str(state.get("start_date") or "")
        previous_end_date = str(state.get("end_date") or "")
        if previous_start_date != args.start_date or previous_end_date != args.end_date:
            state["pass_index"] = 0
            state["done_codes"] = []
            state["failed_codes"] = {}
            state["attempts"] = {code: 0 for code in codes}
            state["last_code"] = ""
        state["start_date"] = args.start_date
        state["end_date"] = args.end_date

        mark_existing_outputs(
            codes,
            state=state,
            kline_dir=kline_dir,
            valuation_dir=valuation_dir,
            overwrite=args.overwrite,
            target_trade_date=trade_date,
        )
        if previous_end_date == args.end_date and len(state["done_codes"]) < previous_done_count:
            state["pass_index"] = 0
            state["failed_codes"] = {}
            state["attempts"] = {code: 0 for code in codes}
            state["last_code"] = ""
        save_state(state_path, state)

        print(f"全市场股票数: {len(codes)}")
        print(f"已完成: {len(state['done_codes'])}")
        print(f"状态文件: {state_path}")

        for pass_index in range(state["pass_index"], args.max_passes):
            state["pass_index"] = pass_index
            todo = pending_codes(codes, state, args.max_attempts)
            print(f"开始第 {pass_index + 1}/{args.max_passes} 轮，待处理股票数: {len(todo)}")
            if not todo:
                break

            for idx, code in enumerate(todo, start=1):
                state["last_code"] = code
                state["attempts"][code] = int(state["attempts"].get(code, 0)) + 1
                print(
                    f"[pass {pass_index + 1} {idx}/{len(todo)}] "
                    f"下载 {code}，尝试次数 {state['attempts'][code]}/{args.max_attempts}"
                )

                if processed_since_login >= args.relogin_every:
                    print("达到重新登录阈值，重连 Baostock...")
                    baostock_logout()
                    time.sleep(2.0)
                    baostock_login()
                    processed_since_login = 0

                ok, reason = process_code(
                    code,
                    exchange=exchange_by_code.get(code),
                    args=args,
                    kline_dir=kline_dir,
                    valuation_dir=valuation_dir,
                    target_trade_date=trade_date,
                )
                processed_since_login += 1

                if ok:
                    if code not in state["done_codes"]:
                        state["done_codes"].append(code)
                        state["done_codes"] = sorted(set(normalize_codes(state["done_codes"])))
                    state["failed_codes"].pop(code, None)
                    print(f"{code} 完成" + (f"，提醒: {reason}" if reason else ""))
                else:
                    state["failed_codes"][code] = reason or "unknown"
                    print(f"{code} 失败: {reason}")

                save_state(state_path, state)
                time.sleep(args.sleep)

            remaining = pending_codes(codes, state, args.max_attempts)
            print(
                f"第 {pass_index + 1} 轮结束，累计完成 {len(state['done_codes'])}/{len(codes)}，"
                f"剩余待重试 {len(remaining)}"
            )
            save_state(state_path, state)
            if remaining and pass_index < args.max_passes - 1:
                pause_seconds = max(args.pause_minutes, 0.0) * 60.0
                print(f"暂停 {args.pause_minutes} 分钟后进入下一轮...")
                time.sleep(pause_seconds)

        remaining = pending_codes(codes, state, args.max_attempts)
        summary = {
            "finished": len(remaining) == 0,
            "total_codes": len(codes),
            "done_codes": len(state["done_codes"]),
            "remaining_codes": len(remaining),
            "state_file": str(state_path),
            "last_code": state.get("last_code", ""),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        save_state(state_path, state)
        return 0 if not remaining else 2
    finally:
        baostock_logout()


def main() -> int:
    args = parse_args()
    return run_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
