#!/usr/bin/env python3
"""Build inference-only features without any future labels."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from feature_engineering import build_features, load_stock_list, trim_supported_panel_columns


DEFAULT_DATA_DIR = "quant_data"
DEFAULT_OUTPUT = "quant_data/inference_features_latest.parquet"
INFERENCE_HISTORY_WINDOW = 25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build inference-ready features from parquet files.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Input data directory.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output parquet path.")
    parser.add_argument("--limit", type=int, default=0, help="Only use the first N stocks; 0 means all.")
    parser.add_argument(
        "--as-of-date",
        default="",
        help="Only keep features up to this date, format YYYY-MM-DD or YYYYMMDD.",
    )
    return parser.parse_args()


def normalize_as_of_date(as_of_date: str) -> pd.Timestamp | None:
    if not as_of_date:
        return None
    return pd.to_datetime(as_of_date)


def load_recent_panel_data(
    data_dir: Path,
    stock_df: pd.DataFrame,
    as_of_date: pd.Timestamp | None,
) -> pd.DataFrame:
    kline_dir = data_dir / "daily_kline"
    valuation_dir = data_dir / "daily_valuation"
    frames: list[pd.DataFrame] = []

    for row in stock_df[["code", "exchange"]].itertuples(index=False):
        code = str(row.code).zfill(6)
        exchange = str(row.exchange).lower()
        kline_path = kline_dir / f"{code}.parquet"
        valuation_path = valuation_dir / f"{code}.parquet"
        if not kline_path.exists() or not valuation_path.exists():
            continue

        kline_df = pd.read_parquet(kline_path)
        valuation_df = pd.read_parquet(valuation_path)

        kline_df["date"] = pd.to_datetime(kline_df["date"])
        valuation_df["date"] = pd.to_datetime(valuation_df["date"])
        kline_df["code"] = kline_df["code"].astype(str).str.zfill(6)
        valuation_df["code"] = valuation_df["code"].astype(str).str.zfill(6)
        if "exchange" not in kline_df.columns:
            kline_df["exchange"] = exchange
        if "exchange" not in valuation_df.columns:
            valuation_df["exchange"] = exchange
        kline_df["exchange"] = kline_df["exchange"].astype(str).str.lower()
        valuation_df["exchange"] = valuation_df["exchange"].astype(str).str.lower()

        merged = kline_df.merge(
            valuation_df,
            on=["date", "code", "exchange"],
            how="left",
            suffixes=("", "_val"),
        )
        merged = trim_supported_panel_columns(merged)
        if as_of_date is not None:
            merged = merged[merged["date"] <= as_of_date].copy()
        if merged.empty:
            continue
        frames.append(merged.sort_values("date").tail(INFERENCE_HISTORY_WINDOW))

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def build_inference_frame(data_dir: Path, limit: int, as_of_date: pd.Timestamp | None) -> pd.DataFrame:
    stock_df = load_stock_list(data_dir, limit)
    latest_rows: list[pd.DataFrame] = []

    for idx, row in enumerate(stock_df.itertuples(index=False), start=1):
        code = str(row.code).zfill(6)
        single_stock_df = stock_df[stock_df["code"] == code].copy()
        panel_df = load_recent_panel_data(data_dir, single_stock_df, as_of_date)
        if panel_df.empty:
            continue
        features_df = build_features(
            panel_df,
            single_stock_df,
            label_horizon=5,
            label_threshold=0.02,
            include_labels=False,
        )
        latest_df = (
            features_df.drop(columns=["future_return", "label"], errors="ignore")
            .sort_values(["code", "date"])
            .tail(1)
            .dropna()
        )
        if not latest_df.empty:
            latest_rows.append(latest_df)

        if idx % 500 == 0:
            print(f"已处理 {idx}/{len(stock_df)} 只股票...")

    if not latest_rows:
        raise SystemExit("没有生成任何可用的推理特征。")

    return pd.concat(latest_rows, ignore_index=True).sort_values(["date", "code"]).reset_index(drop=True)


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_path = Path(args.output)
    as_of_date = normalize_as_of_date(args.as_of_date)

    latest_df = build_inference_frame(data_dir, args.limit, as_of_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    latest_df.to_parquet(output_path, index=False)

    print(f"推理特征完成，数据维度: {latest_df.shape}")
    print(f"输出文件: {output_path}")

    preview_cols = [
        "date",
        "code",
        "exchange",
        "name",
        "industry",
        "close",
        "ma5",
        "ma20",
        "bias_20",
        "pct_chg_5d",
        "volatility_20d",
        "pe_ttm",
        "pb",
        "total_market_cap",
    ]
    preview_cols = [col for col in preview_cols if col in latest_df.columns]
    print(latest_df[preview_cols].head(20).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
