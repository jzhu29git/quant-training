from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import duckdb
import pyarrow.parquet as pq

from app.config import get_settings
from app.serializers import records_to_json

MAX_PAGE_SIZE = 200
MAX_EXPORT_ROWS = 200_000


@dataclass(frozen=True)
class ExplorerDatasetSpec:
    key: str
    label: str
    description: str
    path: Path
    default_columns: tuple[str, ...]
    searchable_columns: tuple[str, ...]
    default_sort_by: str
    default_sort_dir: str = "desc"


def _dataset_specs() -> dict[str, ExplorerDatasetSpec]:
    settings = get_settings()
    return {
        "training_features": ExplorerDatasetSpec(
            key="training_features",
            label="Step 2 Training Features",
            description="Full training feature matrix used by model training and walk-forward backtest.",
            path=settings.quant_dir / "ml_features_ready.parquet",
            default_columns=("date", "code", "name", "industry", "label", "future_return", "close", "volume"),
            searchable_columns=("code", "name", "industry", "exchange"),
            default_sort_by="date",
        ),
        "inference_features": ExplorerDatasetSpec(
            key="inference_features",
            label="Step 3 Inference Features",
            description="Latest inference feature matrix before model scoring.",
            path=settings.quant_dir / "inference_features_latest.parquet",
            default_columns=("date", "code", "name", "industry", "close", "volume", "turnover", "pe_ttm"),
            searchable_columns=("code", "name", "industry", "exchange"),
            default_sort_by="date",
        ),
        "inference_scores": ExplorerDatasetSpec(
            key="inference_scores",
            label="Step 4 Inference Scores",
            description="Latest scored universe with ranking signals and price context.",
            path=settings.models_dir / "inference_scores_latest.parquet",
            default_columns=("date", "code", "name", "industry", "score", "close", "bias_20", "pe_ttm", "pb"),
            searchable_columns=("code", "name", "industry", "exchange"),
            default_sort_by="score",
        ),
        "oos_predictions": ExplorerDatasetSpec(
            key="oos_predictions",
            label="Step 5 OOS Predictions",
            description="Walk-forward out-of-sample predictions across all rebalances.",
            path=settings.backtests_dir / "oos_predictions.parquet",
            default_columns=("date", "code", "name", "industry", "score", "future_return", "label"),
            searchable_columns=("code", "name", "industry"),
            default_sort_by="date",
        ),
        "trade_log": ExplorerDatasetSpec(
            key="trade_log",
            label="Step 5 Trade Log",
            description="Rebalance-level top-K selections chosen by the walk-forward backtest.",
            path=settings.backtests_dir / "trade_log.parquet",
            default_columns=("rebalance_date", "code", "name", "industry", "score", "future_return", "label"),
            searchable_columns=("code", "name", "industry"),
            default_sort_by="rebalance_date",
        ),
    }


def _spec(dataset_key: str) -> ExplorerDatasetSpec:
    spec = _dataset_specs().get(dataset_key)
    if spec is None:
        raise FileNotFoundError(dataset_key)
    return spec


def _file_meta(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _schema(spec: ExplorerDatasetSpec) -> list[dict[str, str]]:
    parquet = pq.ParquetFile(spec.path)
    schema = parquet.schema_arrow
    return [{"name": field.name, "type": str(field.type)} for field in schema]


def _metadata(spec: ExplorerDatasetSpec) -> dict[str, Any]:
    parquet = pq.ParquetFile(spec.path)
    meta = _file_meta(spec.path) or {}
    columns = _schema(spec)
    return {
        "key": spec.key,
        "label": spec.label,
        "description": spec.description,
        "path": meta.get("path"),
        "row_count": int(parquet.metadata.num_rows),
        "column_count": len(columns),
        "size_bytes": meta.get("size_bytes"),
        "updated_at": meta.get("updated_at"),
        "default_columns": [column for column in spec.default_columns if any(item["name"] == column for item in columns)],
        "searchable_columns": [column for column in spec.searchable_columns if any(item["name"] == column for item in columns)],
        "columns": columns,
    }


def get_explorer_catalog() -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    for spec in _dataset_specs().values():
        if spec.path.exists():
            datasets.append(_metadata(spec))
        else:
            datasets.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "description": spec.description,
                    "path": str(spec.path),
                    "row_count": 0,
                    "column_count": 0,
                    "size_bytes": 0,
                    "updated_at": None,
                    "default_columns": list(spec.default_columns),
                    "searchable_columns": list(spec.searchable_columns),
                    "columns": [],
                }
            )
    return {"datasets": datasets}


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _normalize_sort_dir(value: str | None) -> str:
    return "asc" if (value or "").lower() == "asc" else "desc"


def _allowed_columns(spec: ExplorerDatasetSpec) -> list[str]:
    return [column["name"] for column in _metadata(spec)["columns"]]


def _type_map(spec: ExplorerDatasetSpec) -> dict[str, str]:
    return {column["name"]: column["type"] for column in _metadata(spec)["columns"]}


def _is_numeric(type_name: str) -> bool:
    lowered = type_name.lower()
    return any(token in lowered for token in ["int", "float", "double", "decimal"])


def _is_temporal(type_name: str) -> bool:
    lowered = type_name.lower()
    return "date" in lowered or "time" in lowered


def _cast_sql(type_name: str) -> str:
    if _is_numeric(type_name):
        return "DOUBLE"
    if _is_temporal(type_name):
        return "TIMESTAMP"
    if "bool" in type_name.lower():
        return "BOOLEAN"
    return "VARCHAR"


def _parse_filters(filters: list[str]) -> list[dict[str, str | None]]:
    parsed: list[dict[str, str | None]] = []
    for raw in filters:
        if not raw.strip():
            continue
        payload = json.loads(raw)
        parsed.append(
            {
                "column": str(payload.get("column") or "").strip(),
                "operator": str(payload.get("operator") or "").strip(),
                "value": None if payload.get("value") in (None, "") else str(payload.get("value")),
                "value_to": None if payload.get("value_to") in (None, "") else str(payload.get("value_to")),
            }
        )
    return parsed


def _where_clauses(
    *,
    spec: ExplorerDatasetSpec,
    search: str,
    filters: list[dict[str, str | None]],
) -> tuple[list[str], list[Any]]:
    allowed_columns = set(_allowed_columns(spec))
    type_map = _type_map(spec)
    clauses: list[str] = []
    params: list[Any] = []

    if search.strip():
        needle = f"%{search.strip().lower()}%"
        search_columns = [column for column in spec.searchable_columns if column in allowed_columns]
        if search_columns:
            sub: list[str] = []
            for column in search_columns:
                sub.append(f"LOWER(CAST({_quote_identifier(column)} AS VARCHAR)) LIKE ?")
                params.append(needle)
            clauses.append("(" + " OR ".join(sub) + ")")

    for item in filters:
        column = item["column"] or ""
        operator = (item["operator"] or "").lower()
        value = item["value"]
        value_to = item["value_to"]
        if column not in allowed_columns or not operator:
            continue

        column_sql = _quote_identifier(column)
        type_name = type_map.get(column, "VARCHAR")
        cast_type = _cast_sql(type_name)

        if operator == "is_null":
            clauses.append(f"{column_sql} IS NULL")
            continue
        if operator == "not_null":
            clauses.append(f"{column_sql} IS NOT NULL")
            continue
        if operator in {"contains", "starts_with", "ends_with"}:
            if value is None:
                continue
            if operator == "contains":
                params.append(f"%{value.lower()}%")
            elif operator == "starts_with":
                params.append(f"{value.lower()}%")
            else:
                params.append(f"%{value.lower()}")
            clauses.append(f"LOWER(CAST({column_sql} AS VARCHAR)) LIKE ?")
            continue
        if operator == "between":
            if value is None or value_to is None:
                continue
            clauses.append(f"{column_sql} BETWEEN CAST(? AS {cast_type}) AND CAST(? AS {cast_type})")
            params.extend([value, value_to])
            continue
        if value is None:
            continue

        operator_sql = {
            "eq": "=",
            "neq": "!=",
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
        }.get(operator)
        if operator_sql is None:
            continue
        clauses.append(f"{column_sql} {operator_sql} CAST(? AS {cast_type})")
        params.append(value)

    return clauses, params


def _query(
    *,
    spec: ExplorerDatasetSpec,
    selected_columns: list[str],
    search: str,
    filters: list[dict[str, str | None]],
    sort_by: str,
    sort_dir: str,
    limit: int | None,
    offset: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    all_columns = _allowed_columns(spec)
    columns = [column for column in selected_columns if column in all_columns]
    if not columns:
        columns = [column for column in spec.default_columns if column in all_columns] or all_columns[: min(10, len(all_columns))]

    safe_sort_by = sort_by if sort_by in all_columns else (spec.default_sort_by if spec.default_sort_by in all_columns else all_columns[0])
    safe_sort_dir = _normalize_sort_dir(sort_dir)
    clauses, clause_params = _where_clauses(spec=spec, search=search, filters=filters)
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    base_from = " FROM read_parquet(?)"
    path_param = [str(spec.path)]

    with duckdb.connect(database=":memory:") as con:
        count_query = "SELECT COUNT(*)" + base_from + where_sql
        filtered_rows = int(con.execute(count_query, path_param + clause_params).fetchone()[0])

        select_sql = ", ".join(_quote_identifier(column) for column in columns)
        sql = (
            "SELECT "
            + select_sql
            + base_from
            + where_sql
            + f" ORDER BY {_quote_identifier(safe_sort_by)} {safe_sort_dir.upper()}"
        )
        params = path_param + clause_params
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        if offset:
            sql += " OFFSET ?"
            params.append(offset)
        frame = con.execute(sql, params).df()

    return records_to_json(frame.to_dict(orient="records")), filtered_rows


def query_explorer_dataset(
    *,
    dataset_key: str,
    search: str = "",
    filter_payloads: list[str] | None = None,
    columns: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    spec = _spec(dataset_key)
    if not spec.path.exists():
        raise FileNotFoundError(spec.path)

    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    filter_specs = _parse_filters(filter_payloads or [])
    metadata = _metadata(spec)
    selected_columns = columns or metadata["default_columns"]

    rows, filtered_rows = _query(
        spec=spec,
        selected_columns=selected_columns,
        search=search,
        filters=filter_specs,
        sort_by=sort_by or spec.default_sort_by,
        sort_dir=sort_dir or spec.default_sort_dir,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    total_pages = max((filtered_rows + page_size - 1) // page_size, 1)

    return {
        "dataset": metadata,
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "total_rows": metadata["row_count"],
        "filtered_rows": filtered_rows,
        "total_pages": total_pages,
        "search": search,
        "sort_by": sort_by or spec.default_sort_by,
        "sort_dir": _normalize_sort_dir(sort_dir),
        "selected_columns": [column for column in selected_columns if column in _allowed_columns(spec)],
        "applied_filters": filter_specs,
        "max_export_rows": MAX_EXPORT_ROWS,
    }


def export_explorer_dataset(
    *,
    dataset_key: str,
    export_format: str,
    search: str = "",
    filter_payloads: list[str] | None = None,
    columns: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> tuple[Path, str]:
    spec = _spec(dataset_key)
    if not spec.path.exists():
        raise FileNotFoundError(spec.path)

    metadata = _metadata(spec)
    selected_columns = columns or metadata["default_columns"]
    filter_specs = _parse_filters(filter_payloads or [])
    rows, filtered_rows = _query(
        spec=spec,
        selected_columns=selected_columns,
        search=search,
        filters=filter_specs,
        sort_by=sort_by or spec.default_sort_by,
        sort_dir=sort_dir or spec.default_sort_dir,
        limit=MAX_EXPORT_ROWS + 1,
    )
    if filtered_rows > MAX_EXPORT_ROWS:
        raise ValueError(f"Export is limited to {MAX_EXPORT_ROWS} rows. Narrow the query first.")

    suffix = ".parquet" if export_format == "parquet" else ".csv"
    with NamedTemporaryFile(prefix=f"{dataset_key}_", suffix=suffix, delete=False) as handle:
        export_path = Path(handle.name)

    if export_format == "parquet":
        import pandas as pd

        pd.DataFrame(rows).to_parquet(export_path, index=False)
    else:
        import pandas as pd

        pd.DataFrame(rows).to_csv(export_path, index=False)

    filename = f"{dataset_key}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{suffix}"
    return export_path, filename
