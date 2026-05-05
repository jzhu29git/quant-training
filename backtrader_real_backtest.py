import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import pandas as pd
from datetime import datetime

# ── 策略 ──
class SmaCrossWithStop(bt.Strategy):
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
        ('stop_loss', 0.05),
    )

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.params.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.params.slow_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.order = None
        self.entry_price = None

    def log(self, txt):
        dt = self.data.datetime.date()
        print(f'{dt}  {txt}')

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.log(f'买入 @ {order.executed.price:.2f}')
            else:
                self.log(f'卖出 @ {order.executed.price:.2f}')
        self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.crossover > 0:
                self.order = self.buy()
                self.log(f'金叉信号 -> 买入开仓')
        else:
            if self.entry_price:
                pct = (self.data.close[0] - self.entry_price) / self.entry_price
                if pct <= -self.params.stop_loss:
                    self.order = self.sell()
                    self.log(f'止损触发 ({pct*100:.1f}%) -> 卖出')
                    return
            if self.crossover < 0:
                self.order = self.sell()
                self.log(f'死叉信号 -> 平仓卖出')


# ── 下载 A 股数据 ──
print('下载 A 股沪深300 历史数据...')
import akshare as ak
# 用沪深300指数作为示例
df = ak.stock_zh_index_daily(symbol="sh000300")
df.index = pd.to_datetime(df['date'])
df = df.sort_index()

# 取最近 5 年
df = df[df.index >= '2020-01-01']
print(f'  共 {len(df)} 条日线 ({df.index[0].date()} ~ {df.index[-1].date()})')

# 列名标准化: low -> low, close -> close, etc.
df = df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'})

# ── 回测 ──
data = bt.feeds.PandasData(dataname=df)

cerebro = bt.Cerebro(stdstats=False)
cerebro.adddata(data)
cerebro.addstrategy(SmaCrossWithStop, fast_period=10, slow_period=30, stop_loss=0.05)

cerebro.broker.setcash(100_000.0)
cerebro.broker.setcommission(commission=0.0003)  # A股佣金万三

start_val = cerebro.broker.getvalue()
print(f'初始资金: {start_val:,.2f}')

cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

print('运行回测...')
results = cerebro.run()

end_val = cerebro.broker.getvalue()
total_return = (end_val / start_val - 1) * 100
print(f'最终资金: {end_val:,.2f}')
print(f'总收益率: {total_return:.2f}%')

strat = results[0]
ret = strat.analyzers.returns.get_analysis()
sharpe = strat.analyzers.sharpe.get_analysis()
dd = strat.analyzers.drawdown.get_analysis()

if 'rtot' in ret:
    print(f'累计收益率: {ret["rtot"]*100:.2f}%')
if 'rnorm100' in ret:
    print(f'年化收益率: {ret["rnorm100"]:.2f}%')
if 'sharperatio' in sharpe:
    print(f'夏普比率: {sharpe["sharperatio"]:.2f}')
if 'max' in dd:
    print(f'最大回撤: {dd["max"]["drawdown"]:.2f}%')

trades = strat.analyzers.trades.get_analysis()
total_closed = trades.get('total', {}).get('closed', 0)
won = trades.get('won', {}).get('total', 0)
lost = trades.get('lost', {}).get('total', 0)
print(f'交易次数: {total_closed}  (赢: {won} / 亏: {lost})')
if won + lost > 0:
    print(f'胜率: {won / (won + lost) * 100:.1f}%')

# 画图
print('\n保存收益曲线图...')
fig = cerebro.plot(style='candlestick', iplot=False, volume=False)[0][0]
fig.savefig('backtest_result.png', dpi=150, bbox_inches='tight')
print('已保存: backtest_result.png')
