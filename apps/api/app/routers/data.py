from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse

from app.services.data import get_data_summary, get_pipeline_summary, get_stock_detail, list_stocks
from app.services.explorer import export_explorer_dataset, get_explorer_catalog, query_explorer_dataset

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/summary")
def data_summary() -> dict[str, object]:
    return get_data_summary()


@router.get("/pipeline")
def pipeline_summary() -> dict[str, object]:
    return get_pipeline_summary()


@router.get("/stocks")
def stocks(limit: int = Query(default=50, ge=1, le=200), search: str = "") -> list[dict[str, object]]:
    return list_stocks(limit=limit, search=search)


@router.get("/stock/{code}")
def stock_detail(code: str) -> dict[str, object]:
    try:
        return get_stock_detail(code)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Stock {exc.args[0]} not found in local parquet store.") from exc


@router.get("/explorer/catalog")
def explorer_catalog() -> dict[str, object]:
    return get_explorer_catalog()


@router.get("/explorer/query")
def explorer_query(
    dataset: str,
    search: str = "",
    filter: list[str] = Query(default=[]),
    columns: list[str] = Query(default=[]),
    sort_by: str | None = None,
    sort_dir: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    try:
        return query_explorer_dataset(
            dataset_key=dataset,
            search=search,
            filter_payloads=filter,
            columns=columns,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Dataset {exc.args[0]} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/explorer/export")
def explorer_export(
    background_tasks: BackgroundTasks,
    dataset: str,
    export_format: str = Query(default="csv"),
    search: str = "",
    filter: list[str] = Query(default=[]),
    columns: list[str] = Query(default=[]),
    sort_by: str | None = None,
    sort_dir: str | None = None,
):
    try:
        path, filename = export_explorer_dataset(
            dataset_key=dataset,
            export_format=export_format,
            search=search,
            filter_payloads=filter,
            columns=columns,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Dataset {exc.args[0]} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(Path.unlink, path, True)
    media_type = "application/octet-stream"
    if export_format == "csv":
        media_type = "text/csv"
    elif export_format == "parquet":
        media_type = "application/octet-stream"
    return FileResponse(path, filename=filename, media_type=media_type, background=background_tasks)
