"""
Phase 1 专题6（对标 Week 1）：因子基本功 — IC 分析
===================================================
内容：
1. 动量因子的月度 IC（信息系数）计算
2. Rank IC 计算（Spearman 秩相关）
3. IC / ICIR 时间序列图
4. 多窗口动量的 IC 对比（1m/3m/6m/12m）
5. 多类因子的 IC 对比（动量 + 低波 + 价值）

用已有数据：31个申万一级行业指数（sw_cache/），沪深300（sh000300_cache.pkl）
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
OUTPUT_DIR = os.path.join(os.path.dirname(__file__))


def load_all_industry_prices(start='2015-01-01', end='2026-04-30'):
    """加载31个申万一级行业收盘价"""
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


def calc_ic(price_df, factor_func, factor_name, freq='ME'):
    """
    计算因子的月度 Rank IC。
    factor_func(price_df) → 返回因子值 Series（index=行业名, value=因子值）
    在每个月的月度调仓点上，计算因子值和下个月收益的 cross-sectional Spearman 相关
    """
    monthly = price_df.resample(freq).last().dropna(how='all', axis=1)
    # 下个月收益
    forward_ret = monthly.pct_change().shift(-1)  # t月看t+1月收益

    ic_list = []
    ic_dates = []

    for i in range(len(monthly) - 1):
        date = monthly.index[i]
        next_date = monthly.index[i + 1]
        if next_date not in forward_ret.index:
            continue

        # 当前月的截面因子值
        factor_vals = factor_func(price_df, date)
        if factor_vals is None or len(factor_vals) < 5:
            continue

        # 下个月收益
        rets = forward_ret.loc[date]

        # 对齐两个 Series
        common = factor_vals.dropna().index.intersection(rets.dropna().index)
        if len(common) < 5:
            continue

        f = factor_vals[common]
        r = rets[common]
        # Rank IC：Spearman 秩相关
        rank_ic = f.rank().corr(r.rank(), method='spearman')
        ic_list.append(rank_ic)
        ic_dates.append(date)

    ic_series = pd.Series(ic_list, index=ic_dates, name=factor_name)
    return ic_series


# ─── 因子构造函数 ───

def factor_momentum(price_df, date, window=12):
    """动量因子：过去 N 个月的累计收益"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    if date not in monthly.index:
        return None
    iloc = monthly.index.get_loc(date)
    if iloc < window:
        return None
    prev = monthly.iloc[iloc - window]
    cur = monthly.iloc[iloc]
    return (cur / prev - 1)


def factor_low_vol(price_df, date, window=12):
    """低波因子：过去 N 个月日收益波动率的倒数"""
    # 用日数据计算
    end = date
    start_d = date - pd.DateOffset(months=window)
    d = price_df.loc[start_d:end]
    if len(d) < 20:
        return None
    vol = d.pct_change().dropna().std() * np.sqrt(252)
    return 1.0 / vol.replace(0, np.nan)


def factor_value(price_df, date, window=12):
    """简单价值因子：价格 vs 过去N月均线（高=低估）"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    if date not in monthly.index:
        return None
    iloc = monthly.index.get_loc(date)
    if iloc < window:
        return None
    ma = monthly.iloc[iloc - window:iloc].mean()
    cur = monthly.iloc[iloc]
    return (cur - ma) / ma


# ═══ 包一层兼容 calc_ic 接口 ═══

def make_momentum_ic(window):
    def fn(price_df, date):
        return factor_momentum(price_df, date, window)
    return fn, f'动量_{window}m'


def make_lowvol_ic(window):
    def fn(price_df, date):
        return factor_low_vol(price_df, date, window)
    return fn, f'低波_{window}m'


def make_value_ic(window):
    def fn(price_df, date):
        return factor_value(price_df, date, window)
    return fn, f'价值_{window}m'


# ════════════════════════════════════════
# 主流程
# ════════════════════════════════════════

print('=' * 60)
print('Factor IC Analysis — 申万一级行业')
print('=' * 60)

print('\n📥 加载数据...')
price_df = load_all_industry_prices()
print(f'  行业数: {price_df.shape[1]}, 日期范围: {price_df.index[0].date()} ~ {price_df.index[-1].date()}')

# 定义要计算的因子
factors = [
    make_momentum_ic(1),
    make_momentum_ic(3),
    make_momentum_ic(6),
    make_momentum_ic(12),
    make_lowvol_ic(6),
    make_lowvol_ic(12),
    make_value_ic(6),
    make_value_ic(12),
]

results = {}
print('\n📊 计算月度 IC...')
for fn, name in factors:
    ic_series = calc_ic(price_df, fn, name)
    if ic_series is not None and len(ic_series) > 5:
        results[name] = ic_series
        # 统计
        mean_ic = ic_series.mean()
        std_ic = ic_series.std()
        icir = mean_ic / std_ic if std_ic != 0 else 0
        positive_ratio = (ic_series > 0).mean() * 100
        t_stat = mean_ic / (std_ic / np.sqrt(len(ic_series))) if std_ic > 0 else 0
        print(f'  {name:　>12s}  IC={mean_ic:+.4f}  ICIR={icir:+.3f}  t_stat={t_stat:+.2f}  >0%={positive_ratio:.0f}%  n={len(ic_series)}')
    else:
        print(f'  {name:　>12s}  ❌ 计算失败或无数据')

# ═══ IC 时间序列图 ═══
print('\n📈 绘制 IC 时间序列...')

fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

# 上：动量各窗口
ax = axes[0]
mom_factors = [k for k in results if '动量' in k]
colors = ['#2196F3', '#4CAF50', '#FF9800', '#F44336']
for i, name in enumerate(mom_factors):
    ic = results[name]
    ax.plot(ic.index, ic.values, alpha=0.7, label=name, color=colors[i % len(colors)])
    # 滚动12期均值
    ma = ic.rolling(12).mean()
    ax.plot(ma.index, ma.values, color=colors[i % len(colors)], linewidth=2, alpha=0.9)
    # IC均值线
    ax.axhline(y=ic.mean(), color=colors[i % len(colors)], linestyle='--', alpha=0.5)

ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
ax.legend(loc='upper left')
ax.set_ylabel('Rank IC')
ax.set_title('动量因子 Rank IC 时间序列（实线=滚动12期均值）')
ax.grid(True, alpha=0.3)

# 下：各因子对比（保留动量最强窗口 + 低波 + 价值）
ax = axes[1]
selected = ['动量_12m', '动量_6m', '低波_12m', '价值_12m']
available = [s for s in selected if s in results]
colors2 = ['#F44336', '#FF9800', '#2196F3', '#4CAF50']
for i, name in enumerate(available):
    ic = results[name]
    ax.plot(ic.index, ic.values, alpha=0.5, label=name, color=colors2[i % len(colors2)])
    ma = ic.rolling(12).mean()
    ax.plot(ma.index, ma.values, color=colors2[i % len(colors2)], linewidth=2, alpha=0.9)

ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
ax.legend(loc='upper left')
ax.set_xlabel('日期')
ax.set_ylabel('Rank IC')
ax.set_title('多因子 IC 对比（12期滚动均值）')
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig_path = os.path.join(OUTPUT_DIR, 'factor_ic_timeseries.png')
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f'  ✅ IC 时间序列已保存: factor_ic_timeseries.png')

# ═══ 汇总表 ═══
print('\n📋 IC 汇总表')
print(f'{"因子":　>12s} | {"IC均值":>8s} | {"标准差":>8s} | {"ICIR":>6s} | {"t值":>7s} | {">0比率":>7s} | {"月数":>5s} | {"结论":>8s}')
print('-' * 75)

summary_rows = []
for name, ic in sorted(results.items()):
    mean_ic = ic.mean()
    std_ic = ic.std()
    icir = mean_ic / std_ic if std_ic != 0 else 0
    t_stat = mean_ic / (std_ic / np.sqrt(len(ic))) if std_ic > 0 else 0
    pos_ratio = (ic > 0).mean() * 100
    # 结论
    if abs(t_stat) > 2.0 and mean_ic > 0.01:
        conclusion = '✅ 有效'
    elif abs(t_stat) > 1.5 and mean_ic > 0.005:
        conclusion = '⚠️ 弱有效'
    else:
        conclusion = '❌ 无效'
    summary_rows.append({
        '因子': name, 'IC均值': round(mean_ic, 4),
        '标准差': round(std_ic, 4), 'ICIR': round(icir, 3),
        't值': round(t_stat, 2), '>0比率': f'{pos_ratio:.0f}%',
        '月数': len(ic), '结论': conclusion
    })
    print(f'{name:　>12s} | {mean_ic:>8.4f} | {std_ic:>8.4f} | {icir:>+6.3f} | {t_stat:>+7.2f} | {pos_ratio:>6.0f}% | {len(ic):>4d}  | {conclusion}')

df_summary = pd.DataFrame(summary_rows)
summary_path = os.path.join(OUTPUT_DIR, 'factor_ic_summary.csv')
df_summary.to_csv(summary_path, index=False, encoding='utf-8-sig')
print(f'\n  ✅ 汇总表已保存: factor_ic_summary.csv')

# ═══ 额外的：滚动 ICIR（看稳定性变化） ═══
print('\n📊 滚动 ICIR（24个月窗口）...')
fig, ax = plt.subplots(figsize=(14, 5))
for i, name in enumerate(['动量_12m', '动量_6m', '低波_12m', '价值_12m']):
    if name not in results:
        continue
    ic = results[name]
    rolling_icir = ic.rolling(24).apply(lambda x: x.mean() / x.std() if x.std() > 0 else 0)
    ax.plot(rolling_icir.index, rolling_icir.values, label=name, color=colors2[i], linewidth=1.5)

ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, label='ICIR=1')
ax.axhline(y=-1.0, color='gray', linestyle='--', alpha=0.5)
ax.legend(loc='upper left')
ax.set_ylabel('滚动 ICIR (24个月)')
ax.set_title('因子 ICIR 稳定性：随时间变化的预测能力')
ax.grid(True, alpha=0.3)
plt.tight_layout()

icir_path = os.path.join(OUTPUT_DIR, 'factor_icir_rolling.png')
plt.savefig(icir_path, dpi=150, bbox_inches='tight')
plt.close()
print(f'  ✅ 滚动 ICIR 已保存: factor_icir_rolling.png')

print('\n' + '=' * 60)
print('分析完成！')
print(f'  📎 factor_ic_timeseries.png')
print(f'  📎 factor_icir_rolling.png')
print(f'  📎 factor_ic_summary.csv')
print('=' * 60)
