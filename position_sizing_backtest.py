"""
仓位管理对比回测 — 沪深300 双均线策略，5种仓位模型
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import pandas as pd
import akshare as ak
from datetime import datetime

# ── 数据源 ──
def get_data(symbol='sh000300', start='2020-01-01', end='2026-04-30'):
    df = ak.stock_zh_index_daily(symbol)
    df.index = pd.to_datetime(df['date'])
    df = df.sort_index()
    df = df.loc[start:end]
    df.rename(columns={'open':'open','high':'high','low':'low','close':'close','volume':'volume'}, inplace=True)
    df = df[['open','high','low','close','volume']]
    return df

# ── Base 策略（全仓进出） ──
class BaseStrategy(bt.Strategy):
    params = (('fast',10),('slow',30))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.params.fast)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.order = None

    def next(self):
        if self.order: return
        if self.crossover > 0 and not self.position:
            self.order = self.buy()
        elif self.crossover < 0 and self.position:
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None

# ── 固定比例仓位 ──
class FixedPctStrategy(bt.Strategy):
    params = (('fast',10),('slow',30),('pct',0.25))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.params.fast)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.order = None

    def next(self):
        if self.order: return
        if self.crossover > 0 and self.position.size == 0:
            cash = self.broker.getcash()
            target_val = min(cash, self.broker.getvalue() * self.params.pct)
            size = int(target_val / self.data.close[0])
            if size > 0:
                self.order = self.buy(size=size)
        elif self.crossover < 0 and self.position.size > 0:
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None

# ── ATR 动态仓位 ──
# 逻辑：每次入场时，用总资金 × risk_pct 作为"能承受的亏损额"
# 除以 1 ATR 得到股数，保证如果亏 1 ATR，损失不超过 risk_pct
class ATRStrategy(bt.Strategy):
    params = (('fast',10),('slow',30),('atr_period',14),('risk_pct',0.02))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.params.fast)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.order = None

    def next(self):
        if self.order: return
        if self.crossover > 0 and not self.position:
            atr_val = self.atr[0]
            price = self.data.close[0]
            total_risk = self.broker.getvalue() * self.params.risk_pct
            # 只按现金可购买的数量来限制
            cash = self.broker.getcash()
            # 根据 risk 计算目标股数
            size = int(total_risk / atr_val) if atr_val > 0 else 0
            if size > 0:
                # 确保不超过现金能买的
                max_by_cash = int(cash / price)
                size = min(size, max_by_cash)
            if size > 0:
                self.order = self.buy(size=size)
        elif self.crossover < 0 and self.position:
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None

# ── 回测引擎 ──
def run_backtest(strategy_cls, data_df, strategy_name, cash=100000, commission=0.0003, **kwargs):
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    data_feed = bt.feeds.PandasData(dataname=data_df)
    cerebro.adddata(data_feed)
    cerebro.addstrategy(strategy_cls, **kwargs)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name='sharpe', riskfreerate=0.02, annualize=True, timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    returns = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    final_val = cerebro.broker.getvalue()
    total_return = (final_val / cash - 1) * 100

    trade_count = trades.get('total', {}).get('total', 0) if isinstance(trades, dict) else 0
    won = trades.get('won', {}).get('total', 0) if isinstance(trades, dict) else 0
    lost = trades.get('lost', {}).get('total', 0) if isinstance(trades, dict) else 0
    win_rate = (won / trade_count * 100) if trade_count > 0 else 0

    print(f"\n{'='*50}")
    print(f"  {strategy_name}")
    print(f"{'='*50}")
    print(f"  最终资产：{final_val:>10,.2f}")
    print(f"  总收益率：{total_return:>6.2f}%")
    print(f"  年化收益：{returns.get('rnorm100', 0):>6.2f}%")
    sr = sharpe.get('sharperatio', None)
    print(f"  夏普比率：{sr:.4f}" if sr is not None else "  夏普比率：N/A")
    print(f"  最大回撤：{dd.get('max', {}).get('drawdown', 0):>6.2f}%")
    print(f"  交易次数：{trade_count}")
    print(f"  胜率：{win_rate:>5.1f}%")
    print(f"  盈利次数：{won}  亏损次数：{lost}")
    return {'name': strategy_name, 'final': final_val, 'return_pct': total_return,
            'sharpe': sr if sr is not None else 0, 'max_dd': dd.get('max', {}).get('drawdown', 0),
            'trades': trade_count, 'win_rate': win_rate}

# ── 主程序 ──
if __name__ == '__main__':
    import sys
    # 支持命令行参数：python script.py --cash 5000000 --large-test
    large_test = '--large-test' in sys.argv

    print("正在下载沪深300数据...")
    df = get_data()
    print(f"数据范围：{df.index[0].date()} ~ {df.index[-1].date()}，共 {len(df)} 个交易日")

    if large_test:
        cash = 5_000_000  # 500万起
        print(f"\n╔══════════════════════════════════════════════╗")
        print(f"║      大资金 ATR 梯度测试（初始 {cash/10000:.0f}万）       ║")
        print(f"╚══════════════════════════════════════════════╝")

        # 对比基准（100万，全仓）
        results = []
        r = run_backtest(BaseStrategy, df, "基准：全仓进出", cash=cash)
        results.append(r)

        # ATR 梯度：2%, 5%, 10%, 20%, 50%
        atr_risks = [0.02, 0.05, 0.10, 0.20, 0.50]
        for rp in atr_risks:
            r = run_backtest(ATRStrategy, df, f"ATR 动态仓位（风险{rp*100:.0f}%）", cash=cash, risk_pct=rp)
            results.append(r)

        print(f"\n\n{'='*70}")
        print(f"  大资金（{cash/10000:.0f}万）ATR 梯度对比总结")
        print(f"{'='*70}")
        print(f"{'策略':<28} {'收益率':>8} {'夏普':>8} {'最大回撤':>8} {'交易次数':>8} {'胜率':>6}")
        print("-"*70)
        for r in results:
            sharpe_s = f"{r['sharpe']:.3f}" if r['sharpe'] != 0 else "N/A"
            print(f"{r['name']:<28} {r['return_pct']:>7.2f}% {sharpe_s:>8} {r['max_dd']:>7.2f}% {r['trades']:>8} {r['win_rate']:>5.1f}%")
    else:
        # 默认模式：100万对比 5 种仓位模型
        cash = 1_000_000
        results = []

        r = run_backtest(BaseStrategy, df, "基准：全仓进出", cash=cash)
        results.append(r)
        r = run_backtest(FixedPctStrategy, df, "固定比例 25%", cash=cash, pct=0.25)
        results.append(r)
        r = run_backtest(FixedPctStrategy, df, "固定比例 50%", cash=cash, pct=0.50)
        results.append(r)
        r = run_backtest(ATRStrategy, df, "ATR 动态仓位（风险2%）", cash=cash, risk_pct=0.02)
        results.append(r)
        r = run_backtest(ATRStrategy, df, "ATR 动态仓位（风险5%）", cash=cash, risk_pct=0.05)
        results.append(r)

        print(f"\n\n{'='*60}")
        print("  仓位管理对比总结（默认模式）")
        print(f"{'='*60}")
        print(f"{'策略':<24} {'收益率':>8} {'夏普':>8} {'最大回撤':>8} {'交易次数':>8} {'胜率':>6}")
        print("-"*64)
        for r in results:
            sharpe_s = f"{r['sharpe']:.3f}" if r['sharpe'] != 0 else "N/A"
            print(f"{r['name']:<24} {r['return_pct']:>7.2f}% {sharpe_s:>8} {r['max_dd']:>7.2f}% {r['trades']:>8} {r['win_rate']:>5.1f}%")
