# quant-trading-cn 中文使用说明

这份文档用交易员能落地的方式解释这个项目怎么用。它不是预测明天涨停的工具，而是一个“每隔几个交易日重新给股票池打分、生成候选名单、辅助调仓”的研究和模拟交易系统。

## 一句话理解

系统每隔 5 个交易日，把股票池里的所有股票重新打分，选出模型认为未来 5 个交易日更有机会跑赢的 TopK，然后按组合方式调仓。

它更像：

- 盘前选股助手
- 调仓名单生成器
- 组合研究工具
- 模拟交易执行器

它暂时不应该被当成无人值守的实盘系统。

## 全流程做什么

| 步骤 | 做什么 | 交易员怎么理解 |
|---|---|---|
| Step 1 | 下载日线、成交量、换手、估值数据 | 准备行情和基础面板 |
| Step 2 | 生成训练特征和未来 5 日标签 | 告诉模型以前什么形态容易涨 |
| Step 3 | 生成最新一天的推理特征 | 准备今天要打分的股票表 |
| Step 4 | 训练 LightGBM 并给最新截面打分 | 生成最新 Top10 / Top20 候选 |
| Step 5 | walk-forward 回测 | 模拟历史上每 5 天调仓一次的效果 |
| Step 6 | Futu paper trading | 把最新候选转成模拟目标持仓和订单 |

## 模型到底学什么

训练标签很简单：

```text
如果今天买入一只股票，未来 5 个交易日收益是否超过 2%？
超过就是 1，否则就是 0。
```

所以模型学的是：

```text
这只股票未来 5 天涨超 2% 的概率高不高。
```

它不是直接预测明天涨跌，也不是预测具体涨幅。

LightGBM 可以理解成很多小交易规则树的集合。它会学习类似这样的组合条件：

- 短期涨跌幅
- 20 日趋势
- 是否偏离 20 日均线
- 换手率
- 成交额
- 波动率
- 估值

这些条件一起出现时，未来 5 日更容易上涨还是不容易上涨。

## 因子和权重会不会动态变化

要分三件事：

1. 因子集合不会自动变化。

例如 `momentum_liquidity` 固定使用均线、涨跌幅、成交额、换手等一组特征。模型不会自己突然发明 RSI、MACD 或行业强弱，除非我们写代码加进去。

2. 模型内部规则会重新学习。

每次重新训练，LightGBM 会根据截至当时的历史数据重新学习。同一个因子，这次可能很重要，下次可能不那么重要。

3. 超参数基本固定。

例如：

- 未来 5 日标签
- 涨超 2% 作为正样本
- TopK 数量
- 树模型参数
- 调仓频率

这些不会在回测中自动优化。

## 有没有最终因子权重

没有简单的线性权重表。

LightGBM 不是：

```text
30% 动量 + 20% 换手 + 10% 估值
```

它是很多非线性规则树的组合。我们能看的主要是 `feature_importance.csv`，也就是特征重要性。

目前实验大致可以这样理解：

- 中证 500：动量 + 换手是核心。
- 中证 2000：短期涨跌幅 + 成交额/换手是核心，但交易摩擦风险大。
- 上证 50：估值 + 波动结构更明显。

## OOS walk-forward 是什么

OOS walk-forward 的意思是：

```text
站在历史上的某一天，只用那天以前的数据训练模型，然后预测那天股票的排名。
过 5 个交易日后，再看这些股票真实表现。
```

它的目的就是避免偷看未来。

回测里 `future_return` 只用于事后验证，不用于当天选股。

当前逻辑：

- 每 5 个交易日调仓一次。
- 每 20 次调仓重新训练一次模型。
- 大约相当于每 100 个交易日重新训练一次。

相关代码：

- `backtest_walk_forward.py`
- `train_lightgbm.py`
- `feature_engineering.py`

## 5 天后具体怎么操作

假设今天模型给出 Top10，标准做法是买入可交易的 Top10，并持有 5 个交易日。

5 个交易日后，重新更新数据并重新生成 Top10。然后做再平衡：

```text
旧 Top10 ∩ 新 Top10：继续持有或微调仓位
旧 Top10 不在 新 Top10：卖出
新 Top10 但当前没有：买入
```

如果做等权 Top10：

```text
每只目标仓位约 10%
```

如果做 Top5：

```text
每只目标仓位约 20%
```

中证 2000 不建议 Top5 过度集中。中证 500 Top5 / Top10 更值得继续研究。

## 日常使用建议

先不要一上来全自动实盘。建议先做人工辅助交易：

1. 每 5 个交易日更新数据。
2. 生成最新 Top10。
3. 人工过滤不可交易票。
4. 手动或模拟下单。
5. 记录实际成交、滑点和无法成交情况。

人工过滤至少包括：

- ST
- 停牌
- 接近涨停
- 接近跌停
- 成交额太小
- 一字板
- 财报雷
- 盘口太薄

等模拟跑顺以后，再考虑让 Futu paper trading 自动同步目标仓位。

## 常用命令

运行中证 2000 全流程示例：

```powershell
python scripts\run_index_research_pipeline.py --universe csi2000 --index-code 932000 --label 中证2000 --run-dir quant_data/csi2000_2y_run --start-date 20240430 --end-date 20260430 --sleep 0.05
```

重新生成三个指数交易员视角 Word 报告：

```powershell
python scripts\generate_three_index_trader_insights_docx.py
```

生成这份使用说明的 Word 版本：

```powershell
python scripts\generate_quant_usage_guide_docx.py
```

## 怎么看最新 Top10

最新打分通常保存在：

```text
quant_data/<run_name>/models/inference_scores_latest.parquet
```

如果是特征组模型，例如中证 2000 的 `momentum_liquidity`：

```text
quant_data/csi2000_2y_run/feature_group_tests/momentum_liquidity/models/inference_scores_latest.parquet
```

读取 Top10 示例：

```powershell
python -c "import pandas as pd; df=pd.read_parquet('quant_data/csi2000_2y_run/feature_group_tests/momentum_liquidity/models/inference_scores_latest.parquet'); print(df.head(10)[['date','code','name','score']].to_string(index=False))"
```

## Futu 模拟交易是什么

Futu 模拟交易不是模型本身，而是执行层。

它做的事情：

1. 读取最新 `inference_scores_latest.parquet`。
2. 选出分数超过阈值的 TopK。
3. 查询当前模拟账户持仓。
4. 生成目标仓位。
5. 对比当前持仓和目标持仓。
6. 生成买卖计划。
7. 通过外部 Futu gateway 下模拟单。

默认参数大致是：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| TopK | 5 | 持有前 5 名 |
| min_score | 0.5 | 分数低于 0.5 不买 |
| lot_size | 100 | A 股一手 100 股 |
| cash_buffer_pct | 2% | 保留 2% 现金 |
| buy_limit_bps | 50bp | 买入限价比参考价高 0.5% |
| sell_limit_bps | 50bp | 卖出限价比参考价低 0.5% |
| max_order_qty | 1000 | 单笔最多 1000 股 |

daemon 是后台循环，每隔一段时间检查最新分数文件是否变化。

- 分数文件没变：不重复交易。
- 分数文件变了：重新同步目标仓位。

相关代码：

- `paper_trade_futu.py`
- `paper_trade_daemon.py`

## Futu 模拟交易安全提醒

`paper_trade_futu.py` 会调用外部 gateway 的下单接口。

是否真钱取决于 gateway 后面接的是模拟账户还是真实账户。

没有完全确认之前，必须先用：

```text
--dry-run
```

或者只看生成的：

```text
quant_data/paper_trading/targets_latest.parquet
```

不要直接让它自动下单。

## 当前系统最大的不足

从交易员角度，当前系统还有这些不足：

- 回测没有充分计入真实交易成本。
- 没有严格模拟涨跌停无法成交。
- 中证 2000 还需要先过滤 ST、停牌和极低流动性股票。
- 没有行业暴露控制。
- 没有完整止损/止盈规则。
- 目前更像选股器和组合研究工具，不是完整无人值守交易系统。

## 推荐下一步

建议按这个顺序推进：

1. 固定主策略为中证 500 `momentum_liquidity Top10`。
2. 加入 ST、停牌、涨跌停过滤。
3. 加入成交额和容量过滤。
4. 加入手续费、印花税、滑点回测。
5. 用 Futu dry-run 生成目标仓位。
6. 跑一段模拟交易。
7. 再考虑小资金实盘。

最重要的一句话：

```text
模型负责告诉你哪些股票更值得看；
交易系统必须负责哪些股票真的能买、能卖、能控制风险。
```
