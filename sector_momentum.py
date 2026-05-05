"""
Phase 1 专题4：行业ETF动量策略 — 修复版
— 中证6个行业指数，月度动量轮动

信号逻辑（纯文本，写代码前确认）：
- 买入条件：本月最后交易日，过去N个月收益率排名前K
- 卖出条件：本月最后交易日，动量排名掉出前K → 被轮出
- 持仓：TopK内等权
- 对比基准1：等权持有所有行业（月再平衡）
- 对比基准2：沪深300买入持有
"""
import sys, io, os, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import akshare as ak

# ════════════════════════════════════════
# 数据源
# ════════════════════════════════════════
SECTOR_CODES = {
    '000986': '能源',
    '000987': '材料',
    '000989': '可选消费',
    '000991': '医药',
    '000992': '金融',
    '000993': '信息技术',
}
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'sector_cache')

def ensure_sector_cache():
    """下载并缓存所有行业指数数据"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    for code, name in SECTOR_CODES.items():
        cache_file = os.path.join(CACHE_DIR, f'{code}.pkl')
        if os.path.exists(cache_file):
            print(f'  ✅ {name}({code}) 已缓存')
        else:
            print(f'  ⬇️ 下载 {name}({code})...')
            df = ak.stock_zh_index_daily(f'sh{code}')
            print(f'     {len(df)} 行, {df["date"].iloc[0]} ~ {df["date"].iloc[-1]}')
            df.to_pickle(cache_file)

def load_all_sectors(start='2020-01-01', end='2026-05-04'):
    """加载所有行业数据为 dict {code: DataFrame}"""
    ensure_sector_cache()
    result = {}
    for code, name in SECTOR_CODES.items():
        cache_file = os.path.join(CACHE_DIR, f'{code}.pkl')
        df = pd.read_pickle(cache_file)
        df.index = pd.to_datetime(df['date'])
        df = df.sort_index()
        df = df.loc[start:end]
        df = df[['open', 'high', 'low', 'close', 'volume']]
        result[code] = df
    return result

# ════════════════════════════════════════
# Backtrader 行业动量策略 ✅ 修复版
# ════════════════════════════════════════
class SectorMomentumStrategy(bt.Strategy):
    """行业动量轮动策略

    每月末（最后1~2个交易日）判断：
    1. 用过去M个月的区间计算收益率
    2. 取TopK做多，等权分配
    3. 其他行业平仓
    """
    params = (
        ('momentum_months', 6),
        ('topk', 3),
    )

    def __init__(self):
        self.order = None
        self.trade_log = []
        # 记录上一次调仓的目标行业索引，用于检测变动
        self.prev_targets = set()
        # 记录当前月份，用于检测月份变化
        self.current_month = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Rejected]:
            self.order = None

    def next(self):
        if self.order:
            return

        ln = len(self)
        current_date = self.datas[0].datetime.date(0)

        # ── 每月仅调仓一次：检测月份发生变化 → 在新月份第一根bar触发上月信号 ──
        # 注：这样的好处是只用[0]bar来判断，不受数据缺口影响
        if self.current_month is None:
            self.current_month = current_date.month
            return

        if current_date.month == self.current_month:
            return  # 同一月，不做任何事

        # 月份变化了！先更新月份，再执行调仓
        self.current_month = current_date.month
        n_datas = len(self.datas)
        lookback_days = self.params.momentum_months * 21

        if ln < lookback_days:
            return

        # ── 计算动量：用前一月的末值 vs lookback 前的末值 ──
        # 由于今天是新月的第1根bar，close[-1]是上月最后一日收盘价
        momentum_scores = []
        for i in range(n_datas):
            d = self.datas[i]
            if ln < lookback_days + 1:
                continue
            old_close = d.close[-lookback_days - 1]  # 起点价格
            new_close = d.close[-1]                    # 上月最后价格
            if old_close != 0:
                ret = (new_close / old_close - 1) * 100
            else:
                ret = 0
            code = list(SECTOR_CODES.keys())[i]
            momentum_scores.append((i, ret, SECTOR_CODES[code]))

        if len(momentum_scores) < self.params.topk:
            return

        # 排序
        momentum_scores.sort(key=lambda x: -x[1])
        topk_indices = [x[0] for x in momentum_scores[:self.params.topk]]
        topk_names = [x[2] for x in momentum_scores[:self.params.topk]]
        new_targets = set(topk_indices)

        # 如果和上次没有变化，跳过
        if new_targets == self.prev_targets:
            return

        # 有变化，打印一行摘要
        scored_str = ', '.join(f'{x[2]}:{x[1]:+.1f}%' for x in momentum_scores[:self.params.topk])
        self.log(f'调仓 | Top{self.params.topk}: {topk_names} | {scored_str}')

        # ── 卖出不再是目标的 ──
        sell_inds = self.prev_targets - new_targets
        for i in sell_inds:
            pos = self.getposition(self.datas[i])
            if pos.size > 0:
                self.order = self.close(self.datas[i])

        # ── 买入新目标 ──
        cash = self.broker.get_cash()
        target_per_sector = cash / self.params.topk

        for idx in topk_indices:
            pos = self.getposition(self.datas[idx])
            price = self.datas[idx].close[0]
            size = int(target_per_sector / price)

            if pos.size == 0 and size > 0:
                self.order = self.buy(self.datas[idx], size=size)

        self.prev_targets = new_targets


# ════════════════════════════════════════
# 回测运行器
# ════════════════════════════════════════
def run_momentum_backtest(strategy_params, cash=100000, commission=0.0003, verbose=False):
    cerebro = bt.Cerebro()

    sectors = load_all_sectors()

    for code, df in sectors.items():
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data, name=SECTOR_CODES[code])

    cerebro.addstrategy(SectorMomentumStrategy, **strategy_params)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

    n_sectors = len(sectors)
    label = f'mom={strategy_params["momentum_months"]}m_top{strategy_params["topk"]}'
    print(f"\n{'─'*55}")
    print(f"  🚀 行业动量 | {label}  ", flush=True)

    results = cerebro.run()
    strat = results[0]
    ret = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()

    total_return = ret.get('rtot', pd.NA)
    if pd.notna(total_return):
        total_return = total_return * 100

    ann_return = ret.get('rnorm100', pd.NA)
    if pd.notna(ann_return):
        ann_return = float(ann_return)

    sharpe_val = sharpe.get('sharperatio', pd.NA)
    if pd.notna(sharpe_val):
        sharpe_val = float(sharpe_val)

    won = trades.get('won', {})
    lost = trades.get('lost', {})
    total_trades = won.get('total', 0) + lost.get('total', 0)
    win_rate = won.get('total', 0) / total_trades * 100 if total_trades > 0 else 0

    max_dd = dd.get('max', {}).get('drawdown', 0)
    final_val = cerebro.broker.getvalue()

    print(f"    收益: {total_return:+.2f}%  年化: {ann_return:.2f}%  "
          f"回撤: {max_dd:.1f}%")
    print(f"    夏普: {sharpe_val:.2f}  交易: {total_trades}  胜率: {win_rate:.1f}%  "
          f"SQN: {sqn.get('sqn', 'N/A')}")
    print(f"    最终: {final_val:,.0f}")

    return {
        'label': label,
        'total_return': total_return,
        'annual_return': ann_return,
        'sharpe': sharpe_val,
        'max_drawdown': max_dd,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'sqn': sqn.get('sqn', 'N/A'),
        'final_value': final_val,
    }


# ════════════════════════════════════════
# 基准计算
# ════════════════════════════════════════
def calc_benchmark(cash=100000):
    """等权持有所有行业，每月再平衡"""
    sectors = load_all_sectors()

    prices = {}
    for code, df in sectors.items():
        prices[code] = df['close']

    price_df = pd.DataFrame(prices).dropna()
    price_df = price_df.loc['2020-01-01':'2026-04-30']

    # pandas future proof: use 'ME' instead of 'M'
    monthly = price_df.resample('ME').last().dropna()

    weights = np.ones(len(sectors)) / len(sectors)
    cash_history = [cash]

    for i in range(1, len(monthly)):
        rets = (monthly.iloc[i].values / monthly.iloc[i-1].values) - 1
        port_ret = np.dot(weights, rets)
        cash_history.append(cash_history[-1] * (1 + port_ret))

    final = cash_history[-1]
    total_ret = (final / cash - 1) * 100
    years = (price_df.index[-1] - price_df.index[0]).days / 365.25
    annualized = ((final / cash) ** (1/years) - 1) * 100

    print(f"\n{'─'*55}")
    print(f"  📊 基准: 行业等权（月再平衡）")
    print(f"    收益: {total_ret:+.2f}%  年化: {annualized:.2f}%  最终: {final:,.0f}")

    return {'total_return': total_ret, 'annual_return': annualized, 'final_value': final}


def calc_benchmark_hs300():
    """沪深300买入持有"""
    df300 = pd.read_pickle('sh000300_cache.pkl')
    df300.index = pd.to_datetime(df300.index)
    df300 = df300.sort_index()
    df300 = df300.loc['2020-01-01':'2026-04-30']

    start_p = df300['close'].iloc[0]
    end_p = df300['close'].iloc[-1]
    total_ret = (end_p / start_p - 1) * 100
    years = (df300.index[-1] - df300.index[0]).days / 365.25
    annualized = ((end_p / start_p) ** (1/years) - 1) * 100

    print(f"  📊 基准: 沪深300买入持有")
    print(f"    收益: {total_ret:+.2f}%  年化: {annualized:.2f}%")

    return {'total_return': total_ret, 'annual_return': annualized}


# ════════════════════════════════════════
# 入口
# ════════════════════════════════════════
if __name__ == '__main__':
    print(f"{'='*55}")
    print("  📥 行业动量回测 — 2020 ~ 2026")
    print(f"{'='*55}")

    # 基准
    bench_eq = calc_benchmark()
    bench_hs300 = calc_benchmark_hs300()

    # 动量策略组合
    configs = [
        {'momentum_months': 3, 'topk': 3},
        {'momentum_months': 6, 'topk': 3},
        {'momentum_months': 12, 'topk': 3},
        {'momentum_months': 6, 'topk': 5},
        {'momentum_months': 6, 'topk': 2},
    ]

    results = []
    for cfg in configs:
        r = run_momentum_backtest(cfg)
        results.append(r)

    # ── 汇总表格 ──
    print(f"\n{'='*55}")
    print("  📋 最终对比")
    print(f"{'='*55}")
    header = f"{'策略':<30} {'总收益':>8} {'年化':>8} {'回撤':>7} {'夏普':>6} {'交易':>5} {'胜率':>6} {'最终':>10}"
    print(header)
    print('─' * 55)

    print(f"{'沪深300买入持有':<30} {bench_hs300['total_return']:>+7.2f}% {bench_hs300['annual_return']:>6.2f}% {'N/A':>7} {'N/A':>6} {'N/A':>5} {'N/A':>6} {'N/A':>10}")
    print(f"{'行业等权（月再平衡）':<30} {bench_eq['total_return']:>+7.2f}% {bench_eq['annual_return']:>6.2f}% {'N/A':>7} {'N/A':>6} {'N/A':>5} {'N/A':>6} {bench_eq['final_value']:>10,.0f}")

    for r in results:
        print(f"{r['label']:<30} {r['total_return']:>+7.2f}% {r['annual_return']:>6.2f}% "
              f"{r['max_drawdown']:>6.1f}% {r['sharpe']:>5.2f} {r['total_trades']:>5} "
              f"{r['win_rate']:>5.1f}% {r['final_value']:>10,.0f}")

    print("\n✅ 全部回测完成")
