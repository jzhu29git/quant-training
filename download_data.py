#!/usr/bin/env python3
"""Download core A-share datasets for model training and store them as Parquet."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any


DEFAULT_START_DATE = "20200101"
DEFAULT_END_DATE = "20260322"
DEFAULT_DATA_DIR = "quant_data"

STOCK_LIST_FILENAME = "stock_list.parquet"
STOCK_REGISTRY_FILENAME = "stock_registry.parquet"
STOCK_LIST_SUBSET_FILENAME = "stock_list_subset.parquet"
FAILURES_FILENAME = "download_failures.csv"

KLINE_DIRNAME = "daily_kline"
VALUATION_DIRNAME = "daily_valuation"

REQUEST_RETRY_TIMES = 3
REQUEST_RETRY_SLEEP = 2.0

BAOSTOCK_DAILY_FIELDS = ",".join(
    [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "adjustflag",
        "turn",
        "tradestatus",
        "pctChg",
        "peTTM",
        "pbMRQ",
        "psTTM",
        "pcfNcfTTM",
        "isST",
    ]
)

AKSHARE_MARKET_CAP_COLUMNS = {
    "数据日期": "date",
    "总市值": "total_market_cap",
    "流通市值": "float_market_cap",
    "总股本": "total_shares",
    "流通股本": "float_shares",
}

NUMERIC_BAOSTOCK_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turn",
    "pctChg",
    "peTTM",
    "pbMRQ",
    "psTTM",
    "pcfNcfTTM",
]

ak: Any = None
bs: Any = None
pd: Any = None


def is_investable_stock_name(name: Any) -> bool:
    normalized = str(name).strip()
    if not normalized:
        return True
    return not normalized.endswith("退")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download A-share stock list, qfq daily kline and daily valuation data."
    )
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Output data directory.")
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help="Start date in YYYYMMDD format.",
    )
    parser.add_argument(
        "--end-date",
        default=DEFAULT_END_DATE,
        help="End date in YYYYMMDD format.",
    )
    parser.add_argument(
        "--universe",
        choices=("hs300", "all"),
        default="hs300",
        help="Download HS300 constituents first or the full A-share universe.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Only download the first N stocks in the selected universe; 0 means no limit.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds to sleep between requests to avoid rate limits.",
    )
    parser.add_argument(
        "--skip-stock-list",
        action="store_true",
        help="Skip refreshing stock_list.parquet.",
    )
    parser.add_argument(
        "--skip-kline",
        action="store_true",
        help="Skip downloading daily qfq kline files.",
    )
    parser.add_argument(
        "--skip-valuation",
        action="store_true",
        help="Skip downloading daily valuation files.",
    )
    parser.add_argument(
        "--skip-industry",
        action="store_true",
        help="Skip industry enrichment for a faster stock list refresh.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing parquet files instead of skipping them.",
    )
    return parser.parse_args()


def load_dependencies() -> None:
    global ak, bs, pd

    try:
        import akshare as ak_module
        import baostock as bs_module
        import pandas as pd_module
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "缺少依赖，请先安装 requirements.txt 中的包后再运行下载任务。"
        ) from exc

    ak = ak_module
    bs = bs_module
    pd = pd_module


def ensure_pandas_loaded() -> None:
    global pd
    if pd is None:
        import pandas as pd_module

        pd = pd_module


def ensure_dirs(data_dir: Path) -> tuple[Path, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    kline_dir = data_dir / KLINE_DIRNAME
    valuation_dir = data_dir / VALUATION_DIRNAME
    kline_dir.mkdir(parents=True, exist_ok=True)
    valuation_dir.mkdir(parents=True, exist_ok=True)
    return kline_dir, valuation_dir


def _is_blank(value: Any) -> bool:
    ensure_pandas_loaded()
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return isinstance(value, str) and not value.strip()


def _is_known_category_value(value: Any) -> bool:
    if _is_blank(value):
        return False
    return str(value).strip().upper() != "UNKNOWN"


def summarize_industry_coverage(stock_df: pd.DataFrame) -> dict[str, int]:
    ensure_pandas_loaded()
    total = int(len(stock_df))
    if total == 0 or "industry" not in stock_df.columns:
        return {"total": total, "known": 0, "missing": total}

    known_mask = stock_df["industry"].map(_is_known_category_value)
    known = int(known_mask.sum())
    return {
        "total": total,
        "known": known,
        "missing": total - known,
    }


def call_with_retry(func: Any, *args: Any, **kwargs: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, REQUEST_RETRY_TIMES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - network/API dependent
            last_error = exc
            if attempt == REQUEST_RETRY_TIMES:
                break
            print(f"请求失败，{REQUEST_RETRY_SLEEP:.1f} 秒后重试 ({attempt}/{REQUEST_RETRY_TIMES}): {exc}")
            time.sleep(REQUEST_RETRY_SLEEP)
    raise last_error if last_error else RuntimeError("unknown request error")


def query_baostock_with_retry(query_func: Any, *args: Any, **kwargs: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, REQUEST_RETRY_TIMES + 1):
        try:
            rs = query_func(*args, **kwargs)
            if getattr(rs, "error_code", "0") == "0":
                return rs
            if getattr(rs, "error_code", "") == "10001001":
                print("Baostock 会话已失效，正在自动重新登录...")
                baostock_logout()
                time.sleep(1.0)
                baostock_login()
                continue
            raise RuntimeError(f"{query_func.__name__}: {rs.error_code} {rs.error_msg}")
        except Exception as exc:  # pragma: no cover - network/API dependent
            last_error = exc
            if attempt == REQUEST_RETRY_TIMES:
                break
            print(f"请求失败，{REQUEST_RETRY_SLEEP:.1f} 秒后重试 ({attempt}/{REQUEST_RETRY_TIMES}): {exc}")
            time.sleep(REQUEST_RETRY_SLEEP)
    raise last_error if last_error else RuntimeError("unknown baostock query error")


def baostock_result_to_df(rs: Any) -> pd.DataFrame:
    rows: list[list[str]] = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


def baostock_login() -> None:
    login_result = call_with_retry(bs.login)
    if getattr(login_result, "error_code", None) != "0":  # pragma: no cover - network/API dependent
        raise SystemExit(f"Baostock 登录失败: {login_result.error_code} {login_result.error_msg}")


def baostock_logout() -> None:
    try:
        bs.logout()
    except Exception:
        pass


def format_bs_date(date_str: str) -> str:
    return pd.to_datetime(date_str, format="%Y%m%d").strftime("%Y-%m-%d")


def normalize_exchange(exchange: str | None) -> str | None:
    if exchange is None:
        return None
    normalized = str(exchange).strip().lower().replace(".", "")
    if normalized in {"sh", "sse"}:
        return "sh"
    if normalized in {"sz", "szse"}:
        return "sz"
    return None


def get_exchange_from_baostock_code(code: str) -> str | None:
    if "." not in code:
        return None
    return normalize_exchange(code.split(".", maxsplit=1)[0])


def to_baostock_code(code: str, exchange: str | None = None) -> str:
    normalized_exchange = normalize_exchange(exchange)
    if normalized_exchange is not None:
        return f"{normalized_exchange}.{from_baostock_code(str(code)).zfill(6)}"
    return f"sh.{code}" if str(code).startswith(("5", "6", "9")) else f"sz.{code}"


def from_baostock_code(code: str) -> str:
    if "." in code:
        return code.split(".", maxsplit=1)[1]
    return code


def is_a_share_code(code: str) -> bool:
    return code.startswith(
        (
            "sh.600",
            "sh.601",
            "sh.603",
            "sh.605",
            "sh.688",
            "sz.000",
            "sz.001",
            "sz.002",
            "sz.003",
            "sz.300",
            "sz.301",
            "sz.302",
        )
    )


def get_latest_trade_date(reference_date: str) -> str:
    end_ts = pd.to_datetime(reference_date, format="%Y%m%d")
    start_ts = end_ts - pd.Timedelta(days=30)
    rs = query_baostock_with_retry(
        bs.query_trade_dates,
        start_date=start_ts.strftime("%Y-%m-%d"),
        end_date=end_ts.strftime("%Y-%m-%d"),
    )
    df = baostock_result_to_df(rs)
    df = df[df["is_trading_day"] == "1"].copy()
    if df.empty:
        raise RuntimeError(f"未找到 {reference_date} 之前的最近交易日")
    return str(df.iloc[-1]["calendar_date"])


def get_recent_trade_dates(reference_date: str, *, lookback_days: int = 30) -> list[str]:
    end_ts = pd.to_datetime(reference_date, format="%Y%m%d")
    start_ts = end_ts - pd.Timedelta(days=lookback_days)
    rs = query_baostock_with_retry(
        bs.query_trade_dates,
        start_date=start_ts.strftime("%Y-%m-%d"),
        end_date=end_ts.strftime("%Y-%m-%d"),
    )
    df = baostock_result_to_df(rs)
    df = df[df["is_trading_day"] == "1"].copy()
    if df.empty:
        raise RuntimeError(f"未找到 {reference_date} 之前的交易日")
    return df["calendar_date"].astype(str).tolist()


def normalize_all_stock_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    normalized = df.copy()
    name_col = None
    for candidate in ["code_name", "codeName", "name"]:
        if candidate in normalized.columns:
            name_col = candidate
            break

    if name_col is not None and name_col != "code_name":
        normalized = normalized.rename(columns={name_col: "code_name"})
    if "code_name" not in normalized.columns:
        normalized["code_name"] = ""
    return normalized


def get_latest_all_stock_universe(reference_date: str) -> tuple[pd.DataFrame, str]:
    recent_trade_dates = get_recent_trade_dates(reference_date)

    for trade_date in reversed(recent_trade_dates):
        print(f"正在通过 Baostock 获取全市场 A 股名单，交易日: {trade_date}...")
        rs = query_baostock_with_retry(bs.query_all_stock, trade_date)
        df = normalize_all_stock_df(baostock_result_to_df(rs))
        if df.empty:
            print(f"{trade_date} 返回空股票列表，回退到更早交易日继续尝试。")
            continue

        df = df[df["code"].map(is_a_share_code)].copy()
        df = df[df["code_name"].map(is_investable_stock_name)].copy()
        if df.empty:
            print(f"{trade_date} 过滤后无有效 A 股列表，回退到更早交易日继续尝试。")
            continue

        df["exchange"] = df["code"].map(get_exchange_from_baostock_code)
        df["code"] = df["code"].map(from_baostock_code)
        df = df.rename(columns={"code_name": "name"})
        df["trade_date"] = pd.to_datetime(trade_date)
        df = df[["code", "exchange", "name", "trade_date"]].drop_duplicates(subset=["code"]).reset_index(drop=True)
        return df, trade_date

    raise RuntimeError(f"未能在 {reference_date} 之前的最近交易日中获取非空全市场股票列表")


def get_selected_universe(universe: str, reference_date: str) -> tuple[pd.DataFrame, str]:
    if universe == "hs300":
        print("正在通过 Baostock 获取沪深300成分股名单...")
        rs = query_baostock_with_retry(bs.query_hs300_stocks)
        df = baostock_result_to_df(rs)
        df["exchange"] = df["code"].map(get_exchange_from_baostock_code)
        df["code"] = df["code"].map(from_baostock_code)
        df = df.rename(columns={"code_name": "name", "updateDate": "update_date"})
        df["update_date"] = pd.to_datetime(df["update_date"], errors="coerce")
        df = df[["code", "exchange", "name", "update_date"]].drop_duplicates(subset=["code"]).reset_index(drop=True)
        return df, df["update_date"].dropna().max().strftime("%Y-%m-%d")

    return get_latest_all_stock_universe(reference_date)


def get_stock_industry(code: str, exchange: str | None, trade_date: str) -> dict[str, Any]:
    rs = query_baostock_with_retry(
        bs.query_stock_industry,
        code=to_baostock_code(code, exchange),
        date=trade_date,
    )
    df = baostock_result_to_df(rs)
    if df.empty:
        return {"industry": None, "industry_classification": None}
    row = df.iloc[-1]
    return {
        "industry": row.get("industry"),
        "industry_classification": row.get("industryClassification"),
    }


def normalize_stock_metadata_df(stock_df: pd.DataFrame) -> pd.DataFrame:
    ensure_pandas_loaded()
    normalized = stock_df.copy()
    if "code" in normalized.columns:
        normalized["code"] = normalized["code"].astype(str).str.zfill(6)
    if "exchange" in normalized.columns:
        normalized["exchange"] = normalized["exchange"].map(normalize_exchange)
    for col in ["update_date", "trade_date", "first_seen_date", "last_seen_date", "inactive_date"]:
        if col in normalized.columns:
            normalized[col] = pd.to_datetime(normalized[col], errors="coerce")
    if "is_active" in normalized.columns:
        normalized["is_active"] = normalized["is_active"].fillna(False).astype(bool)
    return normalized


def load_existing_stock_list(data_dir: Path) -> Any:
    candidate_paths = [
        data_dir / STOCK_REGISTRY_FILENAME,
        data_dir / STOCK_LIST_FILENAME,
    ]
    for path in candidate_paths:
        if not path.exists():
            continue
        stock_df = pd.read_parquet(path)
        if "code" not in stock_df.columns:
            continue
        return normalize_stock_metadata_df(stock_df)
    return None


def build_stock_list(
    universe_df: pd.DataFrame,
    *,
    universe_name: str,
    include_industry: bool,
    sleep_seconds: float,
    trade_date: str,
    existing_stock_df: Any = None,
) -> pd.DataFrame:
    stock_df = universe_df.copy()
    stock_df["code"] = stock_df["code"].astype(str).str.zfill(6)
    stock_df["exchange"] = stock_df["exchange"].map(normalize_exchange)
    stock_df["universe"] = universe_name

    if existing_stock_df is not None and not existing_stock_df.empty:
        existing_columns = [
            col
            for col in ["code", "exchange", "industry", "industry_classification"]
            if col in existing_stock_df.columns
        ]
        if {"code", "exchange"} <= set(existing_columns):
            existing_meta = (
                existing_stock_df[existing_columns]
                .drop_duplicates(subset=["code", "exchange"], keep="last")
                .copy()
            )
            stock_df = stock_df.merge(existing_meta, on=["code", "exchange"], how="left")

    coverage_before = summarize_industry_coverage(stock_df)
    if include_industry:
        if "industry" not in stock_df.columns:
            stock_df["industry"] = None
        if "industry_classification" not in stock_df.columns:
            stock_df["industry_classification"] = None

        print(
            "行业补全已启用："
            f"当前已知行业 {coverage_before['known']}/{coverage_before['total']}，"
            f"待补 {coverage_before['missing']}。"
        )
        missing_mask = ~stock_df["industry"].map(_is_known_category_value)
        missing_indices = stock_df.index[missing_mask].tolist()
        total_missing = len(missing_indices)
        for idx, row_index in enumerate(missing_indices, start=1):
            code = str(stock_df.at[row_index, "code"]).zfill(6)
            exchange = stock_df.at[row_index, "exchange"]
            print(f"[stock_list {idx}/{total_missing}] 正在通过 Baostock 补充行业信息: {code}")
            try:
                industry_row = get_stock_industry(code, exchange, trade_date)
            except Exception as exc:  # pragma: no cover - network/API dependent
                print(f"补充 {code} 行业信息失败: {exc}")
                industry_row = {"industry": None, "industry_classification": None}

            stock_df.at[row_index, "industry"] = industry_row.get("industry")
            stock_df.at[row_index, "industry_classification"] = industry_row.get("industry_classification")
            time.sleep(sleep_seconds)
        coverage_after = summarize_industry_coverage(stock_df)
        print(
            "行业补全完成："
            f"已知行业 {coverage_after['known']}/{coverage_after['total']}，"
            f"仍缺失 {coverage_after['missing']}。"
        )
    else:
        print(
            "行业补全已跳过："
            f"当前已知行业 {coverage_before['known']}/{coverage_before['total']}，"
            f"缺失 {coverage_before['missing']}。"
            "如需恢复 industry 特征，请启用 --include-industry。"
        )

    preferred_order = [
        "code",
        "exchange",
        "name",
        "industry",
        "industry_classification",
        "update_date",
        "trade_date",
        "universe",
    ]
    ordered_columns = [col for col in preferred_order if col in stock_df.columns]
    remaining_columns = [col for col in stock_df.columns if col not in ordered_columns]
    return stock_df[ordered_columns + remaining_columns].drop_duplicates(subset=["code"]).sort_values("code").reset_index(drop=True)


def _coalesce_date(*values: Any) -> pd.Timestamp | pd.NaT:
    ensure_pandas_loaded()
    for value in values:
        if _is_blank(value):
            continue
        parsed = pd.to_datetime(value, errors="coerce")
        if not pd.isna(parsed):
            return parsed
    return pd.NaT


def sync_stock_registry(
    latest_stock_df: pd.DataFrame,
    *,
    existing_stock_df: pd.DataFrame | None,
    trade_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    ensure_pandas_loaded()
    sync_date = pd.to_datetime(trade_date, errors="coerce")
    if pd.isna(sync_date):
        sync_date = pd.Timestamp.utcnow().normalize()

    latest_df = normalize_stock_metadata_df(latest_stock_df).drop_duplicates(subset=["code", "exchange"], keep="last")
    existing_df = (
        normalize_stock_metadata_df(existing_stock_df).drop_duplicates(subset=["code", "exchange"], keep="last")
        if existing_stock_df is not None and not existing_stock_df.empty
        else pd.DataFrame(columns=["code", "exchange"])
    )

    latest_by_key = {
        (str(row["code"]).zfill(6), normalize_exchange(row.get("exchange"))): row
        for row in latest_df.to_dict(orient="records")
    }
    existing_by_key = {
        (str(row["code"]).zfill(6), normalize_exchange(row.get("exchange"))): row
        for row in existing_df.to_dict(orient="records")
    }

    rows: list[dict[str, Any]] = []
    new_count = 0
    reactivated_count = 0
    deactivated_count = 0

    for key in sorted(set(existing_by_key) | set(latest_by_key)):
        latest_row = latest_by_key.get(key)
        existing_row = existing_by_key.get(key)

        if latest_row is not None:
            row = dict(existing_row or {})
            for field, value in latest_row.items():
                if not _is_blank(value):
                    row[field] = value
            row["code"], row["exchange"] = key

            if existing_row is None:
                new_count += 1
            elif not bool(existing_row.get("is_active", True)):
                reactivated_count += 1

            row["first_seen_date"] = _coalesce_date(
                row.get("first_seen_date"),
                existing_row.get("first_seen_date") if existing_row else None,
                latest_row.get("trade_date"),
                latest_row.get("update_date"),
                sync_date,
            )
            row["last_seen_date"] = sync_date
            row["is_active"] = True
            row["inactive_date"] = pd.NaT
        else:
            row = dict(existing_row or {})
            row["code"], row["exchange"] = key
            was_active = bool(row.get("is_active", True))
            if was_active:
                deactivated_count += 1
            row["first_seen_date"] = _coalesce_date(
                row.get("first_seen_date"),
                row.get("trade_date"),
                row.get("update_date"),
                sync_date,
            )
            row["last_seen_date"] = _coalesce_date(
                row.get("last_seen_date"),
                row.get("trade_date"),
                row.get("update_date"),
                sync_date,
            )
            row["is_active"] = False
            row["inactive_date"] = _coalesce_date(
                row.get("inactive_date"),
                None if was_active else row.get("last_seen_date"),
                sync_date,
            )

        rows.append(row)

    registry_df = pd.DataFrame(rows)
    if registry_df.empty:
        registry_df = latest_df.copy()
        registry_df["first_seen_date"] = sync_date
        registry_df["last_seen_date"] = sync_date
        registry_df["is_active"] = True
        registry_df["inactive_date"] = pd.NaT

    registry_df = normalize_stock_metadata_df(registry_df)
    preferred_order = [
        "code",
        "exchange",
        "name",
        "industry",
        "industry_classification",
        "update_date",
        "trade_date",
        "universe",
        "is_active",
        "first_seen_date",
        "last_seen_date",
        "inactive_date",
    ]
    ordered_columns = [col for col in preferred_order if col in registry_df.columns]
    remaining_columns = [col for col in registry_df.columns if col not in ordered_columns]
    registry_df = (
        registry_df[ordered_columns + remaining_columns]
        .drop_duplicates(subset=["code", "exchange"], keep="last")
        .sort_values(["is_active", "code", "exchange"], ascending=[False, True, True])
        .reset_index(drop=True)
    )

    active_df = registry_df[registry_df["is_active"]].copy().reset_index(drop=True)
    return registry_df, active_df, {
        "new_count": int(new_count),
        "reactivated_count": int(reactivated_count),
        "deactivated_count": int(deactivated_count),
        "active_count": int(len(active_df)),
        "registry_count": int(len(registry_df)),
    }


def should_update_canonical_stock_lists(*, universe: str, limit: int) -> bool:
    return universe == "all" and limit <= 0


def write_canonical_stock_lists(
    data_dir: Path,
    *,
    registry_df: pd.DataFrame,
    active_df: pd.DataFrame,
) -> tuple[Path, Path]:
    active_path = data_dir / STOCK_LIST_FILENAME
    registry_path = data_dir / STOCK_REGISTRY_FILENAME
    active_df.to_parquet(active_path, index=False)
    registry_df.to_parquet(registry_path, index=False)
    return active_path, registry_path


def convert_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def download_baostock_daily_bundle(
    code: str,
    *,
    exchange: str | None,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame | None, str | None]:
    try:
        rs = query_baostock_with_retry(
            bs.query_history_k_data_plus,
            to_baostock_code(code, exchange),
            BAOSTOCK_DAILY_FIELDS,
            start_date=format_bs_date(start_date),
            end_date=format_bs_date(end_date),
            frequency="d",
            adjustflag="2",
        )
        df = baostock_result_to_df(rs)
        if df.empty:
            return None, "empty"

        df["exchange"] = df["code"].map(get_exchange_from_baostock_code)
        df["code"] = df["code"].map(from_baostock_code)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = convert_numeric_columns(df, NUMERIC_BAOSTOCK_COLUMNS)
        df = df.sort_values("date").reset_index(drop=True)
        return df, None
    except Exception as exc:  # pragma: no cover - network/API dependent
        return None, str(exc)


def build_kline_df(bundle_df: pd.DataFrame, code: str) -> pd.DataFrame:
    df = bundle_df.copy()
    preclose = df["preclose"].replace(0, pd.NA)
    df["amplitude"] = ((df["high"] - df["low"]) / preclose) * 100
    df["change"] = df["close"] - df["preclose"]
    df["turnover"] = df["turn"]
    df["pct_chg"] = df["pctChg"]
    df["code"] = code

    ordered_columns = [
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
    ]
    return df[[col for col in ordered_columns if col in df.columns]].copy()


def fetch_market_cap_df(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    df = call_with_retry(ak.stock_value_em, symbol=code)
    if df.empty:
        return pd.DataFrame(columns=["date", "code", "total_market_cap", "float_market_cap", "total_shares", "float_shares"])

    df = df.rename(columns=AKSHARE_MARKET_CAP_COLUMNS)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    start_ts = pd.to_datetime(start_date, format="%Y%m%d")
    end_ts = pd.to_datetime(end_date, format="%Y%m%d")
    df = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)].copy()
    df = convert_numeric_columns(df, ["total_market_cap", "float_market_cap", "total_shares", "float_shares"])
    df["code"] = code

    ordered_columns = [
        "date",
        "code",
        "total_market_cap",
        "float_market_cap",
        "total_shares",
        "float_shares",
    ]
    return df[[col for col in ordered_columns if col in df.columns]].drop_duplicates(subset=["date", "code"])


def build_valuation_df(
    bundle_df: pd.DataFrame,
    code: str,
    *,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, str | None]:
    df = bundle_df.copy()
    df["code"] = code
    df["pct_chg"] = df["pctChg"]
    df = df.rename(
        columns={
            "peTTM": "pe_ttm",
            "pbMRQ": "pb",
            "psTTM": "ps",
            "pcfNcfTTM": "pcf",
        }
    )
    valuation_df = df[
        [col for col in ["date", "code", "exchange", "close", "pct_chg", "pe_ttm", "pb", "ps", "pcf"] if col in df.columns]
    ].copy()

    warning: str | None = None
    try:
        market_cap_df = fetch_market_cap_df(code, start_date, end_date)
    except Exception as exc:  # pragma: no cover - network/API dependent
        warning = f"market_cap_fallback_failed: {exc}"
        market_cap_df = pd.DataFrame(columns=["date", "code", "total_market_cap", "float_market_cap", "total_shares", "float_shares"])

    valuation_df = valuation_df.merge(market_cap_df, on=["date", "code"], how="left")
    for col in ["total_market_cap", "float_market_cap", "total_shares", "float_shares"]:
        if col not in valuation_df.columns:
            valuation_df[col] = pd.NA

    ordered_columns = [
        "date",
        "code",
        "exchange",
        "close",
        "pct_chg",
        "total_market_cap",
        "float_market_cap",
        "total_shares",
        "float_shares",
        "pe_ttm",
        "pb",
        "ps",
        "pcf",
    ]
    valuation_df = valuation_df[[col for col in ordered_columns if col in valuation_df.columns]].copy()
    return valuation_df, warning


def write_failures(data_dir: Path, failures: list[dict[str, str]]) -> None:
    if not failures:
        return
    failures_df = pd.DataFrame(failures)
    failures_df.to_csv(data_dir / FAILURES_FILENAME, index=False, encoding="utf-8-sig")


def main() -> int:
    args = parse_args()
    load_dependencies()
    data_dir = Path(args.data_dir)
    kline_dir, valuation_dir = ensure_dirs(data_dir)

    baostock_login()
    try:
        universe_df, trade_date = get_selected_universe(args.universe, args.end_date)
        if args.limit and args.limit > 0:
            universe_df = universe_df.head(args.limit).copy()

        existing_stock_df = load_existing_stock_list(data_dir)
        stock_df = build_stock_list(
            universe_df,
            universe_name=args.universe,
            include_industry=not args.skip_industry,
            sleep_seconds=args.sleep,
            trade_date=trade_date,
            existing_stock_df=existing_stock_df,
        )

        if not args.skip_stock_list:
            if should_update_canonical_stock_lists(universe=args.universe, limit=args.limit):
                registry_df, active_df, sync_summary = sync_stock_registry(
                    stock_df,
                    existing_stock_df=existing_stock_df,
                    trade_date=trade_date,
                )
                active_path, registry_path = write_canonical_stock_lists(
                    data_dir,
                    registry_df=registry_df,
                    active_df=active_df,
                )
                stock_df = active_df
                print(f"活跃股票池已保存至 {active_path}，共 {len(active_df)} 只股票。")
                print(f"主注册表已保存至 {registry_path}，共 {len(registry_df)} 只股票。")
                print(
                    "股票池同步结果: "
                    f"新增 {sync_summary['new_count']}，"
                    f"恢复 {sync_summary['reactivated_count']}，"
                    f"停用 {sync_summary['deactivated_count']}"
                )
            else:
                subset_path = data_dir / STOCK_LIST_SUBSET_FILENAME
                stock_df.to_parquet(subset_path, index=False)
                print(f"子集股票列表已保存至 {subset_path}，共 {len(stock_df)} 只股票。")
                print(f"当前任务为子集/测试模式，未覆盖 {data_dir / STOCK_LIST_FILENAME} 和 {data_dir / STOCK_REGISTRY_FILENAME}。")

        stock_records = stock_df[["code", "exchange"]].to_dict("records")
        print(f"本次任务股票数量: {len(stock_records)}，股票池: {args.universe}")

        failures: list[dict[str, str]] = []
        kline_success_count = 0
        valuation_success_count = 0

        if not args.skip_kline:
            print("开始下载前复权日 K 线数据...")
        if not args.skip_valuation:
            print("开始下载每日估值数据...")

        for idx, stock in enumerate(stock_records, start=1):
            code = str(stock["code"]).zfill(6)
            exchange = normalize_exchange(stock.get("exchange"))
            kline_path = kline_dir / f"{code}.parquet"
            valuation_path = valuation_dir / f"{code}.parquet"

            need_kline = not args.skip_kline and (args.overwrite or not kline_path.exists())
            need_valuation = not args.skip_valuation and (args.overwrite or not valuation_path.exists())

            if not need_kline and not need_valuation:
                if not args.skip_kline:
                    kline_success_count += 1
                if not args.skip_valuation:
                    valuation_success_count += 1
                continue

                print(f"[{idx}/{len(stock_records)}] 正在通过 Baostock 下载: {code}")
            bundle_df, reason = download_baostock_daily_bundle(
                code,
                exchange=exchange,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            if bundle_df is None:
                if need_kline:
                    failures.append({"dataset": "kline", "code": code, "exchange": exchange or "", "reason": reason or "unknown"})
                if need_valuation:
                    failures.append({"dataset": "valuation", "code": code, "exchange": exchange or "", "reason": reason or "unknown"})
                print(f"下载 {code} 失败: {reason}")
                time.sleep(args.sleep)
                continue

            if not args.skip_kline:
                try:
                    if need_kline:
                        kline_df = build_kline_df(bundle_df, code)
                        kline_df.to_parquet(kline_path, index=False)
                    kline_success_count += 1
                except Exception as exc:  # pragma: no cover - file/data dependent
                    failures.append({"dataset": "kline", "code": code, "exchange": exchange or "", "reason": str(exc)})
                    print(f"写入 {code} 日 K 线失败: {exc}")

            if not args.skip_valuation:
                try:
                    if need_valuation:
                        valuation_df, warning = build_valuation_df(
                            bundle_df,
                            code,
                            start_date=args.start_date,
                            end_date=args.end_date,
                        )
                        valuation_df.to_parquet(valuation_path, index=False)
                        if warning:
                            failures.append(
                                {"dataset": "valuation_warning", "code": code, "exchange": exchange or "", "reason": warning}
                            )
                            print(f"{code} 估值补充提醒: {warning}")
                    valuation_success_count += 1
                except Exception as exc:  # pragma: no cover - file/data dependent
                    failures.append({"dataset": "valuation", "code": code, "exchange": exchange or "", "reason": str(exc)})
                    print(f"写入 {code} 估值数据失败: {exc}")

            time.sleep(args.sleep)

        if not args.skip_kline:
            print(f"前复权日 K 线下载完成，成功 {kline_success_count}/{len(stock_records)}。")
        if not args.skip_valuation:
            print(f"每日估值数据下载完成，成功 {valuation_success_count}/{len(stock_records)}。")

        write_failures(data_dir, failures)
        if failures:
            print(f"失败明细已写入 {data_dir / FAILURES_FILENAME}")

        print("全部任务完成。")
        return 0
    finally:
        baostock_logout()


if __name__ == "__main__":
    raise SystemExit(main())
