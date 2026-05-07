#!/usr/bin/env python3
"""Generate a self-contained HTML report from quant-trading-cn backtest outputs.

The report consumes the standard artifacts produced by backtest_walk_forward.py:
summary.json, equity_curve.parquet, and trade_log.parquet.
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported table format: {path}")


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return ""


def _fmt_num(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return ""


def _fmt_signed_pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:+.{digits}f}%"
    except (TypeError, ValueError):
        return ""


def _as_date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce")


def _equity_date_col(equity: pd.DataFrame) -> str:
    for col in ["rebalance_date", "date", "trade_date"]:
        if col in equity.columns:
            return col
    raise ValueError("equity curve must contain rebalance_date, date, or trade_date")


def _trade_date_col(trades: pd.DataFrame) -> str | None:
    for col in ["rebalance_date", "date", "trade_date"]:
        if col in trades.columns:
            return col
    return None


def _calc_drawdown(equity: pd.Series) -> pd.Series:
    running_max = equity.cummax()
    return equity / running_max - 1.0


def _find_drawdown_periods(dates: pd.Series, equity: pd.Series, top_n: int = 5) -> list[dict[str, Any]]:
    drawdown = _calc_drawdown(equity).reset_index(drop=True)
    dates = pd.to_datetime(dates).reset_index(drop=True)
    periods: list[dict[str, Any]] = []
    in_drawdown = False
    start_idx = 0
    trough_idx = 0

    for idx, value in enumerate(drawdown):
        if value < -0.0001 and not in_drawdown:
            in_drawdown = True
            start_idx = max(idx - 1, 0)
            trough_idx = idx
        elif value < -0.0001 and in_drawdown and value < drawdown.iloc[trough_idx]:
            trough_idx = idx
        elif value >= -0.0001 and in_drawdown:
            periods.append(
                {
                    "start": dates.iloc[start_idx],
                    "trough": dates.iloc[trough_idx],
                    "end": dates.iloc[idx],
                    "depth": float(drawdown.iloc[trough_idx]),
                    "duration": int(idx - start_idx),
                }
            )
            in_drawdown = False

    if in_drawdown:
        periods.append(
            {
                "start": dates.iloc[start_idx],
                "trough": dates.iloc[trough_idx],
                "end": dates.iloc[-1],
                "depth": float(drawdown.iloc[trough_idx]),
                "duration": int(len(dates) - start_idx),
            }
        )
    return sorted(periods, key=lambda row: row["depth"])[:top_n]


def _monthly_returns(dates: pd.Series, returns: pd.Series) -> tuple[list[str], list[str], list[list[float | None]], list[list[str]]]:
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "return": pd.to_numeric(returns, errors="coerce").fillna(0.0)})
    frame = frame.dropna(subset=["date"])
    if frame.empty:
        return [], [], [], []
    frame["year"] = frame["date"].dt.year
    frame["month"] = frame["date"].dt.month
    monthly = frame.groupby(["year", "month"])["return"].apply(lambda x: (1.0 + x).prod() - 1.0)
    years = sorted(frame["year"].dropna().astype(int).unique().tolist())
    months = list(range(1, 13))
    z: list[list[float | None]] = []
    text: list[list[str]] = []
    for year in years:
        row: list[float | None] = []
        text_row: list[str] = []
        for month in months:
            value = monthly.get((year, month))
            if value is None or pd.isna(value):
                row.append(None)
                text_row.append("")
            else:
                row.append(float(value * 100.0))
                text_row.append(f"{value * 100:+.2f}%")
        z.append(row)
        text.append(text_row)
    return [str(y) for y in years], [f"{m}月" for m in months], z, text


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)


def _metric_cards(summary: dict[str, Any]) -> list[tuple[str, str, str]]:
    metrics = summary.get("oos_metrics") or {}
    return [
        ("总收益", _fmt_signed_pct(summary.get("portfolio_total_return")), "posneg"),
        ("年化收益", _fmt_signed_pct(summary.get("portfolio_cagr")), "posneg"),
        ("最大回撤", _fmt_pct(summary.get("portfolio_max_drawdown")), "negative"),
        ("胜率", _fmt_pct(summary.get("portfolio_win_rate")), ""),
        ("调仓次数", str(summary.get("num_rebalances", "")), ""),
        ("Top K", str(summary.get("top_k", "")), ""),
        ("OOS AUC", _fmt_num(metrics.get("auc")), ""),
        ("OOS Accuracy", _fmt_pct(metrics.get("accuracy")), ""),
    ]


def _build_cards_html(summary: dict[str, Any]) -> str:
    parts: list[str] = []
    for label, value, kind in _metric_cards(summary):
        cls = ""
        if kind == "negative":
            cls = " negative"
        elif kind == "posneg":
            cls = " positive" if not value.startswith("-") else " negative"
        parts.append(
            f"""<div class="card">
  <div class="card-label">{html.escape(label)}</div>
  <div class="card-value{cls}">{html.escape(value)}</div>
</div>"""
        )
    return "\n".join(parts)


def _build_trade_rows(trades: pd.DataFrame, max_rows: int = 300) -> str:
    if trades.empty:
        return '<tr><td colspan="8">No trade rows</td></tr>'

    df = trades.copy()
    date_col = _trade_date_col(df)
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.sort_values([date_col, "score"] if "score" in df.columns else [date_col], ascending=[False, False] if "score" in df.columns else [False])
    keep = [col for col in ["rebalance_date", "date", "code", "name", "industry", "score", "future_return", "label"] if col in df.columns]
    df = df.loc[:, keep].head(max_rows)
    headers = {
        "rebalance_date": "日期",
        "date": "日期",
        "code": "代码",
        "name": "名称",
        "industry": "行业",
        "score": "模型分",
        "future_return": "未来收益",
        "label": "标签",
    }
    rows = []
    for rec in df.to_dict("records"):
        cells = []
        for col in keep:
            value = rec.get(col, "")
            if col in {"rebalance_date", "date"} and pd.notna(value):
                value = pd.to_datetime(value).date().isoformat()
            elif col == "future_return":
                value = _fmt_signed_pct(value)
            elif col == "score":
                value = _fmt_num(value, 4)
            else:
                value = "" if pd.isna(value) else str(value)
            cells.append(f'<td data-label="{html.escape(headers[col])}">{html.escape(value)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(rows)


def _build_trade_header(trades: pd.DataFrame) -> str:
    keep = [col for col in ["rebalance_date", "date", "code", "name", "industry", "score", "future_return", "label"] if col in trades.columns]
    headers = {
        "rebalance_date": "日期",
        "date": "日期",
        "code": "代码",
        "name": "名称",
        "industry": "行业",
        "score": "模型分",
        "future_return": "未来收益",
        "label": "标签",
    }
    return "<tr>" + "".join(f"<th>{html.escape(headers[col])}</th>" for col in keep) + "</tr>"


def _build_drawdown_rows(periods: list[dict[str, Any]]) -> str:
    if not periods:
        return '<tr><td colspan="5">No drawdown periods</td></tr>'
    rows = []
    for idx, row in enumerate(periods, start=1):
        rows.append(
            "<tr>"
            f'<td data-label="#">{idx}</td>'
            f'<td data-label="开始">{pd.to_datetime(row["start"]).date()}</td>'
            f'<td data-label="谷底">{pd.to_datetime(row["trough"]).date()}</td>'
            f'<td data-label="结束">{pd.to_datetime(row["end"]).date()}</td>'
            f'<td data-label="回撤" class="negative-text">{_fmt_pct(row["depth"])}</td>'
            f'<td data-label="持续">{row["duration"]}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def _build_summary_rows(summary: dict[str, Any]) -> str:
    pairs = [
        ("数据行数", summary.get("num_rows")),
        ("股票数", summary.get("num_codes")),
        ("交易日数", summary.get("num_trade_dates")),
        ("训练文件", summary.get("train_path")),
        ("回测开始", summary.get("backtest_start")),
        ("回测结束", summary.get("backtest_end")),
        ("最小训练天数", summary.get("min_train_days")),
        ("重训间隔", summary.get("retrain_every")),
        ("调仓间隔", summary.get("rebalance_every")),
        ("Profile", summary.get("profile_label") or summary.get("profile_name")),
    ]
    return "\n".join(
        f"<tr><td>{html.escape(str(label))}</td><td>{html.escape('' if value is None else str(value))}</td></tr>"
        for label, value in pairs
    )


def build_report_html(
    *,
    summary: dict[str, Any],
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    title: str,
    max_trade_rows: int = 300,
) -> str:
    date_col = _equity_date_col(equity)
    equity = equity.copy()
    equity[date_col] = _as_date_series(equity[date_col])
    equity = equity.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    if "equity" not in equity.columns:
        raise ValueError("equity curve must contain an equity column")
    if "portfolio_return" not in equity.columns:
        equity["portfolio_return"] = pd.to_numeric(equity["equity"], errors="coerce").pct_change().fillna(0.0)

    dates = equity[date_col]
    equity_values = pd.to_numeric(equity["equity"], errors="coerce").ffill().fillna(1.0)
    drawdown = _calc_drawdown(equity_values)
    dd_periods = _find_drawdown_periods(dates, equity_values)
    years, months, monthly_z, monthly_text = _monthly_returns(dates, equity["portfolio_return"])

    chart_payload = {
        "dates": [d.date().isoformat() for d in pd.to_datetime(dates)],
        "equity": [float(x) for x in equity_values],
        "drawdown": [float(x * 100.0) for x in drawdown],
        "monthlyYears": years,
        "monthlyMonths": months,
        "monthlyZ": monthly_z,
        "monthlyText": monthly_text,
    }

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards_html = _build_cards_html(summary)
    summary_rows = _build_summary_rows(summary)
    trade_header = _build_trade_header(trades)
    trade_rows = _build_trade_rows(trades, max_rows=max_trade_rows)
    drawdown_rows = _build_drawdown_rows(dd_periods)
    escaped_title = html.escape(title)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped_title}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root {{
  --bg: #f4f6f8;
  --panel: #ffffff;
  --ink: #263238;
  --muted: #667085;
  --brand: #286f8f;
  --brand-dark: #17465d;
  --green: #1f9d63;
  --red: #d04437;
  --line: #e5e7eb;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
  background: var(--bg);
  color: var(--ink);
}}
.container {{ max-width: 1180px; margin: 0 auto; padding: 22px; }}
.header {{
  background: linear-gradient(135deg, var(--brand), var(--brand-dark));
  color: #fff;
  border-radius: 10px;
  padding: 24px 28px;
  margin-bottom: 18px;
}}
.header h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
.header p {{ margin: 0; color: rgba(255,255,255,0.82); font-size: 13px; }}
.cards {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}}
.card, .panel {{
  background: var(--panel);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
}}
.card {{ padding: 15px; }}
.card-label {{ color: var(--muted); font-size: 12px; margin-bottom: 5px; }}
.card-value {{ font-size: 22px; font-weight: 700; }}
.positive {{ color: var(--green); }}
.negative, .negative-text {{ color: var(--red); }}
.panel {{ padding: 16px; margin-bottom: 18px; overflow: hidden; }}
.panel h2 {{ margin: 0 0 12px; font-size: 16px; }}
.grid-2 {{ display: grid; grid-template-columns: 2fr 1fr; gap: 18px; }}
.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: var(--brand); color: #fff; text-align: left; padding: 9px 10px; font-weight: 600; white-space: nowrap; }}
td {{ border-bottom: 1px solid var(--line); padding: 8px 10px; white-space: nowrap; }}
tr:hover td {{ background: #f8fafc; }}
.note {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}
.footer {{ color: var(--muted); text-align: center; font-size: 12px; padding: 12px 0; }}
@media (max-width: 860px) {{
  .container {{ padding: 12px; }}
  .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .grid-2 {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 520px) {{
  .header {{ padding: 16px; }}
  .header h1 {{ font-size: 18px; }}
  .card-value {{ font-size: 17px; }}
  .panel {{ padding: 10px; }}
  .table-wrap table, .table-wrap thead, .table-wrap tbody, .table-wrap th, .table-wrap td, .table-wrap tr {{ display: block; }}
  .table-wrap thead {{ display: none; }}
  .table-wrap tr {{ border: 1px solid var(--line); border-radius: 8px; margin-bottom: 8px; padding: 8px; }}
  .table-wrap td {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #eef2f7; white-space: normal; }}
  .table-wrap td:last-child {{ border-bottom: 0; }}
  .table-wrap td::before {{ content: attr(data-label); color: var(--muted); font-weight: 600; }}
}}
</style>
</head>
<body>
<div class="container">
  <section class="header">
    <h1>{escaped_title}</h1>
    <p>Generated {html.escape(generated_at)} · quant-trading-cn backtest report</p>
  </section>

  <section class="cards">
    {cards_html}
  </section>

  <section class="panel">
    <div id="equityChart"></div>
  </section>

  <section class="grid-2">
    <div class="panel">
      <div id="monthlyChart"></div>
    </div>
    <div class="panel">
      <h2>回测信息</h2>
      <div class="table-wrap"><table><tbody>{summary_rows}</tbody></table></div>
    </div>
  </section>

  <section class="panel">
    <h2>Top 回撤区间</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>开始</th><th>谷底</th><th>结束</th><th>回撤</th><th>持续</th></tr></thead>
        <tbody>{drawdown_rows}</tbody>
      </table>
    </div>
  </section>

  <section class="panel">
    <h2>调仓/选股明细</h2>
    <div class="table-wrap">
      <table>
        <thead>{trade_header}</thead>
        <tbody>{trade_rows}</tbody>
      </table>
    </div>
    <div class="note">默认展示最近 {max_trade_rows} 行；完整记录请查看原始 trade_log 文件。</div>
  </section>

  <div class="footer">Generated by scripts/backtest_html_report.py</div>
</div>

<script>
const payload = {_json_for_script(chart_payload)};
Plotly.newPlot('equityChart', [
  {{
    x: payload.dates,
    y: payload.equity,
    type: 'scatter',
    mode: 'lines',
    name: '策略净值',
    line: {{color: '#286f8f', width: 2.5}},
    hovertemplate: '%{{x}}<br>净值: %{{y:.4f}}<extra></extra>'
  }},
  {{
    x: payload.dates,
    y: payload.drawdown,
    type: 'scatter',
    mode: 'lines',
    name: '回撤',
    yaxis: 'y2',
    fill: 'tozeroy',
    line: {{color: '#d04437', width: 1.2}},
    hovertemplate: '%{{x}}<br>回撤: %{{y:.2f}}%<extra></extra>'
  }}
], {{
  title: {{text: '净值曲线与回撤', x: 0.5}},
  height: 510,
  margin: {{l: 56, r: 56, t: 52, b: 42}},
  hovermode: 'x unified',
  template: 'plotly_white',
  yaxis: {{title: '净值'}},
  yaxis2: {{title: '回撤 %', overlaying: 'y', side: 'right', tickformat: '.1f'}},
  legend: {{orientation: 'h', y: -0.18}}
}}, {{responsive: true}});

Plotly.newPlot('monthlyChart', [{{
  z: payload.monthlyZ,
  x: payload.monthlyMonths,
  y: payload.monthlyYears,
  text: payload.monthlyText,
  texttemplate: '%{{text}}',
  type: 'heatmap',
  colorscale: [[0, '#c0392b'], [0.5, '#f2f4f7'], [1, '#1f9d63']],
  zmid: 0,
  hovertemplate: '%{{y}} %{{x}}<br>%{{text}}<extra></extra>'
}}], {{
  title: {{text: '月度收益热力图', x: 0.5}},
  height: Math.max(260, 140 + payload.monthlyYears.length * 42),
  margin: {{l: 44, r: 24, t: 48, b: 32}},
  template: 'plotly_white',
  yaxis: {{autorange: 'reversed'}}
}}, {{responsive: true}});
</script>
</body>
</html>
"""


def generate_backtest_html_report(
    run_dir: str | Path,
    output_path: str | Path | None = None,
    *,
    title: str | None = None,
    max_trade_rows: int = 300,
) -> Path:
    """Generate an HTML report for one backtest output directory.

    Args:
        run_dir: Directory containing summary.json, equity_curve.parquet, trade_log.parquet.
        output_path: Optional HTML path. Defaults to run_dir/backtest_report.html.
        title: Optional report title.
        max_trade_rows: Maximum trade rows embedded in the HTML table.

    Returns:
        Path to the generated HTML report.
    """
    run_dir = Path(run_dir)
    summary_path = run_dir / "summary.json"
    equity_path = run_dir / "equity_curve.parquet"
    trade_path = run_dir / "trade_log.parquet"
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)
    if not equity_path.exists():
        alt = run_dir / "equity_curve.csv"
        if alt.exists():
            equity_path = alt
        else:
            raise FileNotFoundError(equity_path)
    if not trade_path.exists():
        alt = run_dir / "trade_log.csv"
        if alt.exists():
            trade_path = alt
        else:
            raise FileNotFoundError(trade_path)

    summary = _load_json(summary_path)
    equity = _read_table(equity_path)
    trades = _read_table(trade_path)
    report_title = title or str(summary.get("profile_label") or summary.get("profile_name") or run_dir.name)
    html_text = build_report_html(summary=summary, equity=equity, trades=trades, title=report_title, max_trade_rows=max_trade_rows)

    output = Path(output_path) if output_path else run_dir / "backtest_report.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a quant-trading-cn HTML backtest report.")
    parser.add_argument("--run-dir", required=True, help="Directory containing summary/equity_curve/trade_log artifacts.")
    parser.add_argument("--output", default=None, help="Output HTML path. Defaults to <run-dir>/backtest_report.html.")
    parser.add_argument("--title", default=None, help="Report title.")
    parser.add_argument("--max-trade-rows", type=int, default=300, help="Maximum trade rows embedded in the report.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = generate_backtest_html_report(
        args.run_dir,
        args.output,
        title=args.title,
        max_trade_rows=args.max_trade_rows,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
