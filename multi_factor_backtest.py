"""
Phase 1 专题5：多因子模型回测 — 修复版
— 申万一级行业指数（31个行业）动量+低波+价值三因子

逻辑（写代码前已确认）：
1. 标的：31个申万一级行业指数
2. 因子：动量（过去N月收益）+ 低波（波动率倒数）+ 价值（价格偏离年线）
3. 合成：每个因子Rank打分（0~1），等权加总
4. 选择：总分TopK，等权配置，月度调仓
5. 对比：沪深300、行业等权、纯动量
"""
import sys, io, os, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import akshare as ak
import time

# ════════════════════════════════════════
# 数据
# ════════════════════════════════════════
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'sw_cache')

def download_sw_data():
    """下载申万一级行业数据"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    df_info = ak.sw_index_first_info()
    industries = [(code.replace('.SI', '').strip(), name.strip())
                  for code, name in df_info[['行业代码', '行业名称']].values.tolist()]
    print(f'   共 {len(industries)} 个行业')

    for code, name in industries:
        cache = os.path.join(CACHE_DIR, f'{code}.pkl')
        if os.path.exists(cache):
            continue
        try:
            df = ak.index_hist_sw(symbol=code)
            df.to_pickle(cache)
            print(f'  ✅ {name}({code}): {df.date.iloc[0]} ~ {df.date.iloc[-1]}')
        except Exception as e:
            print(f'  ❌ {name}({code}): {str(e)[:60]}')
        time.sleep(0.3)

    print(f'   共 {len(industries)} 个行业已缓存')

def load_sw_data(start='2015-01-01', end='2026-04-30'):
    """加载价格DataFrame"""
    if not os.path.exists(CACHE_DIR):
        download_sw_data()
    elif len(os.listdir(CACHE_DIR)) == 0:
        download_sw_data()

    # 检查是否有31个缓存，不够就补
    df_info = ak.sw_index_first_info()
    all_codes = [code.replace('.SI', '').strip() for code in df_info['行业代码']]
    cached = [f.replace('.pkl', '') for f in os.listdir(CACHE_DIR) if f.endswith('.pkl') and f != 'pe_all.pkl']
    missing = [c for c in all_codes if c not in cached]
    if missing:
        print(f'   缺少 {len(missing)} 个行业缓存, 补充下载...')
        for code in missing:
            name_row = df_info[df_info['行业代码'].str.contains(code)]
            name = name_row['行业名称'].values[0] if len(name_row) > 0 else code
            try:
                df = ak.index_hist_sw(symbol=code)
                df.to_pickle(os.path.join(CACHE_DIR, f'{code}.pkl'))
                print(f'  ✅ {name}({code})')
            except Exception as e:
                print(f'  ❌ {code}: {str(e)[:60]}')
            time.sleep(0.3)

    # 加载所有行业
    prices = {}
    valid = []
    for code in all_codes:
        cache = os.path.join(CACHE_DIR, f'{code}.pkl')
        if not os.path.exists(cache):
            continue
        try:
            df = pd.read_pickle(cache)
            df['date'] = pd.to_datetime(df['日期'])
            df = df.set_index('date').sort_index()
            df = df.loc[start:end]
            if len(df) > 100:
                name_row = df_info[df_info['行业代码'].str.contains(code)]
                name = name_row['行业名称'].values[0] if len(name_row) > 0 else code
                prices[code] = df['收盘'].rename(name)
                valid.append(code)
        except:
            pass

    price_df = pd.DataFrame(prices)
    price_df = price_df.dropna(how='all')
    return price_df


# ════════════════════════════════════════
# 因子计算
# ════════════════════════════════════════
def compute_factors(price_df, momentum_months=6):
    """返回月末评分的DataFrame, 总分列"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)

    # 1. 动量因子：过去N月的累计收益
    mom_ret = monthly.pct_change(periods=momentum_months)
    mom_rank = mom_ret.rank(axis=1, ascending=True, pct=True).fillna(0.5)

    # 2. 低波因子：过去N个月的日波动率倒数
    vol_scores = {}
    for col in price_df.columns:
        daily_ret = price_df[col].pct_change().dropna()
        # 月度波动率，然后年化
        vol = daily_ret.groupby(pd.Grouper(freq='ME')).std() * np.sqrt(252)
        # 滚动6个月平均波动率（更稳定）
        vol = vol.rolling(momentum_months, min_periods=1).mean()
        low_vol = 1.0 / vol.replace(0, np.nan)
        vol_scores[col] = low_vol

    vol_df = pd.DataFrame(vol_scores)
    vol_rank = vol_df.rank(axis=1, ascending=True, pct=True).fillna(0.5)
    vol_rank = vol_rank.reindex(monthly.index).ffill()

    # 3. 价值因子：价格低于年线越多越"便宜"
    value_scores = {}
    for col in price_df.columns:
        ma250 = price_df[col].rolling(250).mean()
        deviation = (price_df[col] - ma250) / ma250
        value_scores[col] = deviation

    value_df = pd.DataFrame(value_scores)
    value_monthly = value_df.resample('ME').last()
    # 负偏离越大越有价值 → 用 ascending=False rank
    value_rank = value_monthly.rank(axis=1, ascending=False, pct=True).fillna(0.5)
    value_rank = value_rank.reindex(monthly.index).ffill()

    # 合成：等权
    combined = mom_rank * 1/3 + vol_rank * 1/3 + value_rank * 1/3
    return combined


# ════════════════════════════════════════
# 回测
# ════════════════════════════════════════
def run_backtest(price_df, total_score_df, topk=5, cash=100000, commission=0.0003, label='strategy'):
    """通用回测函数"""
    monthly = total_score_df.index
    # 所有调仓日期取在 monthly.index 内
    dates = monthly.tolist()

    # 需要之前的月度价格数据来算收益率
    monthly_prices = price_df.resample('ME').last().dropna(how='all', axis=1)
    price_dates = set(monthly_prices.index)

    vals = [cash]
    month_returns = []

    for i in range(1, len(dates)):
        prev_signal_date = dates[i-1]  # 用这个日期的rank做信号
        cur_date = dates[i]

        if prev_signal_date not in total_score_df.index or cur_date not in price_dates:
            vals.append(vals[-1])
            continue

        # 取出总分排名
        scores = total_score_df.loc[prev_signal_date]
        top_cols = scores.nlargest(topk).index.tolist()

        # 用当月价格计算收益
        if prev_signal_date not in monthly_prices.index or cur_date not in monthly_prices.index:
            vals.append(vals[-1])
            continue

        # 取当月的实际持仓收益
        # 简化：用调仓日当月的收盘价来做，把 prev 当做上月末 rebal 价格
        p_prev = monthly_prices.loc[prev_signal_date, top_cols].values
        p_cur = monthly_prices.loc[cur_date, top_cols].values

        # 防止除零
        p_prev = np.where(p_prev == 0, np.nan, p_prev)
        rets = (p_cur / p_prev) - 1
        port_ret = np.nanmean(rets)

        if np.isnan(port_ret):
            port_ret = 0

        month_returns.append(port_ret)
        vals.append(vals[-1] * (1 + port_ret))

    if len(month_returns) == 0:
        return None

    final = vals[-1]
    total_ret = (final / cash - 1) * 100
    years = (dates[-1] - dates[0]).days / 365.25 if len(dates) > 1 else 1
    annualized = ((final / cash) ** (1 / years) - 1) * 100 if years > 0 else 0

    # 回撤
    vals_arr = np.array(vals)
    peaks = np.maximum.accumulate(vals_arr)
    dd = (vals_arr - peaks) / peaks * 100
    max_dd = abs(min(dd))

    # 夏普、胜率、SQN
    rets_arr = np.array(month_returns)
    if len(rets_arr) > 1 and rets_arr.std() > 0:
        excess = rets_arr - 0.03 / 12
        sharpe = np.sqrt(12) * excess.mean() / rets_arr.std()
        sqn = np.sqrt(len(rets_arr)) * rets_arr.mean() / rets_arr.std()
    else:
        sharpe = 0
        sqn = 0
    win_rate = (rets_arr > 0).mean() * 100

    print(f'    收益: {total_ret:+.2f}%  年化: {annualized:.2f}%  回撤: {max_dd:.1f}%')
    print(f'    夏普: {sharpe:.2f}  月数: {len(month_returns)}  胜率: {win_rate:.1f}%  SQN: {sqn:.2f}')
    print(f'    最终: {final:,.0f}')

    return {
        'label': label,
        'total_return': round(total_ret, 2),
        'annual_return': round(annualized, 2),
        'max_drawdown': round(max_dd, 1),
        'sharpe': round(sharpe, 2),
        'total_months': len(month_returns),
        'win_rate': round(win_rate, 1),
        'sqn': round(sqn, 2),
        'final_value': final,
    }


def run_multi_factor(price_df, topk=5, momentum_months=6, cash=100000):
    label = f'多因子_mom={momentum_months}m_top{topk}'
    print(f"\n{'─'*55}")
    print(f'  🚀 {label}')
    scores = compute_factors(price_df, momentum_months=momentum_months)
    return run_backtest(price_df, scores, topk=topk, cash=cash, label=label)


def run_pure_momentum(price_df, topk=5, momentum_months=6, cash=100000):
    label = f'纯动量_mom={momentum_months}m_top{topk}'
    print(f"\n{'─'*55}")
    print(f'  📊 {label}')
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    mom_scores = monthly.pct_change(periods=momentum_months)
    mom_scores = mom_scores.iloc[momentum_months:]
    mom_rank = mom_scores.rank(axis=1, ascending=True, pct=True).fillna(0.5)
    # 用评分对齐索引
    first_score_date = mom_rank.index[0]
    total_score_df = mom_rank  # 直接用rank作为总分
    return run_backtest(price_df, total_score_df, topk=topk, cash=cash, label=label)


# ════════════════════════════════════════
# 基准
# ════════════════════════════════════════
def calc_benchmarks(price_df, cash=100000):
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    years = (price_df.index[-1] - price_df.index[0]).days / 365.25

    # 行业等权
    n = monthly.shape[1]
    vals = [cash]
    for i in range(1, len(monthly)):
        rets = (monthly.iloc[i].values / monthly.iloc[i-1].values) - 1
        port_ret = np.nanmean(rets)
        vals.append(vals[-1] * (1 + port_ret))

    f = vals[-1]
    tr = (f / cash - 1) * 100
    ann = ((f / cash) ** (1 / years) - 1) * 100
    print(f"\n{'─'*55}")
    print(f'  📊 基准: 申万行业等权（月再平衡）')
    print(f'    收益: {tr:+.2f}%  年化: {ann:.2f}%  最终: {f:,.0f}')

    # 沪深300
    df300 = pd.read_pickle('sh000300_cache.pkl')
    df300.index = pd.to_datetime(df300.index).tz_localize(None)
    df300 = df300.sort_index()
    start_str = str(price_df.index[0].date())
    end_str = str(price_df.index[-1].date())
    df300 = df300.loc[start_str:end_str]
    bh_tr = (df300['close'].iloc[-1] / df300['close'].iloc[0] - 1) * 100
    bh_ann = ((df300['close'].iloc[-1] / df300['close'].iloc[0]) ** (1 / years) - 1) * 100
    print(f'  📊 基准: 沪深300买入持有')
    print(f'    收益: {bh_tr:+.2f}%  年化: {bh_ann:.2f}%')

    return {
        'eq_weight': {'总收益': tr, '年化': ann, '最终': f},
        'hs300': {'总收益': bh_tr, '年化': bh_ann},
    }


# ════════════════════════════════════════
# 入口
# ════════════════════════════════════════
if __name__ == '__main__':
    print(f"{'='*55}")
    print(f'  🧪 Phase 1 Topic 5: 多因子模型（修复版）')
    print(f'  申万一级行业 | 动量+低波+价值')
    print(f"{'='*55}")

    print('\n📥 加载数据...')
    price_df = load_sw_data()
    print(f'  {price_df.shape[1]} 个行业, {price_df.shape[0]} 个交易日')
    print(f'  {price_df.index[0].date()} ~ {price_df.index[-1].date()}')

    # 基准
    bench = calc_benchmarks(price_df)

    # 多因子组合
    configs = [
        (5, 6, 'mom=6m_top5'),
        (10, 6, 'mom=6m_top10'),
        (5, 3, 'mom=3m_top5'),
        (10, 3, 'mom=3m_top10'),
        (5, 12, 'mom=12m_top5'),
    ]

    results = []
    for topk, mom_m, label in configs:
        r = run_multi_factor(price_df, topk=topk, momentum_months=mom_m)
        if r:
            results.append(r)

    # 纯动量对比
    print(f"\n{'='*55}")
    print(f'  📊 纯动量对比（单因子）')
    print(f"{'='*55}")
    for topk, mom_m, label in configs:
        r = run_pure_momentum(price_df, topk=topk, momentum_months=mom_m)
        if r:
            results.append(r)

    # 汇总表格
    print(f"\n{'='*55}")
    print(f'  📋 最终对比')
    print(f"{'='*55}")
    h = f"{'策略':<35} {'总收益':>8} {'年化':>8} {'回撤':>7} {'夏普':>6} {'胜率':>6} {'最终':>10}"
    print(h)
    print('─' * 55)

    print(f"{'沪深300买入持有':<35} {bench['hs300']['总收益']:>+7.2f}% "
          f"{bench['hs300']['年化']:>6.2f}% {'N/A':>7} {'N/A':>6} {'N/A':>6} {'N/A':>10}")
    print(f"{'申万行业等权':<35} {bench['eq_weight']['总收益']:>+7.2f}% "
          f"{bench['eq_weight']['年化']:>6.2f}% {'N/A':>7} {'N/A':>6} {'N/A':>6} "
          f"{bench['eq_weight']['最终']:>10,.0f}")

    for r in results:
        print(f"{r['label']:<35} {r['total_return']:>+7.2f}% {r['annual_return']:>6.2f}% "
              f"{r['max_drawdown']:>6.1f}% {r['sharpe']:>5.2f} {r['win_rate']:>5.1f}% "
              f"{r['final_value']:>10,.0f}")

    print('\n✅ 全部完成')
