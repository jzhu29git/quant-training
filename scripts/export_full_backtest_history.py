"""Export full backtest equity curves and rebalance histories.

This script converts the parquet artifacts created by the walk-forward
backtests into trader-friendly CSV and Excel files.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "quant_data" / "comparison_reports" / "full_backtest_history"


@dataclass(frozen=True)
class BacktestSpec:
    index_key: str
    index_name: str
    run_dir: Path
    group: str
    top_k: int

    @property
    def label(self) -> str:
        return f"{self.index_key}_{self.group}_top{self.top_k}"

    @property
    def source_dir(self) -> Path:
        return self.run_dir / "topk_tests" / self.group / f"topk_{self.top_k}"


INDEX_CONFIG = {
    "csi500": {
        "index_name": "中证500",
        "run_dir": ROOT / "quant_data" / "csi500_2y_run",
        "group": "momentum_liquidity",
    },
    "csi2000": {
        "index_name": "中证2000",
        "run_dir": ROOT / "quant_data" / "csi2000_2y_run",
        "group": "momentum_liquidity",
    },
    "sse50": {
        "index_name": "上证50",
        "run_dir": ROOT / "quant_data" / "sse50_2y_run",
        "group": "valuation_momentum",
    },
}


def pct(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value) * 100:.2f}%"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_specs(indices: Iterable[str], top_ks: Iterable[int]) -> list[BacktestSpec]:
    specs: list[BacktestSpec] = []
    for index_key in indices:
        cfg = INDEX_CONFIG[index_key]
        for top_k in top_ks:
            specs.append(
                BacktestSpec(
                    index_key=index_key,
                    index_name=str(cfg["index_name"]),
                    run_dir=Path(cfg["run_dir"]),
                    group=str(cfg["group"]),
                    top_k=int(top_k),
                )
            )
    return specs


def load_equity(spec: BacktestSpec) -> pd.DataFrame:
    path = spec.source_dir / "equity_curve.parquet"
    equity = pd.read_parquet(path).copy()
    equity["rebalance_date"] = pd.to_datetime(equity["rebalance_date"]).dt.date
    equity["period_start_equity"] = equity["equity"] / (1.0 + equity["portfolio_return"])
    equity["period_end_equity"] = equity["equity"]
    equity.insert(0, "index", spec.index_name)
    equity.insert(1, "index_key", spec.index_key)
    equity.insert(2, "feature_group", spec.group)
    equity.insert(3, "top_k", spec.top_k)
    equity["period_return_pct"] = equity["portfolio_return"].map(pct)
    equity["total_return_to_date"] = equity["equity"] - 1.0
    equity["total_return_to_date_pct"] = equity["total_return_to_date"].map(pct)
    return equity


def load_holdings(spec: BacktestSpec) -> pd.DataFrame:
    path = spec.source_dir / "trade_log.parquet"
    holdings = pd.read_parquet(path).copy()
    holdings["rebalance_date"] = pd.to_datetime(holdings["rebalance_date"]).dt.date
    holdings["code"] = holdings["code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    holdings = holdings.sort_values(["rebalance_date", "score"], ascending=[True, False]).reset_index(drop=True)
    holdings.insert(0, "index", spec.index_name)
    holdings.insert(1, "index_key", spec.index_key)
    holdings.insert(2, "feature_group", spec.group)
    holdings.insert(3, "top_k", spec.top_k)
    holdings["rank_in_period"] = holdings.groupby(["rebalance_date"]).cumcount() + 1
    holdings["target_weight"] = 1.0 / spec.top_k
    holdings["future_return_pct"] = holdings["future_return"].map(pct)
    return holdings


def derive_actions(holdings: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    previous: dict[str, dict] = {}

    for rebalance_date, day in holdings.groupby("rebalance_date", sort=True):
        current = {str(row.code): row._asdict() for row in day.itertuples(index=False)}
        previous_codes = set(previous)
        current_codes = set(current)

        for code in sorted(current_codes - previous_codes):
            row = current[code]
            rows.append(action_row(row, "BUY", rebalance_date))

        for code in sorted(current_codes & previous_codes):
            row = current[code]
            rows.append(action_row(row, "HOLD", rebalance_date))

        for code in sorted(previous_codes - current_codes):
            row = previous[code]
            rows.append(
                {
                    "index": row["index"],
                    "index_key": row["index_key"],
                    "feature_group": row["feature_group"],
                    "top_k": row["top_k"],
                    "rebalance_date": rebalance_date,
                    "action": "SELL",
                    "code": code,
                    "name": row.get("name"),
                    "industry": row.get("industry"),
                    "score": row.get("score"),
                    "rank_in_period": row.get("rank_in_period"),
                    "target_weight": 0.0,
                    "future_return": row.get("future_return"),
                    "future_return_pct": pct(row.get("future_return")),
                    "label": row.get("label"),
                }
            )

        previous = current

    return pd.DataFrame(rows).sort_values(["rebalance_date", "action", "rank_in_period", "code"]).reset_index(drop=True)


def action_row(row: dict, action: str, rebalance_date) -> dict:
    return {
        "index": row["index"],
        "index_key": row["index_key"],
        "feature_group": row["feature_group"],
        "top_k": row["top_k"],
        "rebalance_date": rebalance_date,
        "action": action,
        "code": row["code"],
        "name": row.get("name"),
        "industry": row.get("industry"),
        "score": row.get("score"),
        "rank_in_period": row.get("rank_in_period"),
        "target_weight": row.get("target_weight"),
        "future_return": row.get("future_return"),
        "future_return_pct": row.get("future_return_pct"),
        "label": row.get("label"),
    }


def load_summary(spec: BacktestSpec, equity: pd.DataFrame, holdings: pd.DataFrame, actions: pd.DataFrame) -> dict:
    summary = read_json(spec.source_dir / "summary.json")
    return {
        "index": spec.index_name,
        "index_key": spec.index_key,
        "feature_group": spec.group,
        "top_k": spec.top_k,
        "first_rebalance_date": str(equity["rebalance_date"].min()),
        "last_rebalance_date": str(equity["rebalance_date"].max()),
        "rebalance_periods": int(len(equity)),
        "holding_rows": int(len(holdings)),
        "buy_count": int((actions["action"] == "BUY").sum()),
        "sell_count": int((actions["action"] == "SELL").sum()),
        "hold_count": int((actions["action"] == "HOLD").sum()),
        "portfolio_total_return": summary.get("portfolio_total_return"),
        "portfolio_total_return_pct": pct(summary.get("portfolio_total_return")),
        "portfolio_cagr": summary.get("portfolio_cagr"),
        "portfolio_cagr_pct": pct(summary.get("portfolio_cagr")),
        "portfolio_max_drawdown": summary.get("portfolio_max_drawdown"),
        "portfolio_max_drawdown_pct": pct(summary.get("portfolio_max_drawdown")),
        "portfolio_win_rate": summary.get("portfolio_win_rate"),
        "portfolio_win_rate_pct": pct(summary.get("portfolio_win_rate")),
        "portfolio_avg_return": summary.get("portfolio_avg_return"),
        "portfolio_avg_return_pct": pct(summary.get("portfolio_avg_return")),
        "source_dir": str(spec.source_dir.relative_to(ROOT)),
    }


def write_outputs(specs: list[BacktestSpec], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    topk_suffix = "top" + "_top".join(str(top_k) for top_k in sorted({spec.top_k for spec in specs}))
    summary_rows: list[dict] = []
    all_equity: list[pd.DataFrame] = []
    all_holdings: list[pd.DataFrame] = []
    all_actions: list[pd.DataFrame] = []

    for spec in specs:
        missing = [name for name in ["summary.json", "equity_curve.parquet", "trade_log.parquet"] if not (spec.source_dir / name).exists()]
        if missing:
            raise FileNotFoundError(f"{spec.source_dir} missing {missing}")

        equity = load_equity(spec)
        holdings = load_holdings(spec)
        actions = derive_actions(holdings)
        summary_rows.append(load_summary(spec, equity, holdings, actions))

        all_equity.append(equity)
        all_holdings.append(holdings)
        all_actions.append(actions)

        file_prefix = output_dir / spec.label
        equity.to_csv(file_prefix.with_name(f"{spec.label}_equity_curve.csv"), index=False, encoding="utf-8-sig")
        holdings.to_csv(file_prefix.with_name(f"{spec.label}_holdings_by_rebalance.csv"), index=False, encoding="utf-8-sig")
        actions.to_csv(file_prefix.with_name(f"{spec.label}_rebalance_actions.csv"), index=False, encoding="utf-8-sig")

    summary_df = pd.DataFrame(summary_rows).sort_values(["index_key", "top_k"])
    equity_df = pd.concat(all_equity, ignore_index=True)
    holdings_df = pd.concat(all_holdings, ignore_index=True)
    actions_df = pd.concat(all_actions, ignore_index=True)

    summary_df.to_csv(output_dir / "summary_all.csv", index=False, encoding="utf-8-sig")
    equity_df.to_csv(output_dir / "equity_curve_all.csv", index=False, encoding="utf-8-sig")
    holdings_df.to_csv(output_dir / "holdings_by_rebalance_all.csv", index=False, encoding="utf-8-sig")
    actions_df.to_csv(output_dir / "rebalance_actions_all.csv", index=False, encoding="utf-8-sig")

    xlsx_path = output_dir / f"full_backtest_history_{topk_suffix}.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        equity_df.to_excel(writer, sheet_name="equity_curve", index=False)
        holdings_df.to_excel(writer, sheet_name="holdings_by_rebalance", index=False)
        actions_df.to_excel(writer, sheet_name="rebalance_actions", index=False)

    write_equity_charts(equity_df, output_dir, topk_suffix)

    print(f"wrote {xlsx_path}")
    print(f"wrote CSV files under {output_dir}")


def write_equity_charts(equity_df: pd.DataFrame, output_dir: Path, topk_suffix: str) -> None:
    for index_key, index_df in equity_df.groupby("index_key"):
        fig, ax = plt.subplots(figsize=(11, 6))
        for top_k, series in index_df.groupby("top_k"):
            series = series.sort_values("rebalance_date")
            ax.plot(pd.to_datetime(series["rebalance_date"]), series["period_end_equity"], marker="o", linewidth=1.6, markersize=3, label=f"Top{top_k}")
        index_name = str(index_df["index"].iloc[0])
        group = str(index_df["feature_group"].iloc[0])
        ax.set_title(f"{index_key} {group} equity curve")
        ax.set_xlabel("rebalance date")
        ax.set_ylabel("equity, initial capital = 1.0")
        ax.grid(True, alpha=0.25)
        ax.legend()
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(output_dir / f"{index_key}_{group}_{topk_suffix}_equity_curve.png", dpi=160)
        plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indices", nargs="+", choices=sorted(INDEX_CONFIG), default=["sse50", "csi500", "csi2000"])
    parser.add_argument("--top-ks", nargs="+", type=int, default=[3, 5, 10])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    specs = load_specs(args.indices, args.top_ks)
    write_outputs(specs, args.output_dir.resolve())


if __name__ == "__main__":
    main()
