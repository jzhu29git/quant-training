"""Phase 1 多因子/动量 收益曲线对比图"""
import sys, io, os, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import akshare as ak
import time

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'sw_cache')

def load_sw_data(start='2015-01-01', end='2026-04-30'):
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
            df = df.set_index('date').sort_index()
            df = df.loc[start:end]
            if len(df) > 100:
                name_row = df_info[df_info['行业代码'].str.contains(code)]
                cname = name_row['行业名称'].values[0] if len(name_row) > 0 else code
                prices[code] = df['收盘'].rename(cname)
        except:
            pass
    price_df = pd.DataFrame(prices).dropna(how='all')
    return price_df


def compute_strategy_curve(price_df, is_multi_factor, topk, momentum_months):
    """计算策略的净值曲线（月末）"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)

    if is_multi_factor:
        # 多因子
        # 动量
        mom_ret = monthly.pct_change(periods=momentum_months)
        mom_rank = mom_ret.rank(axis=1, ascending=True, pct=True).fillna(0.5)

        # 低波
        vol_scores = {}
        for col in price_df.columns:
            dr = price_df[col].pct_change().dropna()
            vol = dr.groupby(pd.Grouper(freq='ME')).std() * np.sqrt(252)
            vol = vol.rolling(momentum_months, min_periods=1).mean()
            vol_scores[col] = 1.0 / vol.replace(0, np.nan)
        vol_df = pd.DataFrame(vol_scores)
        vol_rank = vol_df.rank(axis=1, ascending=True, pct=True).fillna(0.5)
        vol_rank = vol_rank.reindex(monthly.index).ffill()

        # 价值
        val_scores = {}
        for col in price_df.columns:
            ma250 = price_df[col].rolling(250).mean()
            val_scores[col] = (price_df[col] - ma250) / ma250
        val_df = pd.DataFrame(val_scores)
        val_m = val_df.resample('ME').last()
        value_rank = val_m.rank(axis=1, ascending=False, pct=True).fillna(0.5)
        value_rank = value_rank.reindex(monthly.index).ffill()

        total_score = mom_rank * 1/3 + vol_rank * 1/3 + value_rank * 1/3
    else:
        # 纯动量
        mom_ret = monthly.pct_change(periods=momentum_months)
        total_score = mom_ret.rank(axis=1, ascending=True, pct=True).fillna(0.5)

    val = 1.0
    curve = {}
    dates = total_score.index.tolist()

    for i in range(1, len(dates)):
        prev_date = dates[i-1]
        cur_date = dates[i]

        if prev_date not in total_score.index or cur_date not in monthly.index:
            curve[cur_date] = val
            continue

        scores = total_score.loc[prev_date]
        top_cols = scores.nlargest(topk).index.tolist()

        if prev_date not in monthly.index or cur_date not in monthly.index:
            curve[cur_date] = val
            continue

        p_prev = monthly.loc[prev_date, top_cols].values
        p_cur = monthly.loc[cur_date, top_cols].values
        p_prev = np.where(p_prev == 0, np.nan, p_prev)
        rets = (p_cur / p_prev) - 1
        port_ret = np.nanmean(rets)
        if np.isnan(port_ret):
            port_ret = 0
        val *= (1 + port_ret)
        curve[cur_date] = val

    return pd.Series(curve).sort_index()


def compute_ew_curve(price_df):
    """等权基准"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    val = 1.0
    curve = {}
    dates = monthly.index.tolist()
    for i in range(1, len(dates)):
        rets = (monthly.iloc[i].values / monthly.iloc[i-1].values) - 1
        port_ret = np.nanmean(rets)
        val *= (1 + port_ret)
        curve[dates[i]] = val
    return pd.Series(curve).sort_index()


def compute_hs300_curve():
    """沪深300买入持有"""
    df = pd.read_pickle('sh000300_cache.pkl')
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.sort_index()
    df = df.loc['2015-01-01':'2026-04-30']
    val = df['close'] / df['close'].iloc[0]
    return val


# ════════════════════════════════════════
# 主流程
# ════════════════════════════════════════
print('📥 加载数据...', flush=True)
price_df = load_sw_data()
print(f'  {price_df.shape[1]} 个行业, {price_df.shape[0]} 个交易日')

# 定义要计算的策略
strategies = [
    ('纯动量_12m_top5', False, 5, 12),
    ('多因子_12m_top5', True, 5, 12),
    ('纯动量_6m_top10', False, 10, 6),
    ('纯动量_6m_top5', False, 5, 6),
    ('多因子_6m_top5', True, 5, 6),
]

curves = {}

# 基准
print('📊 计算基准...', flush=True)
curves['申万行业等权'] = compute_ew_curve(price_df)
curves['沪深300'] = compute_hs300_curve()

# 策略
for name, is_mf, topk, mom_m in strategies:
    print(f'  {name}...', flush=True)
    curves[name] = compute_strategy_curve(price_df, is_mf, topk, mom_m)

# ── 画图 ──
print('🎨 生成图表...', flush=True)

fig, ax = plt.subplots(figsize=(16, 9))

# 颜色方案
colors = {
    '沪深300': '#999999',
    '申万行业等权': '#555555',
    '纯动量_12m_top5': '#E63946',
    '多因子_12m_top5': '#F4A261',
    '纯动量_6m_top10': '#2A9D8F',
    '纯动量_6m_top5': '#264653',
    '多因子_6m_top5': '#8ECAE6',
}
styles = {
    '沪深300': '--',
    '申万行业等权': '-.',
}

# 每一行只显示策略名称，但图例上加上绩效指标
label_map = {
    '沪深300': '沪深300买入持有',
    '申万行业等权': '申万行业等权',
}

for name, series in curves.items():
    if len(series) == 0:
        continue

    color = colors.get(name, '#000000')
    style = styles.get(name, '-')
    lw = 2.5 if '动量' in name or '多因子' in name else 1.5
    alpha = 0.9 if '动量' in name or '多因子' in name else 0.6

    # 总收益
    total_ret = (series.iloc[-1] - 1) * 100
    label = f'{name} ({total_ret:+.1f}%)'

    ax.plot(series.index.to_pydatetime(), series.values * 100,
            color=color, linestyle=style, linewidth=lw, alpha=alpha, label=label)

ax.axhline(y=100, color='#333', linestyle=':', linewidth=0.8, alpha=0.5)
ax.set_ylabel('总收益率 (%)', fontsize=12)
ax.set_xlabel('日期', fontsize=12)
ax.set_title('Phase 1 多因子/动量策略收益曲线对比 (2015-2026)', fontsize=14, fontweight='bold')

ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax.legend(loc='upper left', fontsize=9, framealpha=0.9)
ax.grid(True, alpha=0.3)

plt.tight_layout()
out_path = os.path.join(os.path.dirname(__file__), 'phase1_curves.png')
fig.savefig(out_path, dpi=150, bbox_inches='tight')
plt.close()

print(f'\n✅ 图已保存: {out_path}')
print(f'   {curves["纯动量_12m_top5"].iloc[-1]*100-100:.1f}% (纯动量12m)')
print(f'   {curves["申万行业等权"].iloc[-1]*100-100:.1f}% (等权基准)')
print(f'   {curves["沪深300"].iloc[-1]*100-100:.1f}% (沪深300)')
