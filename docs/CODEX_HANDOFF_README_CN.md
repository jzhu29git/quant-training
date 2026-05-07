# Codex 交接 README：quant-trading-cn

这份文档的目的很简单：以后如果换账号、换线程、换机器，新的 Codex 不需要你从头讲一遍。先读这个文件，再读它指向的 runbook 和配置文件，就能知道这个项目现在做到哪里、怎么继续、哪些地方不能乱跑。

## 一句话版

`quant-trading-cn` 是一个 A 股量化研究到 paper trading 的完整项目：下载行情，做特征，训练/比较模型，回测，生成最新可交易候选，最后用本地 paper broker 模拟下单、持仓、现金和净值。

当前最重要的边界：

- 这是研究级 paper trading，不是实盘交易。
- 默认不是实时分钟价，不是 9:35 盘口价。
- 默认用日线 `close` 加滑点模拟成交。
- 市值可以用最新价格重新估值，也就是 mark-to-market。
- 漏跑的中间调仓不能被无损补回来，只能用 catch-up 做研究回放。

## 当前项目位置

项目根目录：

```text
C:\Users\Administrator\quant-trading-cn
```

最该先看的文件：

- `README.md`：英文版项目总览。
- `docs/RUNBOOK_PAPER_TRADING_CN.md`：paper trading 的实际操作准绳。
- `docs/A_SHARE_LOCAL_PAPER_TRADING_CN.md`：本地 A 股 paper broker 和交易链路说明。
- `paper_trading_config.yaml`：paper trading 默认参数来源。
- `scripts/run_incremental_rebalance.py`：最新信号增量打分、估值、调仓入口。
- `scripts/run_catchup_rebalance.py`：漏跑调仓的历史 catch-up 回放入口。
- `backtest_walk_forward.py`：LightGBM walk-forward 回测入口。

## 我们已经做过什么

### 1. 基础量化流水线

项目已经有从数据到模型再到回测的主流程：

```text
行情/估值数据
  -> 特征工程
  -> 训练 LightGBM / 其他模型
  -> 最新 inference 打分
  -> walk-forward 回测
  -> TopK 候选
  -> paper trading 调仓
```

核心脚本：

- `download_data.py`：下载或增量更新 A 股行情/估值。
- `feature_engineering.py`：生成训练特征和标签。
- `build_inference_features.py`：生成最新可打分特征。
- `train_lightgbm.py`：训练 LightGBM。
- `backtest_walk_forward.py`：严格样本外 walk-forward 回测。
- `paper_trade_futu.py`：把模型分数变成目标持仓和模拟订单。

### 2. 中证500模型 bakeoff

我们做过一轮比较复杂的中证500模型比较，重点是从交易员角度看“哪个模型更适合拿来选股”。

重要路径：

```text
quant_data/csi500_2y_run/model_bakeoff_fast_v2/
```

关键结论来自当时那版数据快照，后续数据更新后要重新验证：

- `lightgbm_regressor` 当时赢了 Top1 / Top3 / Top5。
- `extra_trees` 当时赢了 Top10 / Top20。
- `lightgbm_ranker` 在快速粗标签版本里表现偏弱，但不能直接说明 ranker 永远不行。
- `ridge` 是基准模型，主要用于 sanity check。
- `XGBoost` 当时环境没有安装，所以没有纳入最终比较。

最重要的日期边界：

- `2026-04-30` 是当时的最新可交易候选日。
- `2026-04-21` 是当时最后一个有未来收益验证的回测评估日。

以后问“最新候选”时，必须先确认到底是：

- 要最新可交易候选，也就是 inference 日期。
- 还是要最后一个可验证回测日期。

### 3. 交易员视角报告

我们已经生成过一份交易员视角 Word 报告，结构是：

```text
第一页 executive summary
  -> 模型解释
  -> TopK 表现对比
  -> 交易含义
  -> 各模型最后 Top10
  -> 旧流程对比
  -> 最新可交易候选
  -> 风险和下一步
```

当时报告路径：

```text
quant_data/csi500_2y_run/model_bakeoff_fast_v2/中证500模型比较_交易员视角报告.docx
```

生成脚本：

```text
scripts/generate_csi500_model_bakeoff_report.py
```

以后如果继续做报告，用户偏好是：

- 先 executive summary。
- 用交易员语言，不要先讲 ML 黑话。
- 必须包含各模型最终 Top10。
- 必须区分最新可交易日和回测验证日。
- 如果问“和原来有什么不同”，要给股票级别 diff，不只是模型指标。

## Paper trading 当前设计

最权威的操作说明在：

```text
docs/RUNBOOK_PAPER_TRADING_CN.md
paper_trading_config.yaml
```

默认 broker：

```text
http://127.0.0.1:18080
```

本地 broker 状态目录：

```text
quant_data/local_a_share_paper_gateway/
```

每个指数的 paper trading 状态：

```text
quant_data/paper_trading_local_csi500/
quant_data/paper_trading_local_csi2000/
quant_data/paper_trading_local_sse50/
```

默认指数配置：

```text
csi500  -> momentum_liquidity, Top10
csi2000 -> momentum_liquidity, Top10
sse50   -> valuation_momentum, Top10
```

默认执行参数：

- 每 5 个交易日调仓一次。
- 模型默认每 20 个交易日重训一次，不是每天重训。
- 买入价约等于 `close * (1 + 50 bps)`。
- 卖出价约等于 `close * (1 - 50 bps)`。
- 佣金 3 bps，最低 5 元。
- 卖出印花税 5 bps。
- 过户费 0.1 bps。
- A 股一手 100 股。
- 不允许卖空。
- 默认 T+1。

## Mark-to-market 是什么

人话版：

mark-to-market 就是“不给你假装还是买入价，而是按最新市场价格重新算当前持仓值多少钱”。

在这个项目里，它的作用是：

- 你上次模拟买入了一批股票。
- 后面即使没有下单，也可以用最新 `close` 更新这些持仓的当前市值。
- broker 汇总会重新算：
  - 现金 `cash`
  - 持仓市值 `market_value`
  - 总资产 `total_assets`
  - 未实现盈亏 `unrealized_pnl`

对应实现：

- `local_a_share_paper_gateway.py` 会在查询 summary / balance / positions 时用 quote 或 last price 更新持仓。
- `paper_trade_futu.py` 会读取 gateway 当前持仓和市值，生成调仓计划。
- `scripts/run_incremental_rebalance.py --skip-rebalance` 可以只刷新打分和市值，不下单。

只做估值、不下单：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --skip-rebalance
```

最重要的边界：

- mark-to-market 可以补“现在这些持仓值多少钱”。
- mark-to-market 不能补“过去漏掉的几次调仓如果当时做了会怎样”。

一句话：估值能补，交易路径不能无损补。

## Catch-up trade 是什么

人话版：

catch-up 不是穿越回去真的补单。它是拿历史 OOS 信号和历史收盘价，重建一条“如果当时每 5 天都按规则调仓，账户可能怎么走”的研究路径。

对应脚本：

```text
scripts/run_catchup_rebalance.py
```

默认模式：

- 读取历史 OOS predictions。
- 读取历史 close 价格。
- 按每个调仓日选 TopK。
- 卖出不在新 TopK 的旧票。
- 对新 TopK 做等权目标仓位。
- 按 100 股一手取整。
- 计入滑点、佣金、印花税、过户费。
- 输出模拟订单和净值路径。
- 默认不改本地 broker。

推荐命令：

```powershell
python scripts\run_catchup_rebalance.py --index csi500 --from-date 2026-04-01 --to-date 2026-04-21
```

输出位置：

```text
quant_data/paper_trading_local_csi500/catchup_runs/latest/
```

输出文件：

- `catchup_orders.csv`
- `catchup_orders.parquet`
- `catchup_equity.csv`
- `catchup_equity.parquet`
- `catchup_summary.json`

非常重要：

- 默认不要加 `--apply-to-gateway`。
- catch-up 是研究回放，不是真实历史成交证明。
- 如果要真的写入 gateway，必须确认当前 broker 是空账户或专门用于 catch-up 的账户。

危险命令，只在明确知道自己要做什么时使用：

```powershell
python scripts\run_catchup_rebalance.py --index csi500 --from-date 2026-04-01 --to-date 2026-04-21 --apply-to-gateway
```

## 如果隔了很多天没跑，怎么处理

不要直接正式调仓。按这个顺序：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --skip-rebalance
python scripts\run_incremental_rebalance.py --index csi500 --update-data --dry-run --force
python scripts\run_incremental_rebalance.py --index csi500 --update-data --force
```

解释：

- 第一步：先更新数据，只看当前持仓估值。
- 第二步：只看新 Top10 和调仓计划，不成交。
- 第三步：确认计划合理后再模拟成交。

如果想研究“如果中间每 5 天都跑，会怎样”，再另外运行 catch-up。

## 常用命令

启动干净本地 paper broker：

```powershell
python local_a_share_paper_gateway.py --port 18080 --state-dir quant_data/local_a_share_paper_gateway --initial-cash 1000000 --reset
```

延续上次本地 paper broker：

```powershell
python local_a_share_paper_gateway.py --port 18080 --state-dir quant_data/local_a_share_paper_gateway --initial-cash 1000000
```

检查 broker：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
Invoke-RestMethod http://127.0.0.1:18080/v1/agents/me/summary
Invoke-RestMethod http://127.0.0.1:18080/v1/agents/me/positions
```

中证500只估值：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --skip-rebalance
```

中证500先看计划：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --dry-run --force
```

中证500正式 paper rebalance：

```powershell
python scripts\run_incremental_rebalance.py --index csi500 --update-data --force
```

中证2000正式 paper rebalance：

```powershell
python scripts\run_incremental_rebalance.py --index csi2000 --update-data --force
```

上证50正式 paper rebalance：

```powershell
python scripts\run_incremental_rebalance.py --index sse50 --update-data --force
```

catch-up 研究回放：

```powershell
python scripts\run_catchup_rebalance.py --index csi500 --from-date YYYY-MM-DD --to-date YYYY-MM-DD
```

## 新 Codex 接手时先做什么

新线程/新账号请先读：

```text
docs/CODEX_HANDOFF_README_CN.md
docs/RUNBOOK_PAPER_TRADING_CN.md
paper_trading_config.yaml
```

然后检查：

```powershell
git status --short
Test-Path quant_data/csi500_2y_run/ml_features_ready.parquet
Test-Path quant_data/csi500_2y_run/inference_features_latest.parquet
Test-Path quant_data/csi500_2y_run/feature_group_tests/momentum_liquidity/models/inference_scores_latest.parquet
Test-Path quant_data/paper_trading_local_csi500/state.json
```

如果用户问“现在能不能跑”，不要直接答能。先确认：

- 需要的数据 parquet 是否存在。
- broker 是否在线。
- 是只估值、dry-run，还是正式 paper rebalance。
- 是否隔了很多天没跑。
- 是否需要 catch-up 研究回放。

## 推荐给未来 Codex 的提示词

只估值：

```text
请先读 docs/CODEX_HANDOFF_README_CN.md、docs/RUNBOOK_PAPER_TRADING_CN.md 和 paper_trading_config.yaml。然后只刷新 csi500 的 mark-to-market，不下单，跑之前先检查 broker health 和需要的数据文件。
```

正式调仓前检查：

```text
请按 quant-trading-cn 的交接 README 和 runbook，帮我跑 csi500。先 update-data + skip-rebalance 看估值，再 dry-run 给我看计划，不要直接正式成交。
```

漏跑很多天：

```text
我隔了很多天没跑 quant-trading-cn。请先按 runbook 做 mark-to-market 和 dry-run，再判断是否需要 catch-up 研究回放。不要直接 apply-to-gateway。
```

重新做中证500模型比较：

```text
请先读 docs/CODEX_HANDOFF_README_CN.md，重新检查当前 quant_data/csi500_2y_run 的最新日期，然后复跑模型 bakeoff。报告要第一页 executive summary，后面详细分析和交易建议，并包含各模型最终 Top10。
```

## 未来可以继续做的事

- 加 Windows Task Scheduler：每天收盘后自动 mark-to-market，每 5 个交易日自动 dry-run 或调仓。
- 把成交价从 `close_with_slippage` 升级成 T+1 开盘价或 9:35 分钟线。
- 给 `catch-up` 增加更清楚的账户隔离保护，避免误写当前 broker。
- 重新做 ranker 标签设计，再判断 LightGBM Ranker 是否真的不适合。
- 安装 XGBoost 后补跑 XGBoost 对比。
- 将报告生成流程标准化成一键命令。
