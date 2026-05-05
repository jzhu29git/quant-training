import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import pandas as pd
import akshare as ak
import time
import warnings
warnings.filterwarnings('ignore')

# =========================================
# 定点数版策略（固定买5手，而非全仓）
# =========================================
class SmaCrossFixed(bt.Strategy):
    params = (
        ('fast', 10),
        ('slow', 30),
        ('fixed_lots', 5),      # 每笔固定买 5 手（1手=100股）
    )
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.params.fast)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.order = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None

    def next(self):
        if self.order: return
        fixed_size = self.params.fixed_lots * 100  # 转成股数
        cash_needed = fixed_size * self.data.close[0]

        if not self.position and self.crossover > 0:
            # 有足够的现金才买
            if self.broker.getcash() >= cash_needed:
                self.order = self.buy(size=fixed_size)
        elif self.position and self.crossover < 0:
            self.order = self.sell(size=self.position.size)


def backtest_stock(code, name):
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                start_date="20200101", end_date="20260428",
                                adjust="qfq")
        if df is None or len(df) < 200:
            return None
        df.index = pd.to_datetime(df['日期'])
        df = df.rename(columns={'开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume'})
        df = df.sort_index()[['open','high','low','close','volume']]
        data = bt.feeds.PandasData(dataname=df)
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(data)
        cerebro.addstrategy(SmaCrossFixed)

        # 初始资金 2,000,000（200万）
        cerebro.broker.setcash(2_000_000.0)
        cerebro.broker.setcommission(commission=0.0003)

        cerebro.addanalyzer(bt.analyzers.Returns, _name='ret')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        start = cerebro.broker.getvalue()
        results = cerebro.run()
        end = cerebro.broker.getvalue()
        strat = results[0]

        dd_val = strat.analyzers.dd.get_analysis().get('max',{}).get('drawdown',0)
        trade_info = strat.analyzers.trades.get_analysis()
        total_trades = trade_info.get('total',{}).get('closed',0)
        won = trade_info.get('won',{}).get('total',0)

        return {
            'code': code,
            'name': name,
            'ret': (end/start-1)*100,
            'max_dd': dd_val,
            'trades': total_trades,
            'won': won,
        }
    except Exception as e:
        return None


stocks = [
    ('600036', '招商银行'), ('000001', '平安银行'),
    ('600519', '贵州茅台'), ('000858', '五粮液'), ('000568', '泸州老窖'),
    ('300750', '宁德时代'), ('002594', '比亚迪'),
    ('000725', '京东方'), ('002415', '海康威视'), ('000333', '美的集团'),
    ('300015', '爱尔眼科'), ('600276', '恒瑞医药'),
    ('601318', '中国平安'), ('600030', '中信证券'), ('600019', '宝钢股份'),
]

print(f'【固定手数版】双均线策略回测 {len(stocks)} 只股票 (2020~2026)')
print(f'策略: SMA {SmaCrossFixed.params.fast}/{SmaCrossFixed.params.slow} 金叉买/死叉卖')
print(f'仓位: 每笔固定 {SmaCrossFixed.params.fixed_lots} 手  初始资金: 2,000,000\n')

all_results = []
for code, name in stocks:
    print(f'  {code} {name}...', end=' ', flush=True)
    r = backtest_stock(code, name)
    if r:
        all_results.append(r)
        won_pct = f'{r["won"]/max(r["trades"],1)*100:.0f}%'
        print(f'{r["ret"]:+.2f}%  交易{r["trades"]}次  胜率{won_pct}')
    else:
        print('失败')
    time.sleep(1)

print()
print('=' * 65)
print('【固定手数】多品种回测结果')
print('=' * 65)

if all_results:
    df_r = pd.DataFrame(all_results).sort_values('ret', ascending=False)
    print(f'\n{"代码":>8s}  {"名称":>6s}  {"收益率":>10s}  {"交易次数":>8s}  {"胜率":>6s}  {"最大回撤":>8s}')
    print('-' * 50)
    for _, r in df_r.iterrows():
        won_pct = f'{r["won"]/max(r["trades"],1)*100:.0f}%'
        ret_s = f'{r["ret"]:+.2f}%'
        print(f'{r["code"]:>8s}  {r["name"]:>6s}  {ret_s:>10s}  {r["trades"]:>8d}  {won_pct:>6s}  {r["max_dd"]:>6.1f}%  ', end='')
        if r['ret'] > 20: print('🏆', end='')
        elif r['ret'] > 5: print('✅', end='')
        elif r['ret'] > 0: print('👍', end='')
        else: print('❌', end='')
        print()

    print(f'\n📊 统计摘要:')
    print(f'  平均收益率:       {df_r["ret"].mean():+.2f}%')
    print(f'  中位数收益率:     {df_r["ret"].median():+.2f}%')
    print(f'  最好:             {df_r.iloc[0]["name"]}  {df_r.iloc[0]["ret"]:+.2f}%')
    print(f'  最差:             {df_r.iloc[-1]["name"]}  {df_r.iloc[-1]["ret"]:+.2f}%')
    print(f'  正收益占比:       {(df_r["ret"]>0).sum()}/{len(df_r)} ({(df_r["ret"]>0).sum()/len(df_r)*100:.0f}%)')
    print(f'  平均最大回撤:     {df_r["max_dd"].mean():.2f}%')
    print(f'  平均交易次数:     {df_r["trades"].mean():.0f}')

    # 保存
    df_r.to_csv('multi_stock_backtest_fixed.csv', index=False, encoding='utf-8-sig')
    print(f'\n结果已保存: multi_stock_backtest_fixed.csv')
