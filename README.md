# A 股量化数据准备

这个目录现在使用 `Baostock-first, AKShare-as-fallback` 的方案准备训练数据，目标是把 LightGBM 常用的三类核心数据存成 Parquet：

- `stock_list.parquet`: 股票基础列表，包含代码、交易所、名称、行业
- `quant_data/daily_kline/*.parquet`: 单只股票的前复权日 K 线
- `quant_data/daily_valuation/*.parquet`: 单只股票的每日估值数据，含总市值、流通市值、PE、PB、PS、PCF

如果你想先看一份给股市新手的完整系统说明书，请读：

- `docs/SYSTEM_MANUAL_zh-Hant.md`

如果你想看正式文档结构，请读：

- `docs/README.md`
- `docs/SYSTEM_DESIGN_SPEC_zh-Hant.md`
- `docs/USER_GUIDE_zh-Hant.md`

## 推荐方式：用 Docker 跑

这类量化数据依赖更适合放进容器里，而不是直接装在宿主机：

- 环境一致，不会出现“这台机能跑，那台机不行”
- 不污染宿主机 Python
- 后面迁移到服务器、定时任务、回测机时更省心

先构建镜像：

```bash
docker compose build
```

先跑一个小样本：

```bash
docker compose run --rm data-prep
```

下载沪深 300 全量：

```bash
docker compose run --rm data-prep --limit 0
```

下载全市场：

```bash
docker compose run --rm data-prep --universe all --limit 0
```

只刷新股票列表：

```bash
docker compose run --rm data-prep --skip-kline --skip-valuation
```

重新覆盖已有文件：

```bash
docker compose run --rm data-prep --overwrite
```

容器会把当前目录挂载到 `/app`，所以下载结果会直接落在宿主机的 `quant_data/` 目录里。

## 本地安装依赖

```bash
python3 -m pip install -r requirements.txt
```

如果系统里还没有 `pip`，先安装 `python3-pip`，或者在虚拟环境里执行上面的命令。

Debian/Ubuntu 常见安装方式：

```bash
sudo apt update
sudo apt install -y python3-pip python3.12-venv
```

如果你暂时不想用 Docker，也可以直接在本机跑。默认配置会下载沪深 300 股票池里的前 50 只，用来验证流程是否打通：

```bash
python3 download_data.py
```

## 常用命令

下载沪深 300 全量：

```bash
python3 download_data.py --limit 0
```

下载全市场：

```bash
python3 download_data.py --universe all --limit 0
```

只刷新股票列表，不下载历史数据：

```bash
python3 download_data.py --skip-kline --skip-valuation
```

跳过行业补充，加快列表刷新：

```bash
python3 download_data.py --skip-industry --skip-kline --skip-valuation
```

重新覆盖已有文件：

```bash
python3 download_data.py --overwrite
```

## 说明

- 日 K 线主数据来自 `Baostock query_history_k_data_plus`，固定使用 `adjustflag="2"`，即前复权。
- `Baostock` 的历史数据默认全是字符串，脚本已经统一做了日期与数值类型转换。
- `stock_list.parquet` 会额外保存 `exchange` 列，后续下载、合并和特征工程优先使用 `code + exchange`，不再依赖六位代码猜交易所。
- 刷新 `stock_list.parquet` 时会优先沿用已有的 `industry` / `industry_classification`；默认只为新股或缺失行业信息的股票补查行业，而不是每次全量重刷。
- `Baostock` 使用 `sh.600000` / `sz.000001` 这类代码格式；脚本内部会自动和普通六位代码互转，落盘时统一保存为六位代码。
- 每日估值里的 `PE/PB/PS/PCF` 来自 `Baostock`，`总市值/流通市值/总股本/流通股本` 由 `AKShare stock_value_em` 补充后再按 `date + code` 合并。
- 免费接口存在限流风险，脚本默认每次请求暂停 `0.5` 秒；全市场下载建议长时间挂机执行。
- 如果部分股票下载失败，失败明细会写入 `quant_data/download_failures.csv`。

## 特征工程

把本地 parquet 合并成可直接喂给 LightGBM 的训练集：

```bash
python3 feature_engineering.py
```

或者用 Docker：

```bash
docker compose run --rm --entrypoint python data-prep feature_engineering.py
```

默认输出到：

```bash
quant_data/ml_features_ready.parquet
```

生成实盘推理特征：

```bash
python3 build_inference_features.py
```

或者用 Docker：

```bash
docker compose run --rm --entrypoint python data-prep build_inference_features.py
```

默认输出到：

```bash
quant_data/inference_features_latest.parquet
```

## 训练模型

训练 LightGBM，并对最新推理特征打分：

```bash
python3 train_lightgbm.py
```

或者用 Docker：

```bash
docker compose run --rm --entrypoint python data-prep train_lightgbm.py
```

默认会输出到：

```bash
quant_data/models/lightgbm_model.txt
quant_data/models/feature_importance.csv
quant_data/models/training_metadata.json
quant_data/models/inference_scores_latest.parquet
```

## 严格 OOS 回测

做 expanding-window 的 walk-forward 历史回测：

```bash
python3 backtest_walk_forward.py
```

或者用 Docker：

```bash
docker compose run --rm --entrypoint python data-prep backtest_walk_forward.py
```

默认输出到：

```bash
quant_data/backtests/summary.json
quant_data/backtests/equity_curve.parquet
quant_data/backtests/trade_log.parquet
quant_data/backtests/oos_predictions.parquet
```

如果你希望管理面板能看到 step 3 到 step 6 的稳定容器名、PID 和日志文件，建议用这些 runner：

```bash
bash run_step3_feature_engineering.sh
bash run_step4_inference_features.sh
bash run_step5_train_score.sh
bash run_step6_backtest.sh
```

这些脚本会把日志写到 `logs/step*_*.log`，并把当前容器 ID / logger PID 写到 `run/*.pid`，管理面板的 live monitor 会优先读取这些运行时信息。

如果你要单独执行 workflow step 6，并且保留独立日志，直接用：

```bash
bash run_step6_backtest.sh
```

关键文件：

```bash
logs/step6_backtest_*.log
run/step6_backtest.pid
run/step6_backtest_logger.pid
```

## Futu Gateway 自动模拟交易

现在多了一层“策略自动执行”，但它不会自己实现券商接口，而是直接接你已经有的 Futu gateway。

职责拆分如下：

- `train_lightgbm.py` 继续负责产出 `quant_data/models/inference_scores_latest.parquet`
- `paper_trade_futu.py` 读取最新 score snapshot，生成目标持仓，并通过 Futu gateway 下模拟单
- `paper_trade_daemon.py` 常驻监看 score 文件变化；如果 snapshot 没变就 noop，变了才做新的 rebalance
- `quant_data/paper_trading/` 保存本地状态、目标持仓快照与同步历史

启动自动模拟交易 daemon：

```bash
bash run_paper_trading_daemon.sh
```

关键文件：

```bash
logs/paper_trading_daemon_*.log
run/paper_trading_daemon.pid
quant_data/paper_trading/state.json
quant_data/paper_trading/targets_latest.parquet
quant_data/paper_trading/sync_history.jsonl
```

默认会尝试连接：

```bash
http://127.0.0.1:8080
```

如果你要覆盖 gateway 或策略参数，先复制 `run/panel.env.example` 为本地 `run/panel.env`，再把这些环境变量写进去后启动 panel / daemon：

```bash
FUTU_GATEWAY_BASE_URL=http://127.0.0.1:8080
FUTU_GATEWAY_MARKET=CN
FUTU_GATEWAY_AGENT_ID=aistockcn-paper-cn
FUTU_GATEWAY_AGENT_KEY=local-dev-agent-key
FUTU_GATEWAY_ACCOUNT_ID=
PAPER_TRADING_TOP_K=5
PAPER_TRADING_MIN_SCORE=0.5
PAPER_TRADING_LOT_SIZE=100
PAPER_TRADING_CASH_BUFFER_PCT=0.02
PAPER_TRADING_BUY_LIMIT_BPS=50
PAPER_TRADING_SELL_LIMIT_BPS=50
PAPER_TRADING_BUDGET_TOTAL=
PAPER_TRADING_INTERVAL_SECONDS=300
PAPER_TRADING_MAX_ORDER_QTY=1000
```

## 全自动 Batch

如果你要在服务器上长期挂机跑全市场 3 年数据，直接用：

```bash
bash run_a_share_3y_batch.sh
```

这个脚本就是固定用途：

- 只跑 A 股
- 只跑最近 3 年窗口
- 自动后台运行
- 自动断点续跑

底层会调用：

```bash
bash run_full_market_3y_batch.sh
```

它会自动做这些事：

- 构建容器
- 启动全市场批量下载
- 写入后台日志
- 写入 PID 文件
- 写入断点续跑状态文件
- 默认复用已有行业信息，并只为新股或缺失行业信息的股票补查 `industry`
- 多轮重试失败股票
- 定期重新登录 Baostock

关键文件：

```bash
logs/full_market_3y_*.log
run/full_market_3y.pid
run/full_market_3y_logger.pid
quant_data/batch_state/all_a_3y_state.json
```

## 控制台 Panel

项目现在带了一个最小可用的观测面板骨架：

- `apps/api/`: FastAPI，只读暴露 batch、log、数据摘要、模型结果
- `apps/web/`: Next.js 控制台

启动方式：

```bash
docker compose up -d panel-api panel-web
```

访问地址：

- 控制台: `http://localhost:3030`
- API: `http://localhost:8001`

当前第一版页面：

- `Overview`
- `Batch`
- `Data`
- `Models`
- `Picks`
- `Paper`

现在 `Paper` 页会把：

- Futu gateway 健康状态
- auto paper trading daemon 状态
- 最新目标持仓
- gateway agent 的持仓 / 委托
- 最近同步历史

放到同一个控制面板里。

## Panel 登录

首页 `/` 现在是登录页，成功后会进入 `/overview`。

公开仓库里只保留样例配置：

```bash
run/panel.env.example
run/panel_users.example.json
```

本地部署前先复制一份真实运行时文件：

```bash
cp run/panel.env.example run/panel.env
cp run/panel_users.example.json run/panel_users.json
```

然后把 `run/panel.env` / `run/panel_users.json` 里的用户名、密码、session secret、admin key 都改成你自己的值，再重新启动：

```bash
docker compose up -d panel-web
```

查看进度：

```bash
tail -f logs/full_market_3y_*.log
```

默认参数可以通过环境变量覆盖，例如：

```bash
START_DATE=20230322 END_DATE=20260322 OVERWRITE=1 bash run_full_market_3y_batch.sh
```
