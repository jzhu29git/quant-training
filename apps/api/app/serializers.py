from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd


def to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        if pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def records_to_json(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: to_jsonable(val) for key, val in row.items()} for row in records]
