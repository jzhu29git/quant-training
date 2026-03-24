#!/usr/bin/env python3
"""Run a strict out-of-sample walk-forward backtest on engineered features."""

from __future__ import annotations

import argparse
import gc
import json
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from train_lightgbm import build_category_mappings, build_feature_frame, choose_feature_columns, compute_metrics, load_frame


DEFAULT_TRAIN_PATH = "quant_data/ml_features_ready.parquet"
DEFAULT_OUTPUT_DIR = "quant_data/backtests"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict walk-forward out-of-sample backtest.")
    parser.add_argument("--train-path", default=DEFAULT_TRAIN_PATH, help="Feature parquet with labels.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for backtest outputs.")
    parser.add_argument("--min-train-days", type=int, default=252, help="Minimum unique trade dates before first rebalance.")
    parser.add_argument("--retrain-every", type=int, default=20, help="Retrain every N rebalance dates.")
    parser.add_argument("--rebalance-every", type=int, default=5, help="Rebalance every N trade dates.")
    parser.add_argument("--top-k", type=int, default=5, help="Hold top K stocks on each rebalance date.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Classification threshold for OOS metrics.")
    parser.add_argument("--profile-name", default="", help="Optional model profile name for this backtest run.")
    parser.add_argument("--profile-label", default="", help="Optional display label for this backtest run.")
    parser.add_argument("--label-horizon", type=int, default=0, help="Optional label horizon metadata for this run.")
    parser.add_argument("--label-threshold", type=float, default=0.0, help="Optional label threshold metadata for this run.")
    return parser.parse_args()


def build_model_params(*, scale_pos_weight: float) -> dict[str, object]:
    return {
        "objective": "binary",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "colsample_bytree": 0.8,
        "force_col_wise": True,
        "num_threads": 1,
        "random_state": 42,
        "scale_pos_weight": scale_pos_weight,
    }


def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    return float(drawdown.min())


def annualized_return(equity_curve: pd.Series, dates: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    start = pd.to_datetime(dates.iloc[0])
    end = pd.to_datetime(dates.iloc[-1])
    total_days = max((end - start).days, 1)
    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0)
    years = total_days / 365.25
    if years <= 0:
        return total_return
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


class IncrementalParquetWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.writer: pq.ParquetWriter | None = None

    def write(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            if self.path.exists():
                self.path.unlink()
            self.writer = pq.ParquetWriter(self.path, table.schema)
        self.writer.write_table(table)

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None


def main() -> int:
    args = parse_args()
    train_path = Path(args.train_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_frame(train_path)
    df["date"] = pd.to_datetime(df["date"])
    # Keep rows ordered by trade date so each walk-forward split becomes a cheap prefix slice.
    df = df.sort_values("date", kind="stable").reset_index(drop=True)

    feature_cols, categorical_cols = choose_feature_columns(df)
    category_mappings = build_category_mappings(df, df, categorical_cols)
    date_values = df["date"].to_numpy()
    label_values = pd.to_numeric(df["label"], errors="coerce").fillna(0).to_numpy(dtype=np.int8)
    future_return_values = pd.to_numeric(df["future_return"], errors="coerce").astype(np.float32).to_numpy()
    summary_stats = {
        "num_rows": int(len(df)),
        "num_codes": int(df["code"].nunique()),
        "num_trade_dates": int(df["date"].nunique()),
    }
    meta_cols = [col for col in ["date", "code", "name", "industry"] if col in df.columns]
    prediction_cols = meta_cols + ["label", "future_return", "score"]
    trade_cols = ["rebalance_date"] + [col for col in ["code", "name", "industry"] if col in df.columns] + [
        "score",
        "future_return",
        "label",
    ]

    unique_dates = pd.Index(pd.unique(date_values[~pd.isna(date_values)]))
    if len(unique_dates) <= args.min_train_days:
        raise SystemExit("交易日数量不足，无法启动 walk-forward 回测。")

    rebalance_dates = unique_dates[args.min_train_days :: args.rebalance_every]
    if len(rebalance_dates) == 0:
        raise SystemExit("没有可用于回测的调仓日期。")

    prediction_path = output_dir / "oos_predictions.parquet"
    trade_log_path = output_dir / "trade_log.parquet"
    equity_path = output_dir / "equity_curve.parquet"
    summary_path = output_dir / "summary.json"
    prediction_tmp_path = output_dir / "oos_predictions.tmp.parquet"
    trade_log_tmp_path = output_dir / "trade_log.tmp.parquet"
    equity_tmp_path = output_dir / "equity_curve.tmp.parquet"
    summary_tmp_path = output_dir / "summary.tmp.json"
    prediction_writer = IncrementalParquetWriter(prediction_tmp_path)
    trade_log_writer = IncrementalParquetWriter(trade_log_tmp_path)
    metric_label_chunks: list[np.ndarray] = []
    metric_score_chunks: list[np.ndarray] = []
    equity_rows: list[dict[str, object]] = []

    model: lgb.Booster | None = None
    rebalance_counter = 0
    equity_value = 1.0
    try:
        for rebalance_date in rebalance_dates:
            test_start = int(date_values.searchsorted(rebalance_date, side="left"))
            test_end = int(date_values.searchsorted(rebalance_date, side="right"))
            if test_start <= 0 or test_end <= test_start:
                continue

            if model is None or rebalance_counter % args.retrain_every == 0:
                train_slice = df.iloc[:test_start]
                X_train = build_feature_frame(train_slice, feature_cols, categorical_cols, category_mappings)
                y_train = label_values[:test_start]
                positive_count = int(y_train.sum())
                negative_count = int(len(y_train) - positive_count)
                scale_pos_weight = negative_count / max(positive_count, 1)

                print(
                    f"retrain on {pd.Timestamp(rebalance_date).date()}: "
                    f"train_rows={len(X_train)} test_rows={test_end - test_start}"
                )
                train_data = lgb.Dataset(
                    X_train,
                    label=y_train,
                    categorical_feature=categorical_cols,
                    free_raw_data=True,
                )
                train_data.construct()
                del train_slice
                del X_train
                del y_train
                gc.collect()
                model = lgb.train(
                    build_model_params(scale_pos_weight=scale_pos_weight),
                    train_data,
                    num_boost_round=500,
                    callbacks=[lgb.log_evaluation(0)],
                )
                del train_data
                gc.collect()

            test_slice = df.iloc[test_start:test_end]
            X_test = build_feature_frame(test_slice, feature_cols, categorical_cols, category_mappings)
            score_values = model.predict(X_test).astype(np.float32, copy=False)
            scored = test_slice.loc[:, meta_cols].copy()
            scored["label"] = label_values[test_start:test_end]
            scored["future_return"] = future_return_values[test_start:test_end]
            scored["score"] = score_values
            prediction_writer.write(scored.loc[:, prediction_cols].copy())
            metric_label_chunks.append(label_values[test_start:test_end].copy())
            metric_score_chunks.append(score_values.copy())

            picks = scored.nlargest(args.top_k, "score").copy()
            portfolio_return = float(picks["future_return"].mean())
            equity_value *= 1.0 + portfolio_return

            equity_rows.append(
                {
                    "rebalance_date": rebalance_date,
                    "portfolio_return": portfolio_return,
                    "equity": equity_value,
                    "num_picks": int(len(picks)),
                }
            )

            if not picks.empty:
                picks.insert(0, "rebalance_date", rebalance_date)
                trade_log_writer.write(picks.loc[:, trade_cols].copy())

            rebalance_counter += 1
            del test_slice
            del X_test
            del score_values
            del scored
            del picks
            gc.collect()
    finally:
        prediction_writer.close()
        trade_log_writer.close()

    if not metric_label_chunks or not equity_rows:
        raise SystemExit("回测没有生成任何预测结果。")

    metric_labels = np.concatenate(metric_label_chunks)
    metric_scores = np.concatenate(metric_score_chunks)
    metrics = compute_metrics(
        pd.Series(metric_labels),
        pd.Series(metric_scores),
        args.threshold,
    )
    del metric_labels
    del metric_scores
    gc.collect()

    equity_df = pd.DataFrame(equity_rows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": output_dir.name,
        "profile_name": args.profile_name.strip() or None,
        "profile_label": args.profile_label.strip() or None,
        "label_horizon": args.label_horizon if args.label_horizon > 0 else None,
        "label_threshold": args.label_threshold if args.label_threshold > 0 else None,
        "train_path": str(train_path),
        **summary_stats,
        "min_train_days": args.min_train_days,
        "retrain_every": args.retrain_every,
        "rebalance_every": args.rebalance_every,
        "top_k": args.top_k,
        "threshold": args.threshold,
        "num_rebalances": int(len(equity_df)),
        "oos_metrics": metrics,
        "portfolio_total_return": float(equity_df["equity"].iloc[-1] - 1.0),
        "portfolio_cagr": annualized_return(equity_df["equity"], equity_df["rebalance_date"]),
        "portfolio_max_drawdown": max_drawdown(equity_df["equity"]),
        "portfolio_win_rate": float((equity_df["portfolio_return"] > 0).mean()),
        "portfolio_avg_return": float(equity_df["portfolio_return"].mean()),
        "portfolio_std_return": float(equity_df["portfolio_return"].std(ddof=0)),
        "backtest_start": str(pd.to_datetime(equity_df["rebalance_date"].min()).date()),
        "backtest_end": str(pd.to_datetime(equity_df["rebalance_date"].max()).date()),
    }

    equity_df.to_parquet(equity_tmp_path, index=False)
    summary_tmp_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    prediction_tmp_path.replace(prediction_path)
    trade_log_tmp_path.replace(trade_log_path)
    equity_tmp_path.replace(equity_path)
    summary_tmp_path.replace(summary_path)

    print("严格 OOS 回测完成。")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(equity_df.tail(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
