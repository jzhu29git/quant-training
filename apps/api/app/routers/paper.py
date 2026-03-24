from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.paper import (
    get_paper_trading_history,
    get_paper_trading_orders,
    get_paper_trading_overview,
    get_paper_trading_positions,
    get_paper_trading_status,
    get_paper_trading_targets,
)

router = APIRouter(prefix="/api/paper", tags=["paper"])


@router.get("/status")
def paper_status() -> dict[str, object]:
    return get_paper_trading_status()


@router.get("/overview")
def paper_overview() -> dict[str, object]:
    return get_paper_trading_overview()


@router.get("/targets")
def paper_targets(limit: int = Query(default=25, ge=1, le=200)) -> dict[str, object]:
    return get_paper_trading_targets(limit=limit)


@router.get("/positions")
def paper_positions(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return get_paper_trading_positions(limit=limit)


@router.get("/orders")
def paper_orders(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return get_paper_trading_orders(limit=limit)


@router.get("/history")
def paper_history(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return get_paper_trading_history(limit=limit)
