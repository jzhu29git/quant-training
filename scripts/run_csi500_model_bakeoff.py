#!/usr/bin/env python3
"""Compare several fast CSI500 models on the same walk-forward top-k test."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from train_lightgbm import build_category_mappings, build_feature_frame, choose_feature_columns, load_frame


DEFAULT_TRAIN_PATH = "quant_data/csi500_2y_run/ml_features_ready.parquet"
DEFAULT_OUTPUT_DIR = "quant_data/csi500_2y_run/model_bakeoff_fast"
TOP_KS = [1, 3, 5, 10, 20]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast CSI500 model bakeoff.")
    parser.add_argument("--train-path", default=DEFAULT_TRAIN_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-train-days", type=int, default=252)
    parser.add_argument("--retrain-every", type=int, default=20)
    parser.add_argument("--rebalance-every", type=int, default=5)
    return parser.parse_args()


def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    return float((equity_curve / running_max - 1.0).min())


def annualized_return(equity_curve: pd.Series, dates: pd.Series) -> float:
    start = pd.to_datetime(dates.iloc[0])
    end = pd.to_datetime(dates.iloc[-1])
    years = max((end - start).days, 1) / 365.25
    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0)
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def daily_relevance(df: pd.DataFrame) -> np.ndarray:
    ranks = df.groupby("date", sort=False)["future_return"].rank(pct=True, method="first")
    return np.floor(ranks.fillna(0.0).to_numpy(dtype=np.float32) * 5.0).clip(0, 4).astype(np.int32)


def train_model(model_name: str, X_train: pd.DataFrame, y_return: np.ndarray, y_rank: np.ndarray, group: list[int]):
    if model_name == "lightgbm_regressor":
        model = lgb.LGBMRegressor(
            objective="regression",
            learning_rate=0.04,
            n_estimators=220,
            num_leaves=31,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            n_jobs=1,
            verbosity=-1,
        )
        model.fit(X_train, y_return)
        return model
    if model_name == "lightgbm_ranker":
        model = lgb.LGBMRanker(
            objective="lambdarank",
            metric="ndcg",
            learning_rate=0.04,
            n_estimators=180,
            num_leaves=31,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            n_jobs=1,
            verbosity=-1,
        )
        model.fit(X_train, y_rank, group=group)
        return model
    if model_name == "extra_trees":
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesRegressor(
                n_estimators=120,
                max_depth=10,
                min_samples_leaf=20,
                random_state=42,
                n_jobs=-1,
            ),
        )
        model.fit(X_train, y_return)
        return model
    if model_name == "ridge":
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            Ridge(alpha=20.0, random_state=42),
        )
        model.fit(X_train, y_return)
        return model
    raise ValueError(model_name)


def summarize_equity(rows: list[dict[str, object]], model_name: str, top_k: int) -> dict[str, object]:
    equity_df = pd.DataFrame(rows)
    return {
        "model": model_name,
        "top_k": top_k,
        "num_rebalances": int(len(equity_df)),
        "total_return": float(equity_df["equity"].iloc[-1] - 1.0),
        "cagr": annualized_return(equity_df["equity"], equity_df["rebalance_date"]),
        "max_drawdown": max_drawdown(equity_df["equity"]),
        "win_rate": float((equity_df["portfolio_return"] > 0).mean()),
        "avg_return": float(equity_df["portfolio_return"].mean()),
        "std_return": float(equity_df["portfolio_return"].std(ddof=0)),
        "backtest_start": str(pd.to_datetime(equity_df["rebalance_date"].min()).date()),
        "backtest_end": str(pd.to_datetime(equity_df["rebalance_date"].max()).date()),
    }


def main() -> int:
    args = parse_args()
    train_path = Path(args.train_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_frame(train_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date", kind="stable").reset_index(drop=True)
    feature_cols, categorical_cols = choose_feature_columns(df)
    category_mappings = build_category_mappings(df, df, categorical_cols)

    date_values = df["date"].to_numpy(dtype="datetime64[ns]")
    y_return = pd.to_numeric(df["future_return"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float32)
    y_rank = daily_relevance(df)
    y_label = pd.to_numeric(df["label"], errors="coerce").fillna(0).to_numpy(dtype=np.int8)
    unique_dates = pd.Index(pd.unique(date_values[~pd.isna(date_values)]))
    rebalance_dates = unique_dates[args.min_train_days :: args.rebalance_every]
    model_names = ["lightgbm_regressor", "lightgbm_ranker", "extra_trees", "ridge"]

    rows: list[dict[str, object]] = []
    metrics_rows: list[dict[str, object]] = []
    latest_pick_rows: list[pd.DataFrame] = []

    for model_name in model_names:
        print(f"\n=== {model_name} ===", flush=True)
        model = None
        equity_values = {top_k: 1.0 for top_k in TOP_KS}
        equity_by_topk: dict[int, list[dict[str, object]]] = {top_k: [] for top_k in TOP_KS}
        metric_labels: list[np.ndarray] = []
        metric_returns: list[np.ndarray] = []
        metric_scores: list[np.ndarray] = []

        for idx, rebalance_date in enumerate(rebalance_dates):
            rebalance_key = np.datetime64(rebalance_date, "ns")
            test_start = int(date_values.searchsorted(rebalance_key, side="left"))
            test_end = int(date_values.searchsorted(rebalance_key, side="right"))
            if test_start <= 0 or test_end <= test_start:
                continue

            if model is None or idx % args.retrain_every == 0:
                train_slice = df.iloc[:test_start]
                X_train = build_feature_frame(train_slice, feature_cols, categorical_cols, category_mappings)
                group = train_slice.groupby("date", sort=False).size().astype(int).tolist()
                print(
                    f"train {pd.Timestamp(rebalance_date).date()} rows={len(X_train)} features={len(feature_cols)}",
                    flush=True,
                )
                model = train_model(model_name, X_train, y_return[:test_start], y_rank[:test_start], group)

            test_slice = df.iloc[test_start:test_end]
            X_test = build_feature_frame(test_slice, feature_cols, categorical_cols, category_mappings)
            score = np.asarray(model.predict(X_test), dtype=np.float32)
            metric_labels.append(y_label[test_start:test_end].copy())
            metric_returns.append(y_return[test_start:test_end].copy())
            metric_scores.append(score.copy())

            scored = test_slice.loc[:, [c for c in ["date", "code", "name", "industry"] if c in test_slice.columns]].copy()
            scored["future_return"] = y_return[test_start:test_end]
            scored["score"] = score
            ranked = scored.sort_values("score", ascending=False, kind="mergesort")
            if idx == len(rebalance_dates) - 1:
                temp = ranked.head(20).copy()
                temp.insert(0, "model", model_name)
                latest_pick_rows.append(temp)

            for top_k in TOP_KS:
                picks = ranked.head(top_k)
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

        labels = np.concatenate(metric_labels)
        returns = np.concatenate(metric_returns)
        scores = np.concatenate(metric_scores)
        model_metrics = {
            "model": model_name,
            "roc_auc_for_label": float(roc_auc_score(labels, scores)),
            "return_mae": float(mean_absolute_error(returns, scores)),
            "return_rmse": float(mean_squared_error(returns, scores) ** 0.5),
        }
        metrics_rows.append(model_metrics)

        for top_k, equity_rows in equity_by_topk.items():
            summary = summarize_equity(equity_rows, model_name, top_k)
            rows.append({**summary, **model_metrics})
            pd.DataFrame(equity_rows).to_parquet(output_dir / f"equity_{model_name}_topk_{top_k}.parquet", index=False)

    comparison = pd.DataFrame(rows).sort_values(["top_k", "total_return"], ascending=[True, False]).reset_index(drop=True)
    comparison.to_csv(output_dir / "model_topk_comparison.csv", index=False, encoding="utf-8-sig")
    comparison.to_json(output_dir / "model_topk_comparison.json", orient="records", force_ascii=False, indent=2)
    pd.DataFrame(metrics_rows).to_csv(output_dir / "model_oos_metrics.csv", index=False, encoding="utf-8-sig")
    if latest_pick_rows:
        pd.concat(latest_pick_rows, ignore_index=True).to_csv(output_dir / "latest_rebalance_top20_by_model.csv", index=False, encoding="utf-8-sig")

    winners = comparison.sort_values(["top_k", "total_return"], ascending=[True, False]).groupby("top_k", as_index=False).first()
    report = [
        "# CSI500 Fast Model Bakeoff",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Data: {train_path}",
        f"Rows: {len(df):,}; stocks: {df['code'].nunique():,}; trade dates: {df['date'].nunique():,}",
        "",
        "## Winners",
        "",
        "| top_k | winner | total return | cagr | max drawdown | win rate |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for row in winners.to_dict("records"):
        report.append(
            f"| {int(row['top_k'])} | {row['model']} | {row['total_return']:.2%} | "
            f"{row['cagr']:.2%} | {row['max_drawdown']:.2%} | {row['win_rate']:.2%} |"
        )
    report.extend(["", "## Full Ranking", "", comparison.to_markdown(index=False, floatfmt=".4f"), ""])
    (output_dir / "executive_summary.md").write_text("\n".join(report), encoding="utf-8")

    print("\nWINNERS")
    print(winners[["top_k", "model", "total_return", "cagr", "max_drawdown", "win_rate"]].to_string(index=False))
    print(f"\noutputs: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
