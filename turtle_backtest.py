"""
Phase 1 专题3：海龟交易法则（简化版）回测
— 单品种沪深300，唐奇安通道突破入场，ATR止损，ATR仓位管理

信号逻辑（先写后写代码，已验证）：
- 入场：收盘价突破过去 N 日最高价（唐奇安通道上轨）且空仓 → buy
- 止损：持仓中，收盘价跌破过去 N 日最低价（唐奇安通道下轨）→ close
- 仓位：size = (cash * risk_pct) / ATR  （海龟原版ATR控仓位）
- 可选：突破入场时用 ATR 做跟踪止损

目标：
1. 交易频率比双均线/多指标方案更高，适合验证 ATR 仓位管理
2. 对比全仓 vs ATR 不同风险参数
3. 探索海龟在沪深300上的适用性
"""
import sys, io, os, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime

CACHE_FILE = os.path.join(os.path.dirname(__file__), 'sh000300_cache.pkl')

def get_data(start='2020-01-01', end='2026-05-04'):
    if os.path.exists(CACHE_FILE):
        print(f"📦 从本地缓存读取：{CACHE_FILE}")
        df = pd.read_pickle(CACHE_FILE)
        df = df.loc[start:end]
        print(f"数据范围：{df.index[0].date()} ~ {df.index[-1].date()}，共 {len(df)} 个交易日")
        return df
    import akshare as ak
    print("⬇️ 从 akshare 下载数据...")
    df = ak.stock_zh_index_daily('sh000300')
    df.index = pd.to_datetime(df['date'])
    df = df.sort_index()
    df.to_pickle(CACHE_FILE)
    print(f"已缓存到 {CACHE_FILE}")
    df = df.loc[start:end]
    print(f"数据范围：{df.index[0].date()} ~ {df.index[-1].date()}，共 {len(df)} 个交易日")
    return df

# ════════════════════════════════════════
# 海龟策略（简化版 — 单品种、单唐奇安通道）
# ════════════════════════════════════════
class TurtleStrategy(bt.Strategy):
    """海龟交易法则（简化版）

    入场：价格突破过去 N 日最高价（唐奇安通道上轨）且空仓
    止损（硬止损）：价格跌破过去 N 日最低价（唐奇安通道下轨）
    止损（跟踪止损，可选）：入场后从最高收盘价回撤 2 * ATR
    仓位：ATR 风险比例控制
    """
    params = (
        ('period', 20),          # 唐奇安通道周期（海龟原版入场=20，止损=10）
        ('risk_pct', None),       # ATR 风险比例，None=全仓
        ('use_trailing_stop', False),  # 是否启用跟踪止损
        ('trailing_atr_mult', 2),      # 跟踪止损 ATR 倍数
    )

    def __init__(self):
        # 唐奇安通道 — 用 shift(1) 取前一日值，避免用到当日数据
        self.donchian_high = bt.indicators.Highest(self.data.high, period=self.params.period)(-1)
        self.donchian_low = bt.indicators.Lowest(self.data.low, period=self.params.period)(-1)

        # ATR
        self.atr = bt.indicators.ATR(self.data, period=14)

        # 跟踪止损跟踪变量
        self.entry_bar = 0
        self.entry_price = 0
        self.highest_since_entry = 0
        self.order = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            pnl = trade.pnlcomm
            bars = trade.barlen
            self.log(f'平仓 | 盈亏: {pnl:.2f} | 持仓天数: {bars}')

    def next(self):
        if self.order:
            return

        price = self.data.close[0]
        atr_val = self.atr[0]
        ln = len(self)

        if not self.position:
            # ── 入场：收盘价突破前一日唐奇安通道上轨 ──
            if price > self.donchian_high[0]:
                cash = self.broker.get_cash()
                if self.params.risk_pct is not None and atr_val > 0:
                    total_risk = cash * self.params.risk_pct
                    size = max(1, int(total_risk / atr_val))
                else:
                    size = int(cash / price)

                # 防止 ATR size 超出可用现金
                cost = size * price
                max_size = int(cash * 0.95 / price)  # 留5% buffer
                if size > max_size:
                    size = max_size
                    cost = size * price

                self.order = self.buy(size=size)
                self.entry_bar = ln
                self.entry_price = price
                self.highest_since_entry = price
                pct = cost / cash * 100 if cash > 0 else 0
                self.log(f'买入 🟢 | 价格: {price:.2f} | ATR: {atr_val:.2f} | 数量: {size} | 占用: {cost:.0f}({pct:.1f}%)')

        else:
            # 更新持仓期间的最高价（用于跟踪止损）
            if price > self.highest_since_entry:
                self.highest_since_entry = price

            # ── 止损条件 ──
            # 条件1：硬止损 — 收盘价跌破前一日唐奇安通道下轨
            stop1 = price < self.donchian_low[0]

            # 条件2（可选）：跟踪止损
            if self.params.use_trailing_stop and atr_val > 0:
                trail_level = self.highest_since_entry - atr_val * self.params.trailing_atr_mult
                stop2 = price < trail_level
            else:
                stop2 = False

            if stop1 or stop2:
                reason = '硬止损(通道下轨)' if stop1 else '跟踪止损'
                self.order = self.close()
                self.log(f'卖出 🔴 | {reason} | 价格: {price:.2f} | 持仓最高: {self.highest_since_entry:.2f}')


# ════════════════════════════════════════
# 回测运行器
# ════════════════════════════════════════
def run_backtest(strategy_params, cash=100000, commission=0.0003):
    cerebro = bt.Cerebro()
    df = get_data()
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    cerebro.addstrategy(TurtleStrategy, **strategy_params)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    # 分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

    print(f"\n{'='*70}")
    print(f"🚀 海龟策略回测 | 参数: {strategy_params} | 初始资金: {cash}")
    print(f"{'='*70}")

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

    sharpe_val = sharpe.get('sharperatio', pd.NA)

    won = trades.get('won', {})
    lost = trades.get('lost', {})
    total_trades = won.get('total', 0) + lost.get('total', 0)
    win_rate = won.get('total', 0) / total_trades * 100 if total_trades > 0 else 0

    max_dd = dd.get('max', {}).get('drawdown', 0)
    print(f"\n📊 结果汇总")
    print(f"  总收益率: {total_return:.2f}%")
    print(f"  夏普比率: {sharpe_val if pd.notna(sharpe_val) else 'N/A'}")
    print(f"  最大回撤: {max_dd:.2f}%")
    print(f"  交易次数: {total_trades}")
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  SQN: {sqn.get('sqn', 'N/A')}")

    if total_trades > 0:
        print(f"  盈利交易: {won.get('total',0)} | 亏损交易: {lost.get('total',0)}")
        avg_win = won.get('pnl', {}).get('average', 0)
        avg_loss = lost.get('pnl', {}).get('average', 0)
        print(f"  平均盈利: {avg_win:.2f} | 平均亏损: {avg_loss:.2f}")
        print(f"  盈亏比: {abs(avg_win/avg_loss) if avg_loss != 0 else 'N/A'}")
        max_won = won.get('pnl', {}).get('max', 0)
        max_lost = lost.get('pnl', {}).get('max', 0)
        print(f"  最大盈利: {max_won:.2f} | 最大亏损: {max_lost:.2f}")
        avg_bars = won.get('barlen', {}).get('average', 0)
        print(f"  平均持仓天数(盈利): {avg_bars:.1f}")

    print(f"  最终资金: {cerebro.broker.getvalue():.2f}")

    return {
        'total_return': total_return,
        'sharpe': sharpe_val,
        'max_drawdown': max_dd,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'sqn': sqn.get('sqn', 'N/A'),
    }


# ════════════════════════════════════════
# 入口
# ════════════════════════════════════════
if __name__ == '__main__':
    # ── 方案 A：海龟全仓（仅唐奇安通道突破，无仓位管理） ──
    run_backtest({'risk_pct': None}, cash=100000)

    # ── 方案 B：海龟 + ATR 仓位管理 (1%/2%/5%) ──
    for risk_pct in [0.01, 0.02, 0.05]:
        run_backtest({'risk_pct': risk_pct}, cash=100000)

    # ── 方案 C：海龟 + ATR 仓位 + 跟踪止损 ──
    run_backtest({'risk_pct': 0.02, 'use_trailing_stop': True, 'trailing_atr_mult': 2.5}, cash=100000)

    print("\n✅ 全部回测完成")
