from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from app.config import get_settings
from app.serializers import records_to_json, to_jsonable
from app.services.files import read_json
from app.services.model_profiles import get_model_profile_catalog


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError):
        return pd.DataFrame()


def _safe_read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, columns=columns)
    except (pa.ArrowException, OSError, ValueError):
        return pd.DataFrame()


def _file_updated_at(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return None


def _parquet_date_max(path: Path, *, column: str) -> str | None:
    frame = _safe_read_parquet(path, columns=[column])
    if frame.empty or column not in frame.columns:
        return None
    date_series = pd.to_datetime(frame[column], errors="coerce")
    if date_series.dropna().empty:
        return None
    return pd.Timestamp(date_series.max()).date().isoformat()


def _enrich_backtest_profile(summary: dict[str, Any], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    if not summary:
        return {}
    if summary.get("profile_name") and summary.get("profile_label"):
        return summary

    candidate = None
    for profile in profiles:
        if (
            summary.get("rebalance_every") == profile.get("backtest_rebalance_every")
            and summary.get("retrain_every") == profile.get("backtest_retrain_every")
            and summary.get("top_k") == profile.get("backtest_top_k")
            and summary.get("threshold") == profile.get("score_threshold")
        ):
            candidate = profile
            break
    if candidate is None and profiles:
        candidate = profiles[0]
    if candidate is None:
        return summary

    enriched = dict(summary)
    enriched.setdefault("profile_name", candidate.get("name"))
    enriched.setdefault("profile_label", candidate.get("label"))
    return enriched


def _backtest_run_rows() -> list[dict[str, Any]]:
    settings = get_settings()
    catalog = get_model_profile_catalog()
    profiles = catalog["profiles"]
    label_by_name = {profile["name"]: profile["label"] for profile in profiles}
    runs_dir = settings.backtests_dir / "runs"
    rows: list[dict[str, Any]] = []

    summary_files = sorted(runs_dir.glob("*/summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for summary_path in summary_files:
        summary = read_json(summary_path)
        if not summary:
            continue
        profile_name = str(summary.get("profile_name") or "").strip() or None
        rows.append(
            {
                "run_id": summary.get("run_id") or summary_path.parent.name,
                "profile_name": profile_name,
                "profile_label": summary.get("profile_label") or (label_by_name.get(profile_name) if profile_name else None),
                "generated_at": summary.get("generated_at"),
                "portfolio_total_return": summary.get("portfolio_total_return"),
                "portfolio_cagr": summary.get("portfolio_cagr"),
                "portfolio_max_drawdown": summary.get("portfolio_max_drawdown"),
                "portfolio_win_rate": summary.get("portfolio_win_rate"),
                "num_rebalances": summary.get("num_rebalances"),
                "backtest_start": summary.get("backtest_start"),
                "backtest_end": summary.get("backtest_end"),
                "summary_path": str(summary_path),
            }
        )

    if rows:
        return rows

    latest_summary = read_json(settings.backtests_dir / "summary.json")
    if latest_summary:
        latest_summary = _enrich_backtest_profile(latest_summary, profiles)
        profile_name = str(latest_summary.get("profile_name") or "").strip() or None
        return [
            {
                "run_id": latest_summary.get("run_id") or "latest",
                "profile_name": profile_name,
                "profile_label": latest_summary.get("profile_label") or (label_by_name.get(profile_name) if profile_name else None),
                "generated_at": latest_summary.get("generated_at"),
                "portfolio_total_return": latest_summary.get("portfolio_total_return"),
                "portfolio_cagr": latest_summary.get("portfolio_cagr"),
                "portfolio_max_drawdown": latest_summary.get("portfolio_max_drawdown"),
                "portfolio_win_rate": latest_summary.get("portfolio_win_rate"),
                "num_rebalances": latest_summary.get("num_rebalances"),
                "backtest_start": latest_summary.get("backtest_start"),
                "backtest_end": latest_summary.get("backtest_end"),
                "summary_path": str(settings.backtests_dir / "summary.json"),
            }
        ]
    return []


def get_model_overview() -> dict[str, Any]:
    settings = get_settings()
    metadata = read_json(settings.models_dir / "training_metadata.json")
    profile_catalog = get_model_profile_catalog()
    backtest = _enrich_backtest_profile(read_json(settings.backtests_dir / "summary.json"), profile_catalog["profiles"])
    importance_df = _safe_read_csv(settings.models_dir / "feature_importance.csv")
    backtest_runs = _backtest_run_rows()

    top_features: list[dict[str, Any]] = []
    if not importance_df.empty:
        columns = [col for col in ["feature", "importance_gain", "importance_split"] if col in importance_df.columns]
        top_features = records_to_json(
            importance_df[columns]
            .sort_values("importance_gain", ascending=False)
            .head(20)
            .to_dict(orient="records")
        )

    return {
        "training_metadata": metadata,
        "backtest_summary": backtest,
        "backtest_runs": backtest_runs,
        "model_profiles": profile_catalog["profiles"],
        "default_profile": profile_catalog["default_profile"],
        "top_features": top_features,
    }


def get_latest_picks(*, limit: int = 25) -> dict[str, Any]:
    settings = get_settings()
    scores_path = settings.models_dir / "inference_scores_latest.parquet"
    features_path = settings.quant_dir / "inference_features_latest.parquet"
    scores_df = _safe_read_parquet(scores_path)
    feature_time = _file_updated_at(features_path)
    model_time = _file_updated_at(scores_path)
    source_close_date = _parquet_date_max(features_path, column="date")
    raw_sync_date = _parquet_date_max(settings.stock_list_path, column="trade_date") or _parquet_date_max(
        settings.stock_registry_path,
        column="trade_date",
    )
    if scores_df.empty:
        return {
            "rows": 0,
            "latest_date": None,
            "source_close_date": source_close_date,
            "raw_sync_date": raw_sync_date,
            "feature_time": feature_time,
            "data_src_time": feature_time,
            "model_time": model_time,
            "picks": [],
        }

    latest_signal_date = None
    snapshot_df = scores_df.copy()
    if "date" in scores_df.columns:
        scores_df["date"] = pd.to_datetime(scores_df["date"], errors="coerce")
        latest_signal = scores_df["date"].max()
        if not pd.isna(latest_signal):
            latest_signal_date = pd.Timestamp(latest_signal).date().isoformat()
            snapshot_df = scores_df.loc[scores_df["date"].eq(latest_signal)].copy()

    top_df = snapshot_df.sort_values("score", ascending=False).head(limit).copy()
    if "date" in top_df.columns:
        top_df.insert(0, "signal_date", top_df["date"].dt.strftime("%Y-%m-%d"))
    top_df.insert(0, "rank", range(1, len(top_df) + 1))
    top_df["feature_time"] = feature_time
    top_df["data_src_time"] = feature_time
    top_df["model_time"] = model_time
    ordered_columns = [
        col
        for col in [
            "rank",
            "signal_date",
            "feature_time",
            "model_time",
            "code",
            "name",
            "industry",
            "score",
            "close",
            "bias_20",
            "pe_ttm",
            "pb",
        ]
        if col in top_df.columns
    ]
    return {
        "rows": int(len(scores_df)),
        "latest_date": latest_signal_date,
        "source_close_date": source_close_date or latest_signal_date,
        "raw_sync_date": raw_sync_date,
        "feature_time": feature_time,
        "data_src_time": feature_time,
        "model_time": model_time,
        "picks": records_to_json(top_df[ordered_columns].to_dict(orient="records")),
    }
