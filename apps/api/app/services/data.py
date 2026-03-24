from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.config import get_settings
from app.serializers import records_to_json, to_jsonable


def _code_path(directory: Path, code: str) -> Path:
    normalized = str(code).zfill(6)
    return directory / f"{normalized}.parquet"


def _frame_summary(df: pd.DataFrame, *, code: str) -> dict[str, Any]:
    if df.empty:
        return {
            "code": code,
            "rows": 0,
            "columns": list(df.columns),
            "date_min": None,
            "date_max": None,
            "head": [],
            "tail": [],
        }

    if "date" in df.columns:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        date_min = to_jsonable(df["date"].min())
        date_max = to_jsonable(df["date"].max())
    else:
        date_min = None
        date_max = None

    return {
        "code": code,
        "rows": int(len(df)),
        "columns": list(df.columns),
        "date_min": date_min,
        "date_max": date_max,
        "head": records_to_json(df.head(8).to_dict(orient="records")),
        "tail": records_to_json(df.tail(8).to_dict(orient="records")),
    }


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _safe_read_parquet(path: Path, *, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, columns=columns)
    except (pa.ArrowException, OSError, ValueError):
        return pd.DataFrame()


def _parquet_snapshot(path: Path, *, root: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        parquet = pq.ParquetFile(path)
        columns = parquet.schema.names
        snapshot: dict[str, Any] = {
            "path": _relative_path(path, root),
            "rows": int(parquet.metadata.num_rows),
            "columns": columns,
            "column_count": len(columns),
            "code_count": None,
            "date_min": None,
            "date_max": None,
        }

        tracked_columns = [col for col in ["date", "code"] if col in columns]
        if not tracked_columns:
            return snapshot

        tracked_df = parquet.read(columns=tracked_columns).to_pandas()
        if "code" in tracked_df.columns:
            snapshot["code_count"] = int(tracked_df["code"].astype(str).nunique())
        if "date" in tracked_df.columns:
            date_series = pd.to_datetime(tracked_df["date"], errors="coerce")
            snapshot["date_min"] = to_jsonable(date_series.min())
            snapshot["date_max"] = to_jsonable(date_series.max())
        return snapshot
    except (pa.ArrowException, OSError, ValueError):
        return None


def get_data_summary() -> dict[str, Any]:
    settings = get_settings()
    stock_df = _safe_read_parquet(settings.stock_list_path)
    registry_df = _safe_read_parquet(settings.stock_registry_path)
    subset_df = _safe_read_parquet(settings.stock_list_subset_path)
    kline_files = sorted((settings.quant_dir / "daily_kline").glob("*.parquet"))
    valuation_files = sorted((settings.quant_dir / "daily_valuation").glob("*.parquet"))
    total_size_bytes = sum(path.stat().st_size for path in settings.quant_dir.rglob("*") if path.is_file())

    latest_inference_path = settings.quant_dir / "inference_features_latest.parquet"
    inference_snapshot = None
    if latest_inference_path.exists():
        inference_df = _safe_read_parquet(latest_inference_path, columns=["date", "code"])
        inference_snapshot = {
            "rows": int(len(inference_df)),
            "code_count": int(inference_df["code"].astype(str).nunique()) if "code" in inference_df.columns else None,
            "latest_date": to_jsonable(pd.to_datetime(inference_df["date"], errors="coerce").max()),
        }

    return {
        "stock_count": int(len(stock_df)),
        "active_stock_count": int(len(stock_df)),
        "registry_stock_count": int(len(registry_df)),
        "subset_stock_count": int(len(subset_df)),
        "kline_file_count": len(kline_files),
        "valuation_file_count": len(valuation_files),
        "paired_file_count": min(len(kline_files), len(valuation_files)),
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "sample_codes": stock_df["code"].astype(str).str.zfill(6).head(12).tolist() if not stock_df.empty else [],
        "latest_inference_snapshot": inference_snapshot,
    }


def get_pipeline_summary() -> dict[str, Any]:
    settings = get_settings()
    return {
        "training_features": _parquet_snapshot(settings.quant_dir / "ml_features_ready.parquet", root=settings.project_root),
        "inference_features": _parquet_snapshot(settings.quant_dir / "inference_features_latest.parquet", root=settings.project_root),
        "inference_scores": _parquet_snapshot(settings.models_dir / "inference_scores_latest.parquet", root=settings.project_root),
    }


def list_stocks(*, limit: int = 50, search: str = "") -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.stock_list_path.exists():
        return []

    stock_df = pd.read_parquet(settings.stock_list_path)
    stock_df["code"] = stock_df["code"].astype(str).str.zfill(6)
    if search:
        search_lower = search.strip().lower()
        name_series = (
            stock_df["name"].astype(str)
            if "name" in stock_df.columns
            else pd.Series("", index=stock_df.index, dtype="string")
        )
        industry_series = (
            stock_df["industry"].astype(str)
            if "industry" in stock_df.columns
            else pd.Series("", index=stock_df.index, dtype="string")
        )
        mask = (
            stock_df["code"].str.contains(search_lower, case=False, na=False)
            | name_series.str.contains(search_lower, case=False, na=False)
            | industry_series.str.contains(search_lower, case=False, na=False)
        )
        stock_df = stock_df[mask].copy()

    columns = [col for col in ["code", "exchange", "name", "industry", "trade_date", "universe"] if col in stock_df.columns]
    return records_to_json(stock_df[columns].head(limit).to_dict(orient="records"))


def get_stock_detail(code: str) -> dict[str, Any]:
    settings = get_settings()
    normalized = str(code).zfill(6)

    stock_meta = None
    for path in [settings.stock_list_path, settings.stock_registry_path]:
        if not path.exists():
            continue
        stock_df = pd.read_parquet(path)
        stock_df["code"] = stock_df["code"].astype(str).str.zfill(6)
        matches = stock_df[stock_df["code"] == normalized]
        if not matches.empty:
            stock_meta = records_to_json(matches.head(1).to_dict(orient="records"))[0]
            break

    kline_path = _code_path(settings.quant_dir / "daily_kline", normalized)
    valuation_path = _code_path(settings.quant_dir / "daily_valuation", normalized)
    if not kline_path.exists() and not valuation_path.exists():
        raise FileNotFoundError(normalized)

    kline_df = pd.read_parquet(kline_path) if kline_path.exists() else pd.DataFrame()
    valuation_df = pd.read_parquet(valuation_path) if valuation_path.exists() else pd.DataFrame()
    return {
        "stock": stock_meta,
        "kline": _frame_summary(kline_df, code=normalized),
        "valuation": _frame_summary(valuation_df, code=normalized),
    }
