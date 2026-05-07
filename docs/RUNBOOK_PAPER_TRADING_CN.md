# A 股 Paper Trading 运行手册

本手册是以后手动或让 Codex 代跑 paper trading 时的唯一操作准绳。不要靠记忆跑，先看这个文件和 `paper_trading_config.yaml`。

## 当前固定假设

- 字体默认：微软雅黑 / Microsoft YaHei。
- Broker：本地 A 股 paper gateway。
- 默认地址：`http://127.0.0.1:18080`。
- 执行模式：`latest_only`。
- 调仓频率：每 5 个交易日一次。
- 模型重训：默认每 20 个交易日一次，不是每次调仓都重训。
- 完整研究复盘：默认每 60 个交易日一次。
- 价格来源：`inference_scores_latest.parquet` 里的日线 `close`。
- 当前不是实时分钟价，不是 9:35 盘口价。
- 当前成交价：`close` 加减滑点。
- 买入价：`close * (1 + buy_limit_bps / 10000)`。
- 卖出价：`close * (1 - sell_limit_bps / 10000)`。
- 默认滑点：买入 50 bps，卖出 50 bps。
- 默认手续费：佣金 3 bps，最低 5 元；卖出印花税 5 bps；过户费 0.1 bps。
- A 股一手：100 股。
- 不允许卖空。
- 默认执行 T+1。

## 最重要的边界

这个系统可以做到：

- 刷新最新行情后，按最新 close 给当前持仓 mark-to-market。
- 从当前持仓调到最新 Top10。
- 保存订单、成交、现金、持仓、净值。
- 让我们验证策略从信号到交易收益的完整链路。

这个系统当前不会做到：

- 不会自动在真实 9:35 按盘口成交。
- 不会使用实时分钟价。
- 不会在你忘记运行时自动补做中间调仓。
- 不会保证 15 天后跑一次等于每 5 天准时跑三次。

一句话：**估值可以补，交易路径不能无损补。**

## 第一次启动本地 broker

如果要新开一个干净 paper account：

```powershell
python local_a_share_paper_gateway.py --port 18080 --state-dir quant_data/local_a_share_paper_gateway --initial-cash 1000000 --reset
```

如果要延续上次持仓：

```powershell
python local_a_share_paper_gateway.py --port 18080 --state-dir quant_data/local_a_share_paper_gateway --initial-cash 1000000
```

检查是否在线：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
```

## 每日收盘后只刷新市值

如果只是想看当前组合按最新本地数据的市值：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --skip-rebalance
```

如果需要先联网补最新日线数据：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --skip-rebalance
```

## 每 5 个交易日调仓

中证500：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --force
```

中证2000：

```powershell
python scripts\run_incremental_rebalance.py --index csi2000 --update-data --force
```

上证50：

```powershell
python scripts\run_incremental_rebalance.py --index sse50 --update-data --force
```

## 不想真实模拟成交，只看计划

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --dry-run --force
```

## 如果隔了 15 天才来跑

先接受这个事实：结果不会等于每 5 天准时调仓。

推荐做法：

1. 运行 `--update-data --skip-rebalance`，先看当前持仓真实估值。
2. 打开 `incremental_rebalance_summary.json`，确认 `missed_window_warning`。
3. 再运行 `--update-data --dry-run --force`，先看新 Top10 和计划交易。
4. 如果计划合理，再运行 `--update-data --force` 成交。

命令：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --skip-rebalance
python scripts\run_incremental_rebalance.py --index csi500 --update-data --dry-run --force
python scripts\run_incremental_rebalance.py --index csi500 --update-data --force
```

## Catch-up 历史回放

如果中间漏跑了几次调仓，可以用 catch-up 脚本重建“如果当时每 5 天都调仓”的研究路径。

默认只生成回放订单和净值，不会改当前 broker 持仓：

```powershell
python scripts\run_catchup_rebalance.py --index csi500 --from-date 2026-04-01 --to-date 2026-04-21
```

输出位置：

```text
quant_data/paper_trading_local_csi500/catchup_runs/latest/
```

主要文件：

- `catchup_orders.csv`
- `catchup_orders.parquet`
- `catchup_equity.csv`
- `catchup_equity.parquet`
- `catchup_summary.json`

非常重要：

- Catch-up 是历史 OOS 预测回放，不是真实补单。
- 它可以用于研究“漏跑期间如果按规则调仓，收益路径会怎样”。
- 它不能证明你的真实 paper account 当时已经发生这些交易。
- 默认不要加 `--apply-to-gateway`。
- 如果真的要把 catch-up 订单打进本地 gateway，必须先确认当前 broker 是专门用于 catch-up 的空账户或已重置账户。

只有明确要把历史重建订单写进本地 broker 时，才使用：

```powershell
python scripts\run_catchup_rebalance.py --index csi500 --from-date 2026-04-01 --to-date 2026-04-21 --apply-to-gateway
```

## 结果看哪里

Broker 账户：

- `quant_data/local_a_share_paper_gateway/broker_state.json`
- `quant_data/local_a_share_paper_gateway/orders.jsonl`
- `quant_data/local_a_share_paper_gateway/fills.jsonl`
- `quant_data/local_a_share_paper_gateway/equity_curve.jsonl`

每个指数的调仓结果：

- `quant_data/paper_trading_local_csi500/state.json`
- `quant_data/paper_trading_local_csi500/targets_latest.parquet`
- `quant_data/paper_trading_local_csi500/incremental_rebalance_summary.json`

把 `csi500` 换成 `csi2000` 或 `sse50` 即可。

## 配置源

默认参数写在：

```text
paper_trading_config.yaml
```

以后不要凭感觉改命令参数。先改配置，再运行脚本。

## Codex 代跑提示词

以后可以直接对 Codex 说：

```text
请按 docs/RUNBOOK_PAPER_TRADING_CN.md 和 paper_trading_config.yaml，帮我跑一次 csi500 paper trading。先检查 broker health，再 update-data，先 dry-run 给我看计划，确认后再正式 rebalance。
```

如果只看市值：

```text
请按 runbook 只刷新 csi500 的 paper trading mark-to-market，不下单。
```

如果隔了很多天：

```text
我隔了很多天没跑，请按 runbook 的 15 天漏跑流程，先估值，再 dry-run，不要直接成交。
```

## 未来升级

下一步如果要更贴近真实交易，可以增加：

- `next_open_with_slippage`：T 日收盘出信号，T+1 开盘成交。
- `next_0935_bar`：T+1 9:35 分钟线成交。
- `vwap_30min`：T+1 前 30 分钟 VWAP 成交。
- `catch_up`：按历史信号回放错过的调仓窗口。
- Windows Task Scheduler：每天收盘后自动估值，每 5 个交易日自动调仓。
