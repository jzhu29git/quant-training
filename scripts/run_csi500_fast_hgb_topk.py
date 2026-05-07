#!/usr/bin/env python3
"""Fast CSI500 top-k experiment with a non-LightGBM sklearn model."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from train_lightgbm import build_category_mappings, build_feature_frame, choose_feature_columns, load_frame


DEFAULT_TRAIN_PATH = "quant_data/csi500_2y_run/ml_features_ready.parquet"
DEFAULT_OUTPUT_DIR = "quant_data/csi500_2y_run/alt_model_tests/hgb_regressor_fast"
DEFAULT_BASELINE_DIR = "quant_data/csi500_2y_run/topk_tests"
TOP_KS = [1, 3, 5, 10, 20]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fast sklearn HGB top-k CSI500 backtest.")
    parser.add_argument("--train-path", default=DEFAULT_TRAIN_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--baseline-dir", default=DEFAULT_BASELINE_DIR)
    parser.add_argument("--min-train-days", type=int, default=252)
    parser.add_argument("--retrain-every", type=int, default=20)
    parser.add_argument("--rebalance-every", type=int, default=5)
    parser.add_argument("--max-iter", type=int, default=80)
    return parser.parse_args()


def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    return float((equity_curve / running_max - 1.0).min())


def annualized_return(equity_curve: pd.Series, dates: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    start = pd.to_datetime(dates.iloc[0])
    end = pd.to_datetime(dates.iloc[-1])
    years = max((end - start).days, 1) / 365.25
    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0)
    return float((1.0 + total_return) ** (1.0 / years) - 1.0) if years > 0 else total_return


def build_model(max_iter: int) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.06,
        max_iter=max_iter,
        max_leaf_nodes=31,
        l2_regularization=0.05,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=8,
        random_state=42,
    )


def summarize_topk(equity_rows: list[dict[str, object]], top_k: int) -> dict[str, object]:
    equity_df = pd.DataFrame(equity_rows)
    return {
        "top_k": top_k,
        "num_rebalances": int(len(equity_df)),
        "portfolio_total_return": float(equity_df["equity"].iloc[-1] - 1.0),
        "portfolio_cagr": annualized_return(equity_df["equity"], equity_df["rebalance_date"]),
        "portfolio_max_drawdown": max_drawdown(equity_df["equity"]),
        "portfolio_win_rate": float((equity_df["portfolio_return"] > 0).mean()),
        "portfolio_avg_return": float(equity_df["portfolio_return"].mean()),
        "portfolio_std_return": float(equity_df["portfolio_return"].std(ddof=0)),
        "backtest_start": str(pd.to_datetime(equity_df["rebalance_date"].min()).date()),
        "backtest_end": str(pd.to_datetime(equity_df["rebalance_date"].max()).date()),
    }


def load_baseline_rows(baseline_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary_path in sorted(baseline_dir.glob("*/topk_*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        top_k = int(summary.get("top_k", -1))
        if top_k not in TOP_KS:
            continue
        rows.append(
            {
                "model": summary_path.parts[-3],
                "top_k": top_k,
                "total_return": float(summary.get("portfolio_total_return", np.nan)),
                "cagr": float(summary.get("portfolio_cagr", np.nan)),
                "max_drawdown": float(summary.get("portfolio_max_drawdown", np.nan)),
                "win_rate": float(summary.get("portfolio_win_rate", np.nan)),
                "num_rebalances": int(summary.get("num_rebalances", 0)),
            }
        )
    return rows


def main() -> int:
    args = parse_args()
    train_path = Path(args.train_path)
    output_dir = Path(args.output_dir)
    baseline_dir = Path(args.baseline_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_frame(train_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date", kind="stable").reset_index(drop=True)

    feature_cols, categorical_cols = choose_feature_columns(df)
    category_mappings = build_category_mappings(df, df, categorical_cols)
    date_values = df["date"].to_numpy(dtype="datetime64[ns]")
    y_return = pd.to_numeric(df["future_return"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float32)
    y_label = pd.to_numeric(df["label"], errors="coerce").fillna(0).to_numpy(dtype=np.int8)
    unique_dates = pd.Index(pd.unique(date_values[~pd.isna(date_values)]))
    rebalance_dates = unique_dates[args.min_train_days :: args.rebalance_every]
    if len(rebalance_dates) == 0:
        raise SystemExit("没有可用于回测的调仓日期。")

    meta_cols = [col for col in ["date", "code", "name", "industry"] if col in df.columns]
    prediction_rows: list[pd.DataFrame] = []
    trade_rows: list[pd.DataFrame] = []
    equity_by_topk: dict[int, list[dict[str, object]]] = {top_k: [] for top_k in TOP_KS}
    equity_values = {top_k: 1.0 for top_k in TOP_KS}
    metric_labels: list[np.ndarray] = []
    metric_scores: list[np.ndarray] = []

    model: HistGradientBoostingRegressor | None = None
    for idx, rebalance_date in enumerate(rebalance_dates):
        rebalance_key = np.datetime64(rebalance_date, "ns")
        test_start = int(date_values.searchsorted(rebalance_key, side="left"))
        test_end = int(date_values.searchsorted(rebalance_key, side="right"))
        if test_start <= 0 or test_end <= test_start:
            continue

        if model is None or idx % args.retrain_every == 0:
            train_slice = df.iloc[:test_start]
            X_train = build_feature_frame(train_slice, feature_cols, categorical_cols, category_mappings)
            model = build_model(args.max_iter)
            print(
                f"retrain {idx + 1}/{len(rebalance_dates)} on {pd.Timestamp(rebalance_date).date()}: "
                f"train_rows={len(X_train)} features={len(feature_cols)}",
                flush=True,
            )
            model.fit(X_train, y_return[:test_start])

        test_slice = df.iloc[test_start:test_end]
        X_test = build_feature_frame(test_slice, feature_cols, categorical_cols, category_mappings)
        score = model.predict(X_test).astype(np.float32, copy=False)
        scored = test_slice.loc[:, meta_cols].copy()
        scored["label"] = y_label[test_start:test_end]
        scored["future_return"] = y_return[test_start:test_end]
        scored["score"] = score
        prediction_rows.append(scored.copy())
        metric_labels.append(y_label[test_start:test_end].copy())
        metric_scores.append(score.copy())

        ranked = scored.sort_values("score", ascending=False, kind="mergesort")
        for top_k in TOP_KS:
            picks = ranked.head(top_k).copy()
            portfolio_return = float(picks["future_return"].mean())
            equity_values[top_k] *= 1.0 + portfolio_return
            equity_by_topk[top_k].append(
                {
                    "rebalance_date": rebalance_date,
                    "portfolio_return": portfolio_return,
                    "equity": equity_values[top_k],
                    "num_picks": int(len(picks)),
                }
            )
            picks.insert(0, "top_k", top_k)
            picks.insert(0, "rebalance_date", rebalance_date)
            trade_rows.append(picks)

    predictions = pd.concat(prediction_rows, ignore_index=True)
    trades = pd.concat(trade_rows, ignore_index=True)
    predictions.to_parquet(output_dir / "oos_predictions.parquet", index=False)
    trades.to_parquet(output_dir / "trade_log_all_topk.parquet", index=False)

    labels = np.concatenate(metric_labels)
    scores = np.concatenate(metric_scores)
    oos_metrics = {
        "roc_auc_for_label": float(roc_auc_score(labels, scores)),
        "return_mae": float(mean_absolute_error(predictions["future_return"], predictions["score"])),
        "return_rmse": float(mean_squared_error(predictions["future_return"], predictions["score"]) ** 0.5),
        "positive_rate": float(labels.mean()),
    }

    summaries: list[dict[str, object]] = []
    for top_k, rows in equity_by_topk.items():
        equity_df = pd.DataFrame(rows)
        equity_df.to_parquet(output_dir / f"equity_curve_topk_{top_k}.parquet", index=False)
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": "sklearn_hist_gradient_boosting_regressor",
            "train_path": str(train_path),
            "num_rows": int(len(df)),
            "num_codes": int(df["code"].nunique()),
            "num_trade_dates": int(df["date"].nunique()),
            "min_train_days": args.min_train_days,
            "retrain_every": args.retrain_every,
            "rebalance_every": args.rebalance_every,
            "max_iter": args.max_iter,
            "num_features": int(len(feature_cols)),
            "categorical_cols": categorical_cols,
            "oos_metrics": oos_metrics,
            **summarize_topk(rows, top_k),
        }
        (output_dir / f"summary_topk_{top_k}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summaries.append(summary)

    new_rows = [
        {
            "model": "hgb_regressor_fast",
            "top_k": int(summary["top_k"]),
            "total_return": float(summary["portfolio_total_return"]),
            "cagr": float(summary["portfolio_cagr"]),
            "max_drawdown": float(summary["portfolio_max_drawdown"]),
            "win_rate": float(summary["portfolio_win_rate"]),
            "num_rebalances": int(summary["num_rebalances"]),
        }
        for summary in summaries
    ]
    comparison = pd.DataFrame([*load_baseline_rows(baseline_dir), *new_rows])
    comparison = comparison.sort_values(["top_k", "total_return"], ascending=[True, False]).reset_index(drop=True)
    comparison.to_csv(output_dir / "comparison_vs_existing_topk.csv", index=False, encoding="utf-8-sig")

    best_existing = (
        comparison[comparison["model"] != "hgb_regressor_fast"]
        .sort_values(["top_k", "total_return"], ascending=[True, False])
        .groupby("top_k", as_index=False)
        .first()
    )
    new_df = pd.DataFrame(new_rows)
    delta = new_df.merge(best_existing, on="top_k", how="left", suffixes=("_new", "_best_old"))
    delta["total_return_delta"] = delta["total_return_new"] - delta["total_return_best_old"]
    delta["cagr_delta"] = delta["cagr_new"] - delta["cagr_best_old"]
    delta["drawdown_delta"] = delta["max_drawdown_new"] - delta["max_drawdown_best_old"]
    delta.to_csv(output_dir / "new_model_delta_vs_best_old.csv", index=False, encoding="utf-8-sig")

    report_lines = [
        "# CSI500 Fast Alternative Model Executive Summary",
        "",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- New model: sklearn HistGradientBoostingRegressor, max_iter={args.max_iter}",
        f"- Backtest window: {summaries[0]['backtest_start']} to {summaries[0]['backtest_end']}",
        f"- Data: {len(df):,} rows, {df['code'].nunique():,} stocks, {df['date'].nunique():,} trade dates",
        "",
        "## New Model vs Best Existing Baseline",
        "",
        "| top_k | new total return | best old model | best old total return | delta | new max drawdown |",
        "|---:|---:|---|---:|---:|---:|",
    ]
    for row in delta.sort_values("top_k").to_dict("records"):
        report_lines.append(
            f"| {int(row['top_k'])} | {row['total_return_new']:.2%} | {row['model_best_old']} | "
            f"{row['total_return_best_old']:.2%} | {row['total_return_delta']:.2%} | "
            f"{row['max_drawdown_new']:.2%} |"
        )
    report_lines.extend(
        [
            "",
            "## All Model Rankings By Top-K",
            "",
            comparison.to_markdown(index=False, floatfmt=".4f"),
            "",
        ]
    )
    (output_dir / "executive_summary.md").write_text("\n".join(report_lines), encoding="utf-8")

    print("DONE")
    print(delta.sort_values("top_k").to_string(index=False))
    print(f"outputs: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
