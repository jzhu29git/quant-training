#!/usr/bin/env python3
"""Build training features from local A-share parquet datasets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd


DEFAULT_DATA_DIR = "quant_data"
DEFAULT_OUTPUT = "quant_data/ml_features_ready.parquet"

SUPPORTED_PANEL_COLUMNS = [
    "date",
    "code",
    "exchange",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover",
    "amplitude",
    "pct_chg",
    "change",
    "close_val",
    "pct_chg_val",
    "total_market_cap",
    "float_market_cap",
    "total_shares",
    "float_shares",
    "pe_ttm",
    "pb",
    "ps",
    "pcf",
]


def is_investable_stock_name(name: object) -> bool:
    normalized = str(name).strip()
    if not normalized:
        return True
    return not normalized.endswith("退")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build LightGBM-ready features from parquet files.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Input data directory.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output parquet path.")
    parser.add_argument("--limit", type=int, default=0, help="Only use the first N stocks; 0 means all.")
    parser.add_argument("--label-threshold", type=float, default=0.02, help="Positive label threshold.")
    parser.add_argument("--label-horizon", type=int, default=5, help="Future return horizon in trading days.")
    parser.add_argument("--profile-name", default="", help="Optional model profile name to stamp into metadata.")
    return parser.parse_args()


def metadata_path_for_output(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".meta.json")


def load_stock_list(data_dir: Path, limit: int) -> pd.DataFrame:
    stock_list_path = data_dir / "stock_list.parquet"
    stock_df = pd.read_parquet(stock_list_path)
    if "exchange" not in stock_df.columns:
        raise SystemExit("stock_list.parquet 缺少 exchange 列，请先重新运行 download_data.py 刷新股票列表。")
    stock_df["code"] = stock_df["code"].astype(str).str.zfill(6)
    stock_df["exchange"] = stock_df["exchange"].astype(str).str.lower()
    if "name" not in stock_df.columns:
        stock_df["name"] = stock_df["code"]
    stock_df = stock_df[stock_df["name"].map(is_investable_stock_name)].copy()
    if "industry" not in stock_df.columns:
        stock_df["industry"] = "UNKNOWN"
    else:
        stock_df["industry"] = stock_df["industry"].fillna("UNKNOWN")
    if limit > 0:
        stock_df = stock_df.head(limit).copy()
    return stock_df


def trim_supported_panel_columns(df: pd.DataFrame) -> pd.DataFrame:
    columns = [col for col in SUPPORTED_PANEL_COLUMNS if col in df.columns]
    return df[columns].copy()


def load_single_panel_data(data_dir: Path, *, code: str, exchange: str) -> pd.DataFrame:
    kline_dir = data_dir / "daily_kline"
    valuation_dir = data_dir / "daily_valuation"
    kline_path = kline_dir / f"{code}.parquet"
    valuation_path = valuation_dir / f"{code}.parquet"
    if not kline_path.exists() or not valuation_path.exists():
        return pd.DataFrame()

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
    return trim_supported_panel_columns(merged)


def load_panel_data(data_dir: Path, stock_df: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for row in stock_df[["code", "exchange"]].itertuples(index=False):
        code = str(row.code).zfill(6)
        exchange = str(row.exchange).lower()
        merged = load_single_panel_data(data_dir, code=code, exchange=exchange)
        if merged.empty:
            continue
        frames.append(merged)

    if not frames:
        raise SystemExit("没有可用的 K 线/估值 parquet 可合并。")

    return pd.concat(frames, ignore_index=True)


def build_features(
    df: pd.DataFrame,
    stock_df: pd.DataFrame,
    label_horizon: int,
    label_threshold: float,
    *,
    include_labels: bool = True,
) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["exchange", "code", "date"]).reset_index(drop=True)
    df = df.merge(stock_df[["code", "exchange", "name", "industry"]], on=["code", "exchange"], how="left")

    grouped_close = df.groupby(["exchange", "code"])["close"]
    grouped_turnover = df.groupby(["exchange", "code"])["turnover"]
    grouped_volume = df.groupby(["exchange", "code"])["volume"]

    df["ma5"] = grouped_close.transform(lambda x: x.rolling(window=5).mean())
    df["ma20"] = grouped_close.transform(lambda x: x.rolling(window=20).mean())
    df["bias_20"] = df["close"] / df["ma20"] - 1

    df["pct_chg_5d"] = grouped_close.transform(lambda x: x.pct_change(periods=5))
    df["pct_chg_20d"] = grouped_close.transform(lambda x: x.pct_change(periods=20))

    df["volatility_20d"] = grouped_close.transform(lambda x: x.rolling(20).std()) / df["ma20"]
    df["turnover_ma5"] = grouped_turnover.transform(lambda x: x.rolling(window=5).mean())
    df["volume_ma5"] = grouped_volume.transform(lambda x: x.rolling(window=5).mean())

    df["close_to_high_20d"] = df["close"] / grouped_close.transform(lambda x: x.rolling(20).max()) - 1
    df["close_to_low_20d"] = df["close"] / grouped_close.transform(lambda x: x.rolling(20).min()) - 1

    if include_labels:
        df["future_return"] = grouped_close.transform(lambda x: x.shift(-label_horizon) / x - 1)
        df["label"] = np.where(df["future_return"] > label_threshold, 1, 0)

    return df


def clean_features(df: pd.DataFrame, *, clip_outliers: bool = True) -> pd.DataFrame:
    train_ready_df = df.dropna().copy()

    if clip_outliers:
        for col in ["pe_ttm", "pb", "ps", "pcf", "total_market_cap", "float_market_cap"]:
            if col in train_ready_df.columns:
                p1 = train_ready_df[col].quantile(0.01)
                p99 = train_ready_df[col].quantile(0.99)
                train_ready_df[col] = train_ready_df[col].clip(p1, p99)

    return train_ready_df


def normalize_training_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    for col in normalized.columns:
        if col == "date":
            normalized[col] = pd.to_datetime(normalized[col], errors="coerce")
        elif col == "label":
            normalized[col] = pd.to_numeric(normalized[col], errors="coerce").fillna(0).astype("int64")
        elif col in {"code", "exchange", "name", "industry"}:
            normalized[col] = normalized[col].astype(str)
        else:
            normalized[col] = pd.to_numeric(normalized[col], errors="coerce").astype("float64")
    return normalized


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_path = Path(args.output)

    stock_df = load_stock_list(data_dir, args.limit)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview_cols = [
        "date",
        "code",
        "exchange",
        "name",
        "industry",
        "close",
        "bias_20",
        "pct_chg_5d",
        "pe_ttm",
        "pb",
        "future_return",
        "label",
    ]

    import pyarrow as pa
    import pyarrow.parquet as pq

    total_panel_rows = 0
    total_panel_cols = 0
    total_train_rows = 0
    total_train_codes = 0
    preview_frames: list[pd.DataFrame] = []
    writer: pq.ParquetWriter | None = None
    output_cols_count = 0
    min_date = None
    max_date = None

    stock_records = stock_df.to_dict(orient="records")
    for idx, stock in enumerate(stock_records, start=1):
        code = str(stock["code"]).zfill(6)
        exchange = str(stock["exchange"]).lower()
        panel_df = load_single_panel_data(data_dir, code=code, exchange=exchange)
        if panel_df.empty:
            continue

        total_panel_rows += int(len(panel_df))
        total_panel_cols = max(total_panel_cols, len(panel_df.columns))

        single_stock_df = pd.DataFrame([stock])
        features_df = build_features(
            panel_df,
            single_stock_df,
            label_horizon=args.label_horizon,
            label_threshold=args.label_threshold,
        )
        train_ready_df = clean_features(features_df, clip_outliers=False)
        if train_ready_df.empty:
            continue
        train_ready_df = normalize_training_dtypes(train_ready_df)

        table = pa.Table.from_pandas(train_ready_df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(output_path, table.schema, compression="snappy")
            output_cols_count = len(table.schema.names)
        else:
            table = pa.Table.from_pandas(train_ready_df, schema=writer.schema, preserve_index=False)
        writer.write_table(table)

        total_train_rows += int(len(train_ready_df))
        total_train_codes += 1
        if "date" in train_ready_df.columns:
            stock_min_date = pd.to_datetime(train_ready_df["date"], errors="coerce").min()
            stock_max_date = pd.to_datetime(train_ready_df["date"], errors="coerce").max()
            if pd.notna(stock_min_date):
                min_date = stock_min_date if min_date is None or stock_min_date < min_date else min_date
            if pd.notna(stock_max_date):
                max_date = stock_max_date if max_date is None or stock_max_date > max_date else max_date

        collected_preview_rows = sum(len(frame) for frame in preview_frames)
        if collected_preview_rows < 10:
            selected_preview_cols = [col for col in preview_cols if col in train_ready_df.columns]
            preview_frames.append(train_ready_df[selected_preview_cols].head(10 - collected_preview_rows))

        if idx % 500 == 0:
            print(
                f"已处理 {idx}/{len(stock_records)} 只股票，"
                f"当前累计 {total_train_codes} 只进入训练集，"
                f"{total_train_rows} 行。"
            )

    if writer is None:
        raise SystemExit("没有生成任何可用训练样本。")

    writer.close()

    print(f"原始面板数据维度: ({total_panel_rows}, {total_panel_cols})")
    print(f"特征工程完成，可训练数据维度: ({total_train_rows}, {output_cols_count})")
    print(f"输出文件: {output_path}")

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_path": str(output_path),
        "profile_name": args.profile_name.strip() or None,
        "label_horizon": int(args.label_horizon),
        "label_threshold": float(args.label_threshold),
        "limit": int(args.limit),
        "train_rows": int(total_train_rows),
        "train_codes": int(total_train_codes),
        "date_min": str(pd.Timestamp(min_date).date()) if min_date is not None else None,
        "date_max": str(pd.Timestamp(max_date).date()) if max_date is not None else None,
    }
    metadata_path = metadata_path_for_output(output_path)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"特征元数据文件: {metadata_path}")

    if preview_frames:
        preview_df = pd.concat(preview_frames, ignore_index=True).head(10)
        print(preview_df.to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
