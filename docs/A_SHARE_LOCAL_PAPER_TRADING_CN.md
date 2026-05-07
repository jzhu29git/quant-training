# A 股本地模拟交易网关使用说明

这个文件说明如何用本地 A 股 paper broker 打通策略最后一公里：从模型 `top10 prediction` 到下单、成交、持仓、现金、净值记录。

## 适用场景

当 moomoo / Futu OpenD 没有给账号开通 A 股模拟交易账户时，可以先用本地网关验证完整交易链路。

这个网关不是实盘券商，也不是交易所撮合。它是一个可复现的本地模拟撮合器，目标是让我们验证：

- 每次模型出新的 TopK 后是否能自动生成目标持仓。
- 是否能按 100 股一手完成买卖。
- 是否能保存订单、成交、持仓、现金和净值。
- 是否能在下一次调仓时卖出旧票、买入新票。
- 交易成本和滑点进入收益统计后，策略是否仍然有交易价值。

## 启动本地 A 股 paper broker

在项目根目录运行：

```powershell
python local_a_share_paper_gateway.py --port 18080 --state-dir quant_data/local_a_share_paper_gateway --initial-cash 1000000 --reset
```

说明：

- `--port 18080`：本地 REST 接口端口，避免和 moomoo gateway 的 `8080` 冲突。
- `--state-dir`：订单、成交、持仓、净值保存目录。
- `--initial-cash 1000000`：初始资金 100 万人民币。
- `--reset`：重新开始一个干净模拟账户。如果想延续上次持仓，不要加这个参数。

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
```

## 跑一次中证500 Top10 调仓

```powershell
python paper_trade_futu.py `
  --scores-path quant_data\csi500_2y_run\models\inference_scores_latest.parquet `
  --state-dir quant_data\paper_trading_local_csi500 `
  --gateway-base-url http://127.0.0.1:18080 `
  --market CN `
  --top-k 10 `
  --min-score 0.5 `
  --budget-total 1000000 `
  --lot-size 100 `
  --max-order-qty 20000 `
  --force
```

## 跑一次中证2000 Top10 调仓

```powershell
python paper_trade_futu.py `
  --scores-path quant_data\csi2000_2y_run\models\inference_scores_latest.parquet `
  --state-dir quant_data\paper_trading_local_csi2000 `
  --gateway-base-url http://127.0.0.1:18080 `
  --market CN `
  --top-k 10 `
  --min-score 0.5 `
  --budget-total 1000000 `
  --lot-size 100 `
  --max-order-qty 20000 `
  --force
```

## 跑一次上证50 Top10 调仓

```powershell
python paper_trade_futu.py `
  --scores-path quant_data\sse50_2y_run\models\inference_scores_latest.parquet `
  --state-dir quant_data\paper_trading_local_sse50 `
  --gateway-base-url http://127.0.0.1:18080 `
  --market CN `
  --top-k 10 `
  --min-score 0.5 `
  --budget-total 1000000 `
  --lot-size 100 `
  --max-order-qty 20000 `
  --force
```

## 查看当前持仓

```powershell
Invoke-RestMethod http://127.0.0.1:18080/v1/agents/me/positions
```

## 查看账户汇总

```powershell
Invoke-RestMethod http://127.0.0.1:18080/v1/agents/me/summary
```

## 输出文件

本地 broker 的文件：

- `quant_data/local_a_share_paper_gateway/broker_state.json`：当前现金、持仓、订单状态。
- `quant_data/local_a_share_paper_gateway/orders.jsonl`：订单流水。
- `quant_data/local_a_share_paper_gateway/fills.jsonl`：成交流水。
- `quant_data/local_a_share_paper_gateway/equity_curve.jsonl`：净值快照。

每次调仓脚本的文件：

- `quant_data/paper_trading_local_*/targets_latest.parquet`：本次目标持仓、下单数量、成交状态。
- `quant_data/paper_trading_local_*/state.json`：本次调仓摘要。
- `quant_data/paper_trading_local_*/sync_history.jsonl`：每次调仓历史。

## 当前撮合规则

默认规则：

- 买入必须是 100 股整数倍。
- 不允许卖空。
- 默认执行 T+1：同一个信号日买入的股票，不能同一个信号日卖出。
- 订单立即成交，成交价使用 `paper_trade_futu.py` 发来的价格。
- 买入价通常是模型 close 价格上浮 `buy_limit_bps`。
- 卖出价通常是模型 close 价格下浮 `sell_limit_bps`。
- 默认佣金 3 bps，最低 5 元。
- 默认卖出印花税 5 bps。
- 默认过户费 0.1 bps。
- 持仓会用最新 `models/inference_scores_latest.parquet` 里的 close 做 mark-to-market。

## 交易员视角怎么用

正常节奏是：

1. 跑完整模型流程，生成新的 `inference_scores_latest.parquet`。
2. 运行 `paper_trade_futu.py`，让它生成新 Top10 目标持仓。
3. 本地 broker 自动模拟成交。
4. 观察持仓、现金、净值、交易成本。
5. 5 个交易日后重新跑模型，再执行一次调仓。

重点不是看某一次 Top10，而是看连续多次调仓以后：

- 换手率是否过高。
- 成交成本是否吞掉收益。
- 单票集中度是否过高。
- 中证500、中证2000、上证50 哪个池子的策略最稳定。
- 市场风格切换时是否明显失效。

## 增量调仓脚本

为了避免每 5 天从 Step1 完整重跑，可以使用：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --gateway-base-url http://127.0.0.1:18080 --force
```

支持的指数：

```powershell
python scripts\run_incremental_rebalance.py --index csi500
python scripts\run_incremental_rebalance.py --index csi2000
python scripts\run_incremental_rebalance.py --index sse50
```

这个脚本会做：

- 可选增量下载最新行情和估值数据。
- 用现有本地数据重新生成最新 inference features。
- 用已有 LightGBM 模型重新打分，不默认重训模型。
- 使用每个指数当前偏交易员视角的默认因子组：
  - `csi500`：`momentum_liquidity`
  - `csi2000`：`momentum_liquidity`
  - `sse50`：`valuation_momentum`
- 调用本地 paper broker 刷新账户市值。
- 如未加 `--skip-rebalance`，会调用 `paper_trade_futu.py` 执行最新 Top10 调仓。
- 输出 `incremental_rebalance_summary.json`。

只刷新打分和市值、不下单：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --skip-rebalance
```

先增量更新行情，再打分和调仓：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --gateway-base-url http://127.0.0.1:18080 --force
```

只生成计划、不成交：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --dry-run
```

## 如果隔了 15 天才运行

本地 broker 可以在你运行时用最新行情给当前持仓重新估值，所以你看到的当前市值是正常的。

前提是你运行时要么已经更新过本地行情文件，要么在命令里加了 `--update-data`。

但默认 `latest_only` 模式不会自动补做中间错过的两次 5 日调仓。也就是说：

- 当前持仓市值：可以正常刷新。
- 当前现金/持仓：是真实反映你上次模拟成交后的状态。
- 中间本该发生但你没有运行的调仓：不会被自动假装发生。
- 15 天后直接运行一次：会按最新 Top10 从当前持仓调到新目标持仓。
- 它和每 5 天都运行一次的结果不一定一样，因为中间路径不同。

如果要和“每 5 天准时运行”的结果一致，需要使用定时任务，或者后续增加 `catch-up` 历史回放模式。

## 切回 moomoo / Futu

等 moomoo 客服确认账号有 CN paper trading account 后，可以把执行端从：

```text
http://127.0.0.1:18080
```

切回：

```text
http://127.0.0.1:8080
```

也就是继续使用 `paper_trade_futu.py`，只换 `--gateway-base-url`。
