"""
ATR 仓位管理深度分析 — 持仓过程、回撤归因、资金敏感性
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import pandas as pd
import numpy as np
import akshare as ak

# ── 数据 ──
def get_data(symbol='sh000300', start='2020-01-01', end='2026-04-30'):
    df = ak.stock_zh_index_daily(symbol)
    df.index = pd.to_datetime(df['date'])
    df = df.sort_index()
    df = df.loc[start:end]
    df.rename(columns={'open':'open','high':'high','low':'low','close':'close','volume':'volume'}, inplace=True)
    df = df[['open','high','low','close','volume']]
    return df

# ── 带日志的 ATR 策略 ──
class LoggingATR(bt.Strategy):
    params = (('fast',10),('slow',30),('atr_period',14),('risk_pct',0.02))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.params.fast)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.order = None
        self.daily_log = []

    def next(self):
        dt = self.data.datetime.date()
        price = self.data.close[0]
        cash = self.broker.getcash()
        val = self.broker.getvalue()
        pos_size = self.position.size
        pos_val = pos_size * price if pos_size > 0 else 0

        self.daily_log.append({
            'date': dt, 'price': price, 'cash': cash, 'value': val,
            'pos_size': pos_size, 'pos_value': pos_val,
            'atr14': self.atr[0], 'crossover': self.crossover[0],
            'exposure_pct': (pos_val / val * 100) if val > 0 else 0
        })

        if self.order: return

        if self.crossover > 0 and not self.position:
            atr_val = self.atr[0]
            total_risk = self.broker.getvalue() * self.params.risk_pct
            cash_avail = self.broker.getcash()
            size = int(total_risk / atr_val) if atr_val > 0 else 0
            max_by_cash = int(cash_avail / price)
            size = min(size, max_by_cash) if size > 0 else 0
            if size > 0:
                self.order = self.buy(size=size)

        elif self.crossover < 0 and self.position:
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None

    def stop(self):
        self.df_log = pd.DataFrame(self.daily_log)
        self.df_log.set_index('date', inplace=True)


def run_atr_log(data_df, cash=100000, risk_pct=0.02):
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0003)
    data = bt.feeds.PandasData(dataname=data_df)
    cerebro.adddata(data)
    cerebro.addstrategy(LoggingATR, risk_pct=risk_pct)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name='sharpe', riskfreerate=0.02, annualize=True, timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]
    log_df = strat.df_log
    final_val = cerebro.broker.getvalue()

    trades = strat.analyzers.trades.get_analysis()
    sharpe_r = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    dd = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()

    return {
        'log': log_df,
        'final': final_val,
        'sharpe': sharpe_r,
        'max_dd': dd.get('max', {}).get('drawdown', 0),
        'trades': trades,
        'returns': returns
    }


def analyze(log_df, label, cash):
    print(f"\n{'#'*60}")
    print(f"  {label}")
    print(f"{'#'*60}")

    # 1. 持仓天数占比
    in_pos = log_df[log_df['pos_size'] > 0]
    out_pos = log_df[log_df['pos_size'] == 0]
    total_days = len(log_df)
    in_days = len(in_pos)
    print(f"\n📊 持仓统计")
    print(f"  总交易日：{total_days}")
    print(f"  持仓日：{in_days}（{in_days/total_days*100:.1f}%）")
    print(f"  空仓日：{total_days - in_days}（{(total_days-in_days)/total_days*100:.1f}%）")

    if len(in_pos) > 0:
        print(f"  持仓日平均敞口：{in_pos['exposure_pct'].mean():.1f}%")
        print(f"  持仓日最大敞口：{in_pos['exposure_pct'].max():.1f}%")
        print(f"  持仓日最小敞口：{in_pos['exposure_pct'].min():.1f}%")

    # 2. 各笔交易详情
    log_df2 = log_df.copy()
    log_df2['signal'] = 0
    log_df2['prev_pos'] = log_df2['pos_size'].shift(1).fillna(0)
    log_df2.loc[(log_df2['prev_pos'] == 0) & (log_df2['pos_size'] > 0), 'signal'] = 1
    log_df2.loc[(log_df2['prev_pos'] > 0) & (log_df2['pos_size'] == 0), 'signal'] = -1

    entries = log_df2[log_df2['signal'] == 1]
    exits = log_df2[log_df2['signal'] == -1]

    trades_list = []
    for i in range(min(len(entries), len(exits))):
        buy_row = entries.iloc[i]
        sell_row = exits.iloc[i]
        ret = (sell_row['price'] - buy_row['price']) / buy_row['price'] * 100
        trades_list.append({
            'entry': str(buy_row.name), 'exit': str(sell_row.name),
            'entry_price': buy_row['price'], 'exit_price': sell_row['price'],
            'return': round(ret, 2), 'buy_val': round(buy_row['pos_value'], 0),
            'atr_at_entry': round(buy_row['atr14'], 1)
        })

    df_trades = pd.DataFrame(trades_list)
    if len(df_trades) > 0:
        print(f"\n📈 逐笔交易分析（{len(df_trades)} 笔）")
        wins = df_trades[df_trades['return'] > 0]
        losses = df_trades[df_trades['return'] <= 0]
        print(f"  盈利笔数：{len(wins)}  亏损笔数：{len(losses)}")
        print(f"  平均单笔收益率：{df_trades['return'].mean():.2f}%")
        print(f"  单笔最大盈利：{df_trades['return'].max():.2f}%")
        print(f"  单笔最大亏损：{df_trades['return'].min():.2f}%")
        win_rate = len(wins) / len(df_trades) * 100
        avg_win = wins['return'].mean() if len(wins) > 0 else 0
        avg_loss = losses['return'].mean() if len(losses) > 0 else 0
        print(f"  胜率：{win_rate:.1f}%")
        print(f"  平均盈利：{avg_win:.2f}%  平均亏损：{avg_loss:.2f}%")
        if avg_loss != 0:
            print(f"  盈亏比：{abs(avg_win/avg_loss):.2f}")

        # 入场时ATR与购买力
        print(f"\n💰 入场时ATR与购买力分析")
        print(f"  平均 ATR 入场：{df_trades['atr_at_entry'].mean():.1f}")
        avg_buy_val = df_trades['buy_val'].mean()
        print(f"  平均买入金额：{avg_buy_val:,.0f}")
        print(f"  平均买入占资金比：{avg_buy_val/cash*100:.1f}%")

        # 详细列表（最近10笔）
        print(f"\n📋 最近10笔交易：")
        cols = ['entry','exit','return','buy_val','atr_at_entry']
        print(df_trades.tail(10)[cols].to_string(index=False))

    # 3. 最大回撤细节
    val_series = log_df['value']
    rolling_max = val_series.cummax()
    drawdowns = (val_series - rolling_max) / rolling_max * 100
    log_df['dd_pct'] = drawdowns
    max_dd_date = drawdowns.idxmin()
    print(f"\n📉 回撤分析")
    print(f"  最大回撤：{drawdowns.min():.2f}%")
    print(f"  最大回撤日期：{max_dd_date}")
    severe_dd = drawdowns[drawdowns < -10]
    if len(severe_dd) > 0:
        print(f"  回撤超过10%的天数：{len(severe_dd)}")
        severe_dd_periods = (severe_dd.index.to_series().diff() > pd.Timedelta(days=3)).cumsum()
        for period_id, group in severe_dd.groupby(severe_dd_periods):
            print(f"    {group.index[0]} ~ {group.index[-1]}  最大{group.min():.1f}%")


if __name__ == '__main__':
    print("下载沪深300数据...")
    df = get_data()
    print(f"数据：{df.index[0].date()} ~ {df.index[-1].date()}, {len(df)} 天")

    for cash in [100000, 500000, 1000000]:
        print(f"\n{'='*70}")
        print(f"  初始资金：{cash:>10,.0f}")
        print(f"{'='*70}")
        for risk_pct in [0.01, 0.02, 0.05]:
            result = run_atr_log(df, cash=cash, risk_pct=risk_pct)
            log = result['log']
            ret_pct = (result['final']/cash-1)*100
            label = f"ATR risk={risk_pct*100:.0f}%  |  终值={result['final']:>10,.0f}  收益={ret_pct:>5.1f}%"
            if result['sharpe']:
                label += f"  夏普={result['sharpe']:.3f}"
            label += f"  最大回撤={result['max_dd']:.1f}%"
            analyze(log, label, cash)

    print("\n\n✅ 分析完成")
