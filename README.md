# quant-training

A股量化训练与回测脚本仓库。

## 仓库里有什么

### 近期重点
- `stock_momentum_factor.py`
  - 中证500个股动量分层回测
  - 支持 3m / 6m / 12m 动量对比
  - 输出 Q1-Q5 分层表现、最大回撤、多空组合、图片
  - 已加入 sanity-check assertions，避免基准区间错位、净值/收益不一致等错误

### 主要输出文件
- `phase2_stock_momentum.png`
  - 三周期（3m/6m/12m）Q1-Q5净值曲线 + 多空统计图
- `phase2_stock_momentum_qcomparison.png`
  - 各Q在三周期下的对比图
- `latest_top10_picks.md`
  - 最新一期 Top10 动量选股名单

### 其他历史脚本
- `factor_layer_backtest.py`：因子分层回测
- `factor_ic_analysis.py`：IC / RankIC 分析
- `sector_momentum.py`：行业动量研究
- `multi_factor_backtest.py`：多因子组合回测
- `momentum_timing_analysis.py`：动量择时
- `position_sizing_backtest.py`：仓位管理相关回测

## 数据说明

本地缓存目录：

```txt
stock_cache/
```

里面是中证500成分股历史日线缓存（pkl）。

注意：
- 缓存数据 **没有推到 GitHub**
- 仓库里保存的是脚本、图片、说明文档
- 如果换一台电脑，需要重新下载数据，或者手动把 `stock_cache/` 拷过去

## 如何运行

在仓库目录下执行：

```bash
python stock_momentum_factor.py
```

运行后会：
1. 读取本地缓存数据
2. 计算 3m / 6m / 12m 动量因子
3. 做 Q1-Q5 分层回测
4. 输出最新 Top10 股票名单
5. 生成两张图片

## 当前研究结论（简版）

基于 2018-01 ~ 2026-04 的中证500样本：

- **6m 动量**：Q1 年化最高
- **12m 动量**：单调性更好、Q1 回撤更小，更适合当作研究因子
- **Q1纯多头** 比 **Q1-Q5多空** 更有现实意义
- A股环境下，多空组合统计上不显著，纯多头更值得继续研究

## GitHub 使用说明（给未来的自己）

### 当前状态
- 默认分支：`master`
- 已推送到 GitHub
- 如果 GitHub 页面看到 “Create pull request”，那只是 GitHub 的通用提示，**不是必须做的事情**

### 日常更新

```bash
git status
git add .
git commit -m "更新说明"
git push
```

### 下载仓库

首次下载：

```bash
git clone git@github.com:jzhu29git/quant-training.git
```

如果只想在网页上下载：
- 打开仓库页面
- 点击绿色按钮 **Code**
- 选择 **Download ZIP**

### 换电脑时要注意
如果要完整复现结果，除了下载 repo，还需要把本机的 `stock_cache/` 一起带走，或者重新下载历史数据。
