"""
Phase 1 专题2：多技术指标组合回测
MACD + RSI + 布林带 信号组合，对比不同仓位模型

目标：
1. 构造高频信号（比纯双均线交易频率高）
2. 在不同信号强度下验证 ATR 仓位管理的有效性
3. 一口起闭合专题1（仓位管理验证）+ 专题2（多指标组合）
"""
import sys, io, os, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime

# ════════════════════════════════════════
# 数据源（本地缓存优先，首次从 akshare 下载）
# ════════════════════════════════════════
CACHE_FILE = os.path.join(os.path.dirname(__file__), 'sh000300_cache.pkl')

def get_data(start='2020-01-01', end='2026-04-30'):
    """读取本地缓存或从 akshare 下载后缓存"""
    if os.path.exists(CACHE_FILE):
        print(f"📦 从本地缓存读取：{CACHE_FILE}")
        df = pd.read_pickle(CACHE_FILE)
        df = df.loc[start:end]
        print(f"数据范围：{df.index[0].date()} ~ {df.index[-1].date()}，共 {len(df)} 个交易日")
        return df

    # 尝试下载
    print("⬇️ 正在下载沪深300数据...")
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily('sh000300')
        df.index = pd.to_datetime(df['date'])
        df = df.sort_index()
        df = df.loc[start:end]
        df.rename(columns={'open':'open','high':'high','low':'low','close':'close','volume':'volume'}, inplace=True)
        df = df[['open','high','low','close','volume']]
        full_df = df.copy()
        full_df.to_pickle(CACHE_FILE)
        print(f"💾 已缓存到 {CACHE_FILE}")
        print(f"数据范围：{df.index[0].date()} ~ {df.index[-1].date()}，共 {len(df)} 个交易日")
        return df
    except Exception as e:
        print(f"⚠️ akshare 下载失败 ({e})，改用合成数据验证逻辑")
        return None


def make_synthetic_data(periods=1532, start='2020-01-01'):
    """合成沪深300风格数据（用于 akshare 不可用时验证逻辑）"""
    np.random.seed(42)
    dates = pd.date_range(start=start, periods=periods, freq='B')
    # 沪深300风格的随机游走
    returns = np.random.normal(0.0003, 0.012, periods)
    price = 4000 * np.exp(np.cumsum(returns))
    # 生成 OHLC
    daily_vol = price * np.random.uniform(0.005, 0.02, periods)
    close = price
    open_ = close * np.random.uniform(0.998, 1.002, periods)
    high = np.maximum(open_, close) + np.abs(daily_vol) * np.random.uniform(0.3, 1.0, periods)
    low = np.minimum(open_, close) - np.abs(daily_vol) * np.random.uniform(0.3, 1.0, periods)
    volume = np.random.randint(1000000, 10000000, periods)

    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low, 'close': close, 'volume': volume
    }, index=dates)
    print(f"📊 使用合成数据：{len(df)} 个交易日，{df.index[0].date()} ~ {df.index[-1].date()}")
    print(f"  最后价格：{close[-1]:.2f}")
    return df

# ════════════════════════════════════════
# 信号生成器（独立函数，可复用）
# ════════════════════════════════════════
def generate_signals(df):
    """在 DataFrame 上计算 MACD/RSI/布林带信号，返回信号强度 -3~+3"""
    df = df.copy()

    # ── MACD ──
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - signal
    df['macd_cross'] = 0
    df.loc[(macd_hist > 0) & (macd_hist.shift(1) <= 0), 'macd_cross'] = 1   # 金叉
    df.loc[(macd_hist < 0) & (macd_hist.shift(1) >= 0), 'macd_cross'] = -1  # 死叉

    # ── RSI ──
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    df['rsi'] = rsi
    df['rsi_signal'] = 0
    df.loc[rsi < 30, 'rsi_signal'] = 1      # 超卖 → 买入信号
    df.loc[rsi > 70, 'rsi_signal'] = -1     # 超买 → 卖出信号

    # ── 布林带 ──
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    df['bb_signal'] = 0
    df.loc[df['close'] < bb_lower, 'bb_signal'] = 1     # 下轨以下 → 超卖
    df.loc[df['close'] > bb_upper, 'bb_signal'] = -1    # 上轨以上 → 超买

    # ── ATR ──
    tr = pd.DataFrame({
        'hl': df['high'] - df['low'],
        'hc': (df['high'] - df['close'].shift()).abs(),
        'lc': (df['low'] - df['close'].shift()).abs(),
    }).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()

    # ── 综合信号强度（-3 ~ +3） ──
    df['signal_strength'] = df['macd_cross'] + df['rsi_signal'] + df['bb_signal']

    # ── 方案 B：MACD 主信号 + RSI/布林带辅助过滤 ──
    # 买入：MACD 金叉 AND（RSI < 40 OR 布林带下轨附近）
    # 卖出：MACD 死叉 OR（已有持仓时 RSI > 70 AND 价格破上轨）
    bb_lower_buy = df['close'] < df['close'].rolling(20).mean() - df['close'].rolling(20).std()  # 在下轨以下区域
    bb_upper_sell = df['close'] > df['close'].rolling(20).mean() + df['close'].rolling(20).std() # 在上轨以上区域

    df['signal_buy'] = (df['macd_cross'] == 1) & ((df['rsi'] < 40) | (bb_lower_buy))
    df['signal_sell'] = (df['macd_cross'] == -1) | ((df['rsi'] > 70) & (bb_upper_sell))

    # 交易频次统计
    buy_days = df['signal_buy'].sum()
    sell_days = df['signal_sell'].sum()
    return df, buy_days, sell_days


# ════════════════════════════════════════
# Backtrader 策略：多信号 + 仓位管理
# ════════════════════════════════════════

# ════════════════════════════════════════
# 扩展 DataFeed：将信号列暴露为 lines
# ════════════════════════════════════════
class SignalData(bt.feeds.PandasData):
    """扩展 PandasData，加入信号列和 ATR 列"""
    lines = ('signal_buy', 'signal_sell', 'signal_strength', 'atr14')
    params = (
        ('signal_buy', 'signal_buy'),
        ('signal_sell', 'signal_sell'),
        ('signal_strength', 'signal_strength'),
        ('atr14', 'atr14'),
    )


class MultiIndicatorStrategy(bt.Strategy):
    """多指标信号策略，支持多种仓位模型

    模式选择：
    - 'full': 全仓进出
    - 'fixed25': 固定25%仓位
    - 'fixed50': 固定50%
    - 'atr': ATR 动态仓位
    """
    params = (
        ('mode', 'full'),
        ('atr_period', 14),
        ('risk_pct', 0.02),
    )

    def __init__(self):
        self.order = None

    def next(self):
        if self.order:
            return

        buy = self.data.signal_buy[0]
        sell = self.data.signal_sell[0]
        price = self.data.close[0]

        # 卖出优先（持仓时才检查）
        if self.position:
            if sell:
                self._close_position()
        elif buy:
            self._open_position(price)

    def _open_position(self, price):
        mode = self.params.mode
        cash = self.broker.getcash()
        value = self.broker.getvalue()

        if mode == 'full':
            size = int(cash / price)

        elif mode == 'fixed25':
            target_val = value * 0.25
            size = int(min(cash, target_val) / price)

        elif mode == 'fixed50':
            target_val = value * 0.50
            size = int(min(cash, target_val) / price)

        elif mode == 'atr':
            atr_val = self.data.atr14[0]
            total_risk = value * self.params.risk_pct
            size_target = int(total_risk / atr_val) if atr_val > 0 else 0
            max_by_cash = int(cash / price)
            size = min(size_target, max_by_cash) if size_target > 0 else 0

        else:
            size = 0

        if size > 0:
            self.order = self.buy(size=size)

    def _close_position(self):
        self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


# ════════════════════════════════════════
# ATR 计算函数（预计算到 DataFrame 中）
# ════════════════════════════════════════
def add_atr_column(df, period=14):
    """在 DataFrame 上预计算 ATR 列"""
    high = df['high']
    low = df['low']
    close = df['close']

    tr = pd.DataFrame({
        'hl': high - low,
        'hc': (high - close.shift()).abs(),
        'lc': (low - close.shift()).abs(),
    }).max(axis=1)
    atr = tr.rolling(period).mean()
    df['atr14'] = atr
    return df


# ════════════════════════════════════════
# 回测封装
# ════════════════════════════════════════

def run_backtest_with_signals(df, strategy_name, cash=100000, mode='full', risk_pct=0.02):
    """用已带信号的 DataFrame 跑回测"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0003)

    data = SignalData(dataname=df)
    cerebro.adddata(data)
    cerebro.addstrategy(MultiIndicatorStrategy, mode=mode, risk_pct=risk_pct)
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
    print(f"  总收益率：{total_return:>+6.2f}%")
    print(f"  年化收益：{returns.get('rnorm100', 0):>+6.2f}%")
    sr = sharpe.get('sharperatio', None)
    print(f"  夏普比率：{sr:.4f}" if sr is not None else "  夏普比率：N/A")
    print(f"  最大回撤：{dd.get('max', {}).get('drawdown', 0):>6.2f}%")
    print(f"  交易次数：{trade_count}")
    print(f"  胜率：{win_rate:>5.1f}%")
    print(f"  盈利次数：{won}  亏损次数：{lost}")

    return {
        'name': strategy_name,
        'final': final_val,
        'return_pct': total_return,
        'sharpe': sr if sr is not None else 0,
        'max_dd': dd.get('max', {}).get('drawdown', 0),
        'trades': trade_count,
        'win_rate': win_rate,
    }


# ════════════════════════════════════════
# 主程序
# ════════════════════════════════════════

if __name__ == '__main__':
    df_raw = get_data()
    if df_raw is None:
        df_raw = make_synthetic_data(periods=1532)

    # 生成信号
    df, buy_days, sell_days = generate_signals(df_raw)
    print(f"\n信号统计（2020-01 ~ 2026-04）：")
    print(f"  买入信号天数：{buy_days}")
    print(f"  卖出信号天数：{sell_days}")
    print(f"  日均信号强度：{df['signal_strength'].abs().mean():.2f}")
    print(f"  信号强度 >0 占比：{(df['signal_strength'].abs() > 0).mean()*100:.1f}%")

    # 去除 NaN（指标计算需要足够窗口）
    df_clean = df.dropna(subset=['signal_buy', 'signal_sell', 'atr14'])
    print(f"\n清理后有效数据：{len(df_clean)} 个交易日（去除指标预热期）")

    # ═══ 对比回测 ═══
    cash = 1_000_000
    results = []

    # 基准：全仓进出（多信号）
    r = run_backtest_with_signals(df, "🔵 多信号 + 全仓", cash=cash, mode='full')
    results.append(r)

    # 固定比例
    r = run_backtest_with_signals(df, "🟠 多信号 + 固定25%", cash=cash, mode='fixed25')
    results.append(r)
    r = run_backtest_with_signals(df, "🟠 多信号 + 固定50%", cash=cash, mode='fixed50')
    results.append(r)

    # ATR 梯度对比
    r = run_backtest_with_signals(df, "🟢 多信号 + ATR(风险1%)", cash=cash, mode='atr', risk_pct=0.01)
    results.append(r)
    r = run_backtest_with_signals(df, "🟢 多信号 + ATR(风险2%)", cash=cash, mode='atr', risk_pct=0.02)
    results.append(r)
    r = run_backtest_with_signals(df, "🟢 多信号 + ATR(风险5%)", cash=cash, mode='atr', risk_pct=0.05)
    results.append(r)
    r = run_backtest_with_signals(df, "🟢 多信号 + ATR(风险10%)", cash=cash, mode='atr', risk_pct=0.10)
    results.append(r)

    # ═══ 输出对比表 ═══
    print(f"\n\n{'='*75}")
    print(f"  📊 多指标信号 + 仓位管理 对比总结（初始资金 {cash/10000:.0f}万）")
    print(f"{'='*75}")
    print(f"{'策略':<32} {'收益率':>8} {'夏普':>8} {'最大回撤':>8} {'交易次数':>8} {'胜率':>6}")
    print("-"*75)
    for r in results:
        sharpe_s = f"{r['sharpe']:.3f}" if r['sharpe'] != 0 else "N/A"
        print(f"{r['name']:<32} {r['return_pct']:>+7.2f}% {sharpe_s:>8} {r['max_dd']:>7.2f}% {r['trades']:>8} {r['win_rate']:>5.1f}%")

    # ═══ 关键问题回答 ═══
    print(f"\n\n{'='*75}")
    print(f"  🔍 关键结论")
    print(f"{'='*75}")

    sig_days = (df['signal_strength'].abs() > 0).sum()
    print(f"  1. 方案 B：MACD 主信号 + RSI/布林带辅助过滤")
    print(f"   — 买入：MACD 金叉 AND (RSI<40 OR 价格在下轨附近)")
    print(f"   — 卖出：MACD 死叉 OR (持仓中 RSI>70 AND 价格破上轨)")

    atr_results = [r for r in results if 'ATR' in r['name']]
    atr_returns = [r['return_pct'] for r in atr_results]
    if len(set(atr_returns)) > 1:
        print(f"  2. ATR 不同风险参数已出现分化 ✅")
        print(f"   — 说明高频策略下 ATR 仓位管理能发挥效果")
    else:
        print(f"  2. ATR 不同风险参数仍无分化 ⚠️")

    # 对比纯双均线历史结果
    best = max(results, key=lambda x: x['return_pct'])
    print(f"\n  3. 最优策略：{best['name']} 收益 {best['return_pct']:+.2f}%")
    print(f"   — 对比纯双均线全仓 +0.89%/回撤1.07%，多指标过滤后是否有改善？")

    print(f"\n  （详细分析见上方各策略输出）")
