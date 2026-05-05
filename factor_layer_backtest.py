"""
Phase 1 专题6（对标 Week 1 Day 5~6）：因子分层回测 + 相关性分析
==============================================================
内容：
1. 动量_12m 因子分层回测（分5组，看收益单调性）
2. 价值_12m 因子分层回测
3. 多空组合（Top - Bottom）表现
4. 因子相关性矩阵（动量 vs 低波 vs 价值）
5. 组间收益差异的统计检验
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


# ════════════════════════════════════════
# 1. 因子分层回测
# ════════════════════════════════════════

def factor_layer_backtest(price_df, factor_func, factor_name, n_groups=5):
    """
    因子分层回测。
    每月末按因子值分 n_groups 组，等权持有组内行业，下月调仓。
    返回：各组净值曲线 + 分组收益表 + 统计指标
    """
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    dates = monthly.index.tolist()

    navs = {f'Group {g+1}': [1.0] for g in range(n_groups)}
    navs['Long-Short'] = [1.0]
    navs['Equal-Weight'] = [1.0]
    nav_dates = [dates[0]]

    for i in range(1, len(dates)):
        prev_date = dates[i-1]
        cur_date = dates[i]

        # 当前因子值
        factor_vals = factor_func(price_df, prev_date)
        if factor_vals is None:
            for k in navs:
                navs[k].append(navs[k][-1])
            nav_dates.append(cur_date)
            continue

        # 行业按月分组
        sorted_vals = factor_vals.dropna().sort_values()
        if len(sorted_vals) < n_groups:
            for k in navs:
                navs[k].append(navs[k][-1])
            nav_dates.append(cur_date)
            continue

        group_size = len(sorted_vals) // n_groups
        groups = []
        for g in range(n_groups):
            if g == n_groups - 1:
                members = sorted_vals.index[g * group_size:]
            else:
                members = sorted_vals.index[g * group_size:(g + 1) * group_size]
            groups.append(members)

        # 各组收益
        if prev_date not in monthly.index or cur_date not in monthly.index:
            for k in navs:
                navs[k].append(navs[k][-1])
            nav_dates.append(cur_date)
            continue

        prev_prices = monthly.loc[prev_date]
        cur_prices = monthly.loc[cur_date]

        for g in range(n_groups):
            members = groups[g]
            available = [m for m in members if m in prev_prices.index and m in cur_prices.index]
            if len(available) == 0:
                navs[f'Group {g+1}'].append(navs[f'Group {g+1}'][-1])
            else:
                rets = (cur_prices[available].values / prev_prices[available].values) - 1
                g_ret = np.nanmean(rets)
                navs[f'Group {g+1}'].append(navs[f'Group {g+1}'][-1] * (1 + g_ret))

        # 多空组合（Top - Bottom）
        g5_prev = prev_prices[groups[-1]]
        g5_cur = cur_prices[groups[-1]]
        g1_prev = prev_prices[groups[0]]
        g1_cur = cur_prices[groups[0]]
        available_top = [m for m in groups[-1] if m in prev_prices.index and m in cur_prices.index]
        available_bot = [m for m in groups[0] if m in prev_prices.index and m in cur_prices.index]
        ret_top = np.nanmean((cur_prices[available_top].values / prev_prices[available_top].values) - 1) if len(available_top) > 0 else 0
        ret_bot = np.nanmean((cur_prices[available_bot].values / prev_prices[available_bot].values) - 1) if len(available_bot) > 0 else 0
        navs['Long-Short'].append(navs['Long-Short'][-1] * (1 + ret_top - ret_bot))

        # 等权基准
        all_rets = (cur_prices.values / prev_prices.values) - 1
        ew_ret = np.nanmean(all_rets)
        navs['Equal-Weight'].append(navs['Equal-Weight'][-1] * (1 + ew_ret))

        nav_dates.append(cur_date)

    # 整理结果
    result_df = pd.DataFrame(navs, index=nav_dates)
    result_df.index.name = '日期'

    # 统计指标
    stats = {}
    for col in result_df.columns:
        nav = result_df[col]
        total_ret = (nav.iloc[-1] / nav.iloc[0]) - 1
        years = (nav.index[-1] - nav.index[0]).days / 365.25
        ann_ret = nav.iloc[-1] ** (1 / years) - 1 if nav.iloc[0] > 0 else 0
        dd = (nav / nav.cummax() - 1)
        max_dd = dd.min()
        # 年化波动率
        monthly_rets = nav.pct_change().dropna()
        ann_vol = monthly_rets.std() * np.sqrt(12)
        sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0
        stats[col] = {
            '总收益': total_ret, '年化收益': ann_ret,
            '最大回撤': max_dd, '年化波动': ann_vol,
            '夏普比率': sharpe
        }

    return result_df, stats


# 因子构造函数（复用）
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


def factor_value(price_df, date, window=12):
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    if date not in monthly.index:
        return None
    iloc = monthly.index.get_loc(date)
    if iloc < window:
        return None
    ma = monthly.iloc[iloc - window:iloc].mean()
    cur = monthly.iloc[iloc]
    return (cur - ma) / ma


def factor_low_vol(price_df, date, window=12):
    end = date
    start_d = date - pd.DateOffset(months=window)
    d = price_df.loc[start_d:end]
    if len(d) < 20:
        return None
    vol = d.pct_change().dropna().std() * np.sqrt(252)
    return 1.0 / vol.replace(0, np.nan)


# ════════════════════════════════════════
# 2. 因子相关性分析
# ════════════════════════════════════════

def factor_correlation(price_df, start='2015-01-01', end='2026-04-30'):
    """计算各因子在每个月截面的平均相关系数"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    dates = monthly.index.tolist()

    factor_values = {
        '动量_12m': [],
        '动量_6m': [],
        '动量_3m': [],
        '价值_12m': [],
        '价值_6m': [],
        '低波_12m': [],
        '低波_6m': [],
    }
    factor_dates = []

    for i, date in enumerate(dates):
        m12 = factor_momentum(price_df, date, 12)
        m6 = factor_momentum(price_df, date, 6)
        m3 = factor_momentum(price_df, date, 3)
        v12 = factor_value(price_df, date, 12)
        v6 = factor_value(price_df, date, 6)
        lv12 = factor_low_vol(price_df, date, 12)
        lv6 = factor_low_vol(price_df, date, 6)

        vals = {'动量_12m': m12, '动量_6m': m6, '动量_3m': m3,
                '价值_12m': v12, '价值_6m': v6,
                '低波_12m': lv12, '低波_6m': lv6}

        # 检查是否有缺失或None
        valid = True
        for k in vals:
            if vals[k] is None:
                valid = False
                break
        if not valid:
            continue

        for k in vals:
            factor_values[k].append(vals[k])

        factor_dates.append(date)

    # 计算每月的correlation
    correlations = {}
    factor_names = list(factor_values.keys())
    for i, name1 in enumerate(factor_names):
        for j, name2 in enumerate(factor_names):
            if i >= j:
                continue
            corr_list = []
            for t in range(len(factor_dates)):
                f1 = factor_values[name1][t]
                f2 = factor_values[name2][t]
                if f1 is None or f2 is None:
                    continue
                common = f1.dropna().index.intersection(f2.dropna().index)
                if len(common) < 5:
                    continue
                corr = f1[common].corr(f2[common], method='pearson')
                corr_list.append(corr)
            if len(corr_list) > 0:
                correlations[f'{name1} vs {name2}'] = {
                    '均值': np.mean(corr_list),
                    '中位数': np.median(corr_list),
                    '标准差': np.std(corr_list),
                    '>0比例': np.mean([c > 0 for c in corr_list]) * 100,
                }

    return correlations


# ════════════════════════════════════════
# 主流程
# ════════════════════════════════════════

print('=' * 60)
print('因子分层回测 + 相关性分析')
print('=' * 60)

print('\n📥 加载数据...')
price_df = load_all_industry_prices()
print(f'  行业数: {price_df.shape[1]}, 日期: {price_df.index[0].date()} ~ {price_df.index[-1].date()}')

# ═══ 因子分层回测 ═══

factors_to_test = [
    (lambda pd, d: factor_momentum(pd, d, 12), '动量_12m'),
    (lambda pd, d: factor_value(pd, d, 12), '价值_12m'),
    (lambda pd, d: factor_low_vol(pd, d, 12), '低波_12m'),
]

fig, axes = plt.subplots(1, 3, figsize=(18, 5))

all_stats = {}

for idx, (fn, name) in enumerate(factors_to_test):
    print(f'\n📊 分层回测: {name}')

    # 分层动量_12m 使用每年因子值，不是月度
    if name == '动量_12m':
        # 直接计算每个月的因子值并分rank
        result_df, stats = factor_layer_backtest(price_df, fn, name)
    else:
        result_df, stats = factor_layer_backtest(price_df, fn, name)

    all_stats[name] = stats

    # 打印
    for group, s in stats.items():
        print(f'  {group:15s}  总收益={s["总收益"]*100:>+7.2f}%  年化={s["年化收益"]*100:>+5.2f}%  '
              f'回撤={s["最大回撤"]*100:>+5.1f}%  夏普={s["夏普比率"]:>+5.2f}')

    # 绘图
    ax = axes[idx]
    colors = ['#2196F3', '#4CAF50', '#FF9800', '#F44336', '#9C27B0', '#795548', '#607D8B']
    for i, col in enumerate(result_df.columns):
        if col == 'Equal-Weight':
            ax.plot(result_df.index, result_df[col] / result_df[col].iloc[0],
                    label=col, color='black', linewidth=2, linestyle='--')
        elif col == 'Long-Short':
            ax.plot(result_df.index, result_df[col],
                    label=col, color='#FF5722', linewidth=2)
        else:
            ax.plot(result_df.index, result_df[col] / result_df[col].iloc[0],
                    label=col, color=colors[i % len(colors)], alpha=0.8)

    ax.axhline(y=1, color='gray', linestyle='-', linewidth=0.5)
    ax.set_title(f'{name} 分层收益', fontsize=11)
    ax.set_ylabel('净值')
    ax.legend(loc='upper left', fontsize=7)
    ax.grid(True, alpha=0.3)

plt.tight_layout()
fig_path = os.path.join(OUTPUT_DIR, 'factor_layer_backtest.png')
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f'\n  ✅ 分层回测图已保存: factor_layer_backtest.png')

# ═══ 因子相关性分析 ═══
print('\n📊 因子截面相关性分析...')
corr_dict = factor_correlation(price_df)

print(f'\n{"因子对":40s} | {"均值":>6s} | {"中位数":>6s} | {"标准差":>6s} | {">0比":>5s}')
print('-' * 75)
for pair, vals in sorted(corr_dict.items()):
    print(f'{pair:40s} | {vals["均值"]:>+6.3f} | {vals["中位数"]:>+6.3f} | {vals["标准差"]:>6.3f} | {vals[">0比例"]:>4.0f}%')

# 用热力图可视化
print('\n📈 绘制因子相关性热力图...')
# 构建平均相关矩阵
factor_names_unique = ['动量_12m', '动量_6m', '动量_3m', '价值_12m', '价值_6m', '低波_12m', '低波_6m']
n = len(factor_names_unique)
corr_matrix = np.eye(n)
for i in range(n):
    for j in range(i+1, n):
        key = f'{factor_names_unique[i]} vs {factor_names_unique[j]}'
        key2 = f'{factor_names_unique[j]} vs {factor_names_unique[i]}'
        if key in corr_dict:
            corr_matrix[i, j] = corr_matrix[j, i] = corr_dict[key]['均值']
        elif key2 in corr_dict:
            corr_matrix[i, j] = corr_matrix[j, i] = corr_dict[key2]['均值']
        else:
            corr_matrix[i, j] = corr_matrix[j, i] = 0

fig, ax = plt.subplots(figsize=(8, 7))
im = ax.imshow(corr_matrix, cmap='RdBu_r', vmin=-0.5, vmax=0.5, aspect='auto')
ax.set_xticks(range(n))
ax.set_yticks(range(n))
ax.set_xticklabels(factor_names_unique, rotation=45, ha='right', fontsize=9)
ax.set_yticklabels(factor_names_unique, fontsize=9)

# 显示数值
for i in range(n):
    for j in range(n):
        text = ax.text(j, i, f'{corr_matrix[i, j]:+.2f}',
                      ha='center', va='center', fontsize=8,
                      color='white' if abs(corr_matrix[i, j]) > 0.3 else 'black')

plt.title('因子截面相关性热力图（月度均值）', fontsize=12)
plt.colorbar(im, ax=ax, shrink=0.8)
plt.tight_layout()
heat_path = os.path.join(OUTPUT_DIR, 'factor_correlation_heatmap.png')
plt.savefig(heat_path, dpi=150, bbox_inches='tight')
plt.close()
print(f'  ✅ 热力图已保存: factor_correlation_heatmap.png')

# ═══ 单调性检验 ═══
print('\n📊 单调性检验：各组年化收益')

fig2, axes2 = plt.subplots(1, 3, figsize=(18, 5))
for idx, (fn, name) in enumerate(factors_to_test):
    stats = all_stats[name]
    groups = [f'Group {i+1}' for i in range(5)]
    ann_rets = [stats[g]['年化收益'] * 100 for g in groups if g in stats]
    dd = [stats[g]['最大回撤'] * 100 for g in groups if g in stats]

    ax = axes2[idx]
    x = range(len(ann_rets))
    bars1 = ax.bar([i - 0.15 for i in x], ann_rets, width=0.3, color='#4CAF50', alpha=0.8, label='年化收益')
    ax2_twin = ax.twinx()
    bars2 = ax2_twin.bar([i + 0.15 for i in x], dd, width=0.3, color='#F44336', alpha=0.6, label='最大回撤')

    ax.set_xlabel('分组 (1=因子最低, 5=因子最高)')
    ax.set_ylabel('年化收益 (%)', color='#4CAF50')
    ax2_twin.set_ylabel('最大回撤 (%)', color='#F44336')
    ax.set_xticks(list(range(5)))
    ax.set_xticklabels([f'Q{i+1}' for i in range(5)])
    ax.set_title(f'{name}\n单调性检验', fontsize=11)
    ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
    ax.grid(True, alpha=0.3)

plt.tight_layout()
mono_path = os.path.join(OUTPUT_DIR, 'factor_monotonicity.png')
plt.savefig(mono_path, dpi=150, bbox_inches='tight')
plt.close()
print(f'  ✅ 单调性图已保存: factor_monotonicity.png')

print('\n' + '=' * 60)
print('分析完成！')
print(f'  📎 factor_layer_backtest.png')
print(f'  📎 factor_correlation_heatmap.png')
print(f'  📎 factor_monotonicity.png')
print('=' * 60)
