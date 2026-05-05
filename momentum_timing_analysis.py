"""
Phase 1 专题7：动量择时分析 — 什么时候动量有效/失效？
====================================================
内容：
1. 动量策略的分段表现（牛/熊/震荡市）
2. 动量 crash 检测（动量策略大幅回撤的归因）
3. 市场状态与动量收益的关系（用 HS300 判断市场环境）
4. 动量因子 IC 的时间变化趋势
"""

import sys, io, os, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import akshare as ak
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'sw_cache')
OUTPUT_DIR = os.path.dirname(__file__)


def load_all_industry_prices(start='2015-01-01', end='2026-04-30'):
    df_info = ak.sw_index_first_info()
    industries = [(code.replace('.SI', '').strip(), name.strip())
                  for code, name in df_info[['行业代码', '行业名称']].values.tolist()]
    prices = {}
    for code, name in industries:
        cache = os.path.join(CACHE_DIR, f'{code}.pkl')
        if not os.path.exists(cache):
            continue
        try:
            df = pd.read_pickle(cache)
            df['date'] = pd.to_datetime(df['日期'])
            df = df.set_index('date').sort_index().loc[start:end]
            if len(df) > 100:
                row = df_info[df_info['行业代码'].str.contains(code)]
                cname = row['行业名称'].values[0] if len(row) > 0 else code
                prices[cname] = df['收盘']
        except:
            pass
    price_df = pd.DataFrame(prices).dropna(how='all')
    return price_df


def load_hs300():
    df = pd.read_pickle('sh000300_cache.pkl')
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.sort_index()


# ════════════════════════════════════════
# 1. 动量策略（12个月 top5）回测，记录每月收益
# ════════════════════════════════════════

def run_momentum12_top5(price_df):
    """动量12m top5 月度调仓，返回月收益序列"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    dates = monthly.index.tolist()

    monthly_rets = []
    monthly_dates = []
    nav = [1.0]

    for i in range(1, len(dates)):
        prev_date = dates[i-1]
        cur_date = dates[i]

        # 12个月动量
        for_prev = monthly.loc[:prev_date].iloc[-12:] if len(monthly.loc[:prev_date]) >= 12 else monthly.loc[:prev_date]
        if len(for_prev) < 12:
            monthly_rets.append(0)
            monthly_dates.append(cur_date)
            nav.append(nav[-1])
            continue

        mom = for_prev.iloc[-1] / for_prev.iloc[0] - 1
        top5 = mom.nlargest(5).index.tolist()

        # 持仓收益
        available = [c for c in top5 if c in monthly.columns and c in monthly.columns]
        if len(available) == 0:
            monthly_rets.append(0)
            monthly_dates.append(cur_date)
            nav.append(nav[-1])
            continue

        prev_prices = monthly.loc[prev_date, available].values
        cur_prices = monthly.loc[cur_date, available].values
        prev_prices = np.where(prev_prices == 0, np.nan, prev_prices)
        ret = np.nanmean((cur_prices / prev_prices) - 1)
        monthly_rets.append(ret)
        monthly_dates.append(cur_date)
        nav.append(nav[-1] * (1 + ret))

    return pd.Series(monthly_rets, index=pd.to_datetime(monthly_dates), name='动量12m_top5'), pd.Series(nav[1:], index=pd.to_datetime(monthly_dates), name='动量12m_top5_净值')


# ════════════════════════════════════════
# 2. 市场状态划分
# ════════════════════════════════════════

def classify_market(hs300_close, mom_rets):
    """用沪深300的月度收益和趋势划分市场状态"""
    monthly = hs300_close.resample('ME').last()
    monthly_ret = monthly.pct_change().dropna()

    # 对齐日期
    common_idx = monthly_ret.index.intersection(mom_rets.index)
    mkt_ret = monthly_ret[common_idx]
    mom_ret = mom_rets[common_idx]

    # 用12个月滚动均线划分牛熊
    mkt_ma = monthly.rolling(12).mean()

    regimes = {}
    for idx in common_idx:
        if idx not in mkt_ma.index or np.isnan(mkt_ma.loc[idx]):
            regimes[idx] = '未知'
            continue

        price = monthly.loc[idx]
        ma = mkt_ma.loc[idx]

        if np.isnan(ma):
            regimes[idx] = '未知'
            continue

        # 找到3个月前的索引
        all_idx = monthly.index.tolist()
        pos = all_idx.index(idx)
        idx_3m_pos = max(0, pos - 3)
        idx_3m = all_idx[idx_3m_pos]
        ret3m = (price / monthly.loc[idx_3m]) - 1

        if price > ma * 1.05 and ret3m > 0.03:
            regimes[idx] = '牛市'
        elif price < ma * 0.95 and ret3m < -0.03:
            regimes[idx] = '熊市'
        elif abs(ret3m) < 0.03:
            regimes[idx] = '震荡'
        else:
            regimes[idx] = '震荡（带趋势）'

    return pd.Series(regimes), mkt_ret, common_idx


# ════════════════════════════════════════
# 3. 动量 crash 分析
# ════════════════════════════════════════

def analyze_crashes(nav_series, mom_rets):
    """分析动量最大回撤区间，归因"""
    dd = nav_series / nav_series.cummax() - 1
    dd.index = pd.to_datetime(dd.index)

    # 找到所有 > 10% 的回撤
    crash_threshold = -0.10
    in_crash = dd < crash_threshold

    crash_periods = []
    start = None
    for i in range(len(dd)):
        if in_crash.iloc[i] and start is None:
            start = dd.index[i]
        elif not in_crash.iloc[i] and start is not None:
            crash_periods.append((start, dd.index[i]))
            start = None
    if start is not None:
        crash_periods.append((start, dd.index[-1]))

    print(f'\n📉 动量大回撤分析（阈值 {crash_threshold*100:.0f}%）')
    print(f'  {"开始":12s} | {"结束":12s} | {"最大回撤":>8s} | {"月度数":>6s}')

    crash_details = []
    for start, end in crash_periods:
        period_dd = dd[start:end]
        max_dd_val = period_dd.min()
        n_months = len(period_dd)

        # 归因：这个区间动量买的是哪些行业
        # 取这个区间的中段点查看
        mid_date = start + (end - start) / 2
        crash_details.append({
            '开始': start.date(),
            '结束': end.date(),
            '最大回撤': max_dd_val,
            '月数': n_months,
        })
        print(f'  {start.date()} | {end.date()} | {max_dd_val*100:>+7.1f}% | {n_months:>4d}')

    return crash_details


# ════════════════════════════════════════
# 4. 动量 IC 时间趋势
# ════════════════════════════════════════

def factor_momentum(price_df, date, window=12):
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    if date not in monthly.index:
        return None
    iloc = monthly.index.get_loc(date)
    if iloc < window:
        return None
    prev = monthly.iloc[iloc - window]
    cur = monthly.iloc[iloc]
    return (cur / prev - 1)


def calc_momentum_ic(price_df):
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    ic_list = []
    for i in range(1, len(monthly)):
        date = monthly.index[i]
        factor = factor_momentum(price_df, date, 12)
        if factor is None:
            continue
        ret = monthly.iloc[i] / monthly.iloc[i-1] - 1
        common = factor.dropna().index.intersection(ret.dropna().index)
        if len(common) < 5:
            continue
        ic = factor[common].rank().corr(ret[common].rank(), method='spearman')
        ic_list.append((date, ic))
    return pd.DataFrame(ic_list, columns=['date', 'IC']).set_index('date')['IC']


# ════════════════════════════════════════
# 主流程
# ════════════════════════════════════════

print('=' * 60)
print('🚀 动量择时分析 — 什么时候有效/失效？')
print('=' * 60)

print('\n📥 加载数据...')
price_df = load_all_industry_prices()
print(f'  行业: {price_df.shape[1]}, 日期: {price_df.index[0].date()} ~ {price_df.index[-1].date()}')

hs300 = load_hs300()
print(f'  沪深300: {hs300.index[0].date()} ~ {hs300.index[-1].date()}')

# ── 动量策略月收益 ──
print('\n📊 动量12m_top5 月收益...')
mom_rets, nav = run_momentum12_top5(price_df)
print(f'  月数: {len(mom_rets)}')
print(f'  总收益: {(nav.iloc[-1]/nav.iloc[0]-1)*100:+.2f}%')
print(f'  月胜率: {(mom_rets>0).mean()*100:.0f}%')

# ── 市场状态划分 ──
print('\n📊 市场状态划分...')
hs300_close = hs300['close']
regimes, mkt_ret, common_idx = classify_market(hs300_close, mom_rets)

# 按市场状态统计动量收益
mom_aligned = mom_rets[common_idx]
regime_counts = regimes.value_counts()
print(f'\n市场状态分布:')
for regime, count in regime_counts.items():
    print(f'  {regime}: {count} 个月')

print(f'\n市场状态 vs 动量收益:')
regime_stats = {}
for regime in regimes.unique():
    mask = regimes == regime
    r = mom_aligned[mask]
    if len(r) == 0:
        continue
    win_rate = (r > 0).mean() * 100
    avg_ret = r.mean() * 100
    total_ret = ((1 + r.values).prod() - 1) * 100
    regime_stats[regime] = {
        '月数': len(r),
        '平均月收益%': avg_ret,
        '总收益%': total_ret,
        '月胜率%': win_rate,
    }
    print(f'  {regime:12s}  {len(r):>4d}个月  平均月收益={avg_ret:+.2f}%  总收益={total_ret:+.2f}%  胜率={win_rate:.0f}%')

# ── 分市场状态作图 ──
fig, axes = plt.subplots(3, 1, figsize=(14, 12))

# 上：市场状态和动量净值
ax = axes[0]
colors_map = {'牛市': '#4CAF50', '熊市': '#F44336', '震荡': '#FF9800', '震荡（带趋势）': '#2196F3', '未知': '#9E9E9E'}
bar_colors = [colors_map.get(regimes.get(d, '未知'), '#9E9E9E') for d in nav.index if d in regimes.index]
ax.plot(nav.index, nav.values / nav.iloc[0], color='black', linewidth=1.5, label='动量12m_top5净值')
# 着色区域
ax2 = ax.twinx()
for i in range(len(nav) - 1):
    d = nav.index[i]
    if d not in regimes.index:
        continue
    ax2.axvspan(d, nav.index[i+1], alpha=0.15, color=colors_map.get(regimes[d], '#9E9E9E'))
ax2.set_yticks([])
ax.legend(loc='upper left')
ax.set_ylabel('累计净值（对数）')
ax.set_yscale('log')
ax.set_title('动量策略净值 vs 市场状态', fontsize=12)
ax.grid(True, alpha=0.3)

# 中：月度收益直方图
ax = axes[1]
mom_aligned_series = mom_aligned
colors_hist = ['#F44336' if r < 0 else '#4CAF50' for r in mom_aligned_series.values]
ax.bar(range(len(mom_aligned_series)), mom_aligned_series.values * 100, color=colors_hist, alpha=0.7, width=0.8)
ax.axhline(y=0, color='gray', linewidth=0.5)
ax.set_xlabel('月份')
ax.set_ylabel('月收益 (%)')
ax.set_title('动量12m_top5 月度收益', fontsize=12)
ax.grid(True, alpha=0.3)

# 下：滚动 IC 与市场状态
ax = axes[2]
ic_series = calc_momentum_ic(price_df)
ic_monthly = ic_series.resample('ME').last().dropna()
ic_ma = ic_monthly.rolling(12).mean()
ax.plot(ic_monthly.index, ic_monthly.values, alpha=0.4, color='gray', label='月度IC', linewidth=0.8)
ax.plot(ic_ma.index, ic_ma.values, color='#F44336', linewidth=2, label='12个月滚动均值IC', marker='')
ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
ax.legend(loc='upper left')
ax.set_xlabel('日期')
ax.set_ylabel('Rank IC')
ax.set_title('动量因子 IC 时间趋势', fontsize=12)
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig_path = os.path.join(OUTPUT_DIR, 'momentum_regime_analysis.png')
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f'\n  ✅ 市场状态分析图已保存: momentum_regime_analysis.png')

# ── Crash 分析 ──
print('\n📉 动量大回撤分析...')
crash_details = analyze_crashes(nav, mom_rets)
print(f'  总计 {len(crash_details)} 次大回撤（>10%）')

# 动量 vs HS300 的月度收益对比
print('\n📊 动量 vs 沪深300 月度收益对比:')
common_across = mom_aligned.index.intersection(mkt_ret.index)
mkt_ret_c = mkt_ret[common_across] * 100
mom_ret_c = mom_aligned[common_across] * 100

# 市场上涨/下跌时动量表现
up_months = mkt_ret_c > 0
down_months = mkt_ret_c <= 0

print(f'  市场上涨月 (n={up_months.sum()}):')
print(f'    动量平均收益: {mom_ret_c[up_months].mean():+.2f}%  | 胜率: {(mom_ret_c[up_months]>0).mean()*100:.0f}%')
print(f'  市场下跌月 (n={down_months.sum()}):')
print(f'    动量平均收益: {mom_ret_c[down_months].mean():+.2f}%  | 胜率: {(mom_ret_c[down_months]>0).mean()*100:.0f}%')
print(f'  动量 vs 沪深300 月度相关性: {mom_ret_c.corr(mkt_ret_c):+.3f}')

# ── 动量 crash 归因图 ──
fig2, axes2 = plt.subplots(2, 1, figsize=(14, 8))

# 回撤曲线
ax = axes2[0]
dd = nav / nav.cummax() - 1
ax.fill_between(dd.index, dd.values * 100, 0, color='#F44336', alpha=0.3)
ax.plot(dd.index, dd.values * 100, color='#F44336', linewidth=1)
ax.axhline(y=-10, color='gray', linestyle='--', alpha=0.7, label='-10%阈值')
ax.legend(loc='lower left')
ax.set_ylabel('回撤 (%)')
ax.set_title('动量12m_top5 回撤曲线', fontsize=12)
ax.grid(True, alpha=0.3)

# 滚动12个月ICIR
ax = axes2[1]
rolling_icir = ic_monthly.rolling(24).apply(lambda x: x.mean() / x.std() if x.std() > 0 else 0)
ax.plot(rolling_icir.index, rolling_icir.values, color='#2196F3', linewidth=1.5)
ax.axhline(y=0.5, color='gray', linestyle='--', alpha=0.5, label='ICIR=0.5')
ax.axhline(y=0, color='gray', linestyle='-', alpha=0.5)
ax.legend(loc='upper left')
ax.set_xlabel('日期')
ax.set_ylabel('24个月滚动ICIR')
ax.set_title('动量因子预测稳定性（滚动ICIR）', fontsize=12)
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig2_path = os.path.join(OUTPUT_DIR, 'momentum_crash_analysis.png')
plt.savefig(fig2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f'  ✅ Crash 分析图已保存: momentum_crash_analysis.png')

# ── 动量 IC 的分段统计 ──
print('\n📊 IC 的分段统计（按年份）:')
ic_years = ic_monthly.groupby(ic_monthly.index.year)
for year, ic_data in ic_years:
    if len(ic_data) < 6:
        continue
    mean_ic = ic_data.mean()
    std_ic = ic_data.std()
    icir = mean_ic / std_ic if std_ic > 0 else 0
    pos_ratio = (ic_data > 0).mean() * 100
    print(f'  {year}: IC={mean_ic:+.4f}  ICIR={icir:+.3f}  胜率={pos_ratio:.0f}%  n={len(ic_data)}')


print('\n' + '=' * 60)
print('分析完成！')
print(f'  📎 momentum_regime_analysis.png')
print(f'  📎 momentum_crash_analysis.png')
print('=' * 60)
