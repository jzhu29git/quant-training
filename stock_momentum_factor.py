"""
中证500个股动量因子分层回测（完整版）
- 动量_3m / 动量_6m / 动量_12m
- 每月末截面排序分5组
- 次月首日开盘买入，等权持有，每月调仓

输出：完整 Q1-Q5 收益对比 + 3/6/12m 三组对比图
"""

import os, pickle, time, warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "stock_cache")
OUTPUT_IMG = os.path.join(BASE_DIR, "phase2_stock_momentum.png")
START_DATE, END_DATE = "2018-01-01", "2026-04-30"
LOOKBACKS = {'3m': 63, '6m': 126, '12m': 252}

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.family'] = 'sans-serif'

COLORS = ['#e41a1c','#377eb8','#4daf4a','#984ea3','#ff7f00']
QNAMES = ['Q1(最高动量)', 'Q2', 'Q3', 'Q4', 'Q5(最低动量)']
TOPK_N = 10
EPS = 1e-8

# ====== 数据加载 ======
def load_cached_stocks(cache_dir):
    """从缓存加载所有已下载的股票数据"""
    codes = [f.replace('.pkl','') for f in os.listdir(cache_dir) if f.endswith('.pkl') and f != '_benchmark_zz500.pkl']
    all_data = {}
    for code in codes:
        try:
            df = pickle.load(open(os.path.join(cache_dir, f"{code}.pkl"), 'rb'))
            if df is not None and len(df) > 200:
                all_data[code] = df
        except:
            pass
    print(f"[数据] 从缓存加载 {len(all_data)} 只股票")
    return all_data

def load_benchmark():
    """加载或获取中证500基准"""
    cache_file = os.path.join(CACHE_DIR, "_benchmark_zz500.pkl")
    if os.path.exists(cache_file):
        df = pickle.load(open(cache_file, 'rb'))
        print(f"[基准] 从缓存加载中证500, {len(df)} 行")
        return df
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol="sh000905")
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    pickle.dump(df, open(cache_file, 'wb'))
    print(f"[基准] 已下载中证500, {len(df)} 行")
    return df

# ====== 因子计算 ======
def get_month_ends(all_data, start, end):
    """获取回测期内每月最后一个交易日"""
    all_dates = []
    for df in all_data.values():
        all_dates.extend(df['date'].dt.date.tolist())
    dates = pd.Series(pd.to_datetime(sorted(set(all_dates))))
    ym = dates.map(lambda x: (x.year, x.month))
    month_ends = {g: grp.max() for g, grp in dates.groupby(ym)}
    start_dt, end_dt = pd.Timestamp(start), pd.Timestamp(end)
    valid = sorted([v for k, v in month_ends.items() if start_dt <= v <= end_dt])
    return valid

def compute_all_factors(all_data, month_ends):
    """计算3m/6m/12m动量因子"""
    print("\n[因子] 计算动量因子...")
    ret_data = {code: df.set_index('date')['close'].pct_change() for code, df in all_data.items()}
    
    factors = {}
    for name, lb in LOOKBACKS.items():
        factors[name] = []
    
    for idx, me in enumerate(month_ends):
        if (idx+1) % 30 == 0:
            print(f"  进度: {idx+1}/{len(month_ends)}")
        
        fvals = {name: {} for name in LOOKBACKS}
        for code, ret in ret_data.items():
            try:
                pos = ret.index.get_loc(me)
            except (KeyError, TypeError):
                continue
            for name, lb in LOOKBACKS.items():
                if pos >= lb:
                    fvals[name][code] = (1 + ret.iloc[pos-lb+1:pos+1]).prod() - 1
        for name in LOOKBACKS:
            factors[name].append(pd.Series(fvals[name], name=me))
    
    factor_dfs = {}
    for name in LOOKBACKS:
        df = pd.concat(factors[name], axis=1).T
        print(f"  {name}: {df.shape}")
        factor_dfs[name] = df
    return factor_dfs

# ====== 回测 ======
def backtest_factor(factor_df, all_data, month_ends):
    """单个因子的分组回测，返回每个Q的月度收益"""
    open_prices = {code: df.set_index('date')['open'] for code, df in all_data.items()}
    all_dates = sorted(set(
        pd.Timestamp(d) for data in all_data.values() for d in data['date']))
    
    group_rets = {g: [] for g in [1,2,3,4,5]}
    months_label = []
    
    for i in range(len(month_ends)-1):
        me, nme = month_ends[i], month_ends[i+1]
        months_label.append(f"{me.year}-{me.month:02d}")
        
        vals = factor_df.loc[me].dropna()
        if len(vals) < 20:
            continue
        
        sorted_codes = vals.sort_values(ascending=False)
        n = len(sorted_codes)
        gs = n // 5
        groups = {g: sorted_codes.iloc[(g-1)*gs: g*gs if g<5 else n].index.tolist()
                  for g in [1,2,3,4,5]}
        
        for g in [1,2,3,4,5]:
            rets = []
            for code in groups[g]:
                op = open_prices.get(code)
                if op is None:
                    continue
                entry = [d for d in all_dates if d > me]
                exit_ = [d for d in all_dates if d > nme]
                if not entry or not exit_:
                    continue
                try:
                    ep = op.loc[entry[0]]
                    xp = op.loc[exit_[0]]
                    if ep > 0:
                        rets.append(xp/ep - 1)
                except KeyError:
                    continue
            group_rets[g].append(np.mean(rets) if rets else 0.0)
    
    navs = {}
    for g in [1,2,3,4,5]:
        nav = [1.0]
        for r in group_rets[g]:
            nav.append(nav[-1] * (1+r))
        navs[g] = np.array(nav[1:])
    
    ls_rets = [group_rets[1][i] - group_rets[5][i] for i in range(len(group_rets[1]))]
    ls_nav = [1.0]
    for r in ls_rets:
        ls_nav.append(ls_nav[-1]*(1+r))
    
    return {
        'months': months_label,
        'navs': navs,
        'group_rets': group_rets,
        'ls_rets': ls_rets,
        'ls_nav': np.array(ls_nav[1:]),
    }

def calc_stats(monthly_rets):
    rets = np.array(monthly_rets, dtype=float)
    n = len(rets)
    if n == 0: return {}
    total = np.prod(1+rets) - 1
    ann = (1+total)**(12/n) - 1
    vol = np.std(rets, ddof=1)*np.sqrt(12) if n>1 else 0
    cum = np.cumprod(1+rets)
    dd = (cum - np.maximum.accumulate(cum)) / np.maximum.accumulate(cum)
    mdd = np.min(dd) if len(dd)>0 else 0
    sr = (np.mean(rets)/np.std(rets, ddof=1)*np.sqrt(12)) if np.std(rets,ddof=1)>1e-10 else 0
    wr = np.mean(rets>0)
    return {'总收益': total, '年化': ann, '年化波动': vol, '最大回撤': mdd, '夏普': sr, '月胜率': wr, '月数': n, '终值': total + 1}

def sanity_check_stats(name, monthly_rets, nav_series=None):
    rets = np.array(monthly_rets, dtype=float)
    if len(rets) == 0:
        raise ValueError(f'[{name}] 月度收益为空')
    stats_dict = calc_stats(rets)
    final_from_total = 1 + stats_dict['总收益']
    final_from_prod = float(np.prod(1 + rets))
    if abs(final_from_total - final_from_prod) > 1e-8:
        raise AssertionError(f'[{name}] 总收益与终值不一致: total->{final_from_total:.6f}, prod->{final_from_prod:.6f}')
    ann_recalc = final_from_prod ** (12 / len(rets)) - 1
    if abs(ann_recalc - stats_dict['年化']) > 1e-10:
        raise AssertionError(f'[{name}] 年化与终值不一致: calc->{ann_recalc:.8f}, stats->{stats_dict["年化"]:.8f}')
    if nav_series is not None and len(nav_series) > 0:
        nav_last = float(np.array(nav_series)[-1])
        if abs(nav_last - final_from_prod) > 1e-6:
            raise AssertionError(f'[{name}] 图上净值终点与收益计算不一致: nav->{nav_last:.6f}, prod->{final_from_prod:.6f}')
        if np.any(np.array(nav_series) <= 0):
            raise AssertionError(f'[{name}] 净值序列出现非正值')
    return stats_dict

def sanity_check_benchmark(bench_df, bench_rets, start_date, end_date, expected_months=None):
    bench_df = bench_df.copy()
    bench_df['date'] = pd.to_datetime(bench_df['date'])
    filtered = bench_df[(bench_df['date'] >= pd.Timestamp(start_date)) & (bench_df['date'] <= pd.Timestamp(end_date))].copy()
    if filtered.empty:
        raise AssertionError('[基准] 过滤后为空，请检查时间范围')
    monthly_close = filtered.set_index('date')['close'].resample('ME').last()
    expected_rets = monthly_close.pct_change().dropna().tolist()
    if len(expected_rets) != len(bench_rets):
        raise AssertionError(f'[基准] 月收益长度不一致: expected={len(expected_rets)}, got={len(bench_rets)}')
    expected_final = float((1 + pd.Series(expected_rets)).prod())
    got_final = float((1 + pd.Series(bench_rets)).prod())
    if abs(expected_final - got_final) > 1e-8:
        raise AssertionError(f'[基准] 时间范围可能错位: expected_final={expected_final:.6f}, got_final={got_final:.6f}')
    if expected_months is not None and abs(len(bench_rets) - expected_months) > 2:
        raise AssertionError(f'[基准] 月数异常: benchmark={len(bench_rets)}, strategy≈{expected_months}')
    return True

def get_topk_latest(factor_df, topk=10):
    latest_date = factor_df.index.max()
    latest = factor_df.loc[latest_date].dropna().sort_values(ascending=False)
    picks = latest.head(topk)
    return latest_date, picks

def print_full_table(name, result, bench_rets=None):
    print(f"\n{'='*120}")
    print(f"  {name}")
    print(f"{'='*120}")
    header = f"{'分组':>6} | {'总收益':>10} | {'年化':>10} | {'年化波动':>10} | {'最大回撤':>10} | {'夏普':>8} | {'月胜率':>8}"
    print(header)
    print("-"*90)
    for g in [1,2,3,4,5]:
        s = sanity_check_stats(f'{name}-Q{g}', result['group_rets'][g], result['navs'][g])
        print(f"{f'Q{g}':>6} | {s['总收益']:>9.2%} | {s['年化']:>9.2%} | {s['年化波动']:>9.2%} | {s['最大回撤']:>9.2%} | {s['夏普']:>8.3f} | {s['月胜率']:>7.2%}")
    
    ls = sanity_check_stats(f'{name}-LS', result['ls_rets'], result['ls_nav'])
    t_stat, p_val = stats.ttest_1samp(result['ls_rets'], 0)
    print(f"\n  多空(Q1-Q5): 年化{ls['年化']:.2%} 夏普{ls['夏普']:.3f} 回撤{ls['最大回撤']:.2%} 胜率{ls['月胜率']:.2%}")
    print(f"  t={t_stat:.3f} p={p_val:.6f} {'显著' if p_val<0.05 else '不显著'}")
    
    if bench_rets is not None:
        bs = sanity_check_stats('Benchmark', bench_rets)
        print(f"\n  中证500基准: 年化{bs['年化']:.2%} 夏普{bs['夏普']:.3f} 回撤{bs['最大回撤']:.2%}")

def plot_all(results_dict, bench_rets, months):
    """4x3 大图：每列是一个周期（3m/6m/12m），每行是净值/多空/年化柱状图"""
    fig, axes = plt.subplots(3, 4, figsize=(28, 18))
    
    period_names = ['动量_3m', '动量_6m', '动量_12m']
    period_keys = ['3m', '6m', '12m']
    
    # 年份刻度
    yr_ticks = [i for i,m in enumerate(months) if m.endswith('-01') or i==0]
    yr_labels = [months[i][:4] for i in yr_ticks]
    
    for col, (pk, pn) in enumerate(zip(period_keys, period_names)):
        res = results_dict[pk]
        
        # 行1: 分组净值曲线
        ax = axes[0, col]
        for g in [1,2,3,4,5]:
            ax.plot(res['navs'][g], color=COLORS[g-1], label=QNAMES[g-1], lw=1.5)
        if bench_rets is not None and len(bench_rets) >= len(months):
            bnav = np.cumprod(1 + np.array(bench_rets[:len(months)]))
            ax.plot(range(len(months)), bnav, color='gray', ls='--', lw=1.5, label='中证500')
        ax.set_title(f'{pn} Q1-Q5 净值曲线', fontsize=13, fontweight='bold')
        ax.legend(fontsize=8, loc='upper left')
        ax.grid(alpha=0.3)
        ax.set_xticks(yr_ticks); ax.set_xticklabels(yr_labels, rotation=45)
        
        # 行2: 多空组合净值
        ax = axes[1, col]
        ax.plot(res['ls_nav'], color='darkred', lw=2, label='多空(Q1-Q5)')
        ax.axhline(y=1, color='gray', ls='--', alpha=0.5)
        ax.set_title(f'{pn} 多空组合', fontsize=13, fontweight='bold')
        ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        ax.set_xticks(yr_ticks); ax.set_xticklabels(yr_labels, rotation=45)
        
        # 行3: 每个Q单独画（紧凑并排）
        ax = axes[2, col]
        for g in [1,2,3,4,5]:
            s = calc_stats(res['group_rets'][g])
            ann_ret = s['年化']
            ax.bar(g, ann_ret, color=COLORS[g-1], alpha=0.8, label=f'Q{g}: {ann_ret:.1%}')
            ax.text(g, ann_ret+(0.005 if ann_ret>=0 else -0.015),
                    f'{ann_ret:.1%}', ha='center', va='bottom' if ann_ret>=0 else 'top', fontsize=9)
        if bench_rets is not None:
            bs = calc_stats(bench_rets)
            ax.axhline(y=bs['年化'], color='gray', ls='--', lw=1.5, label=f'基准:{bs["年化"]:.1%}')
        ax.set_title(f'{pn} 各Q年化收益', fontsize=13, fontweight='bold')
        ax.set_xticks([1,2,3,4,5])
        ax.set_xticklabels(['Q1','Q2','Q3','Q4','Q5'])
        ax.set_ylabel('年化收益率')
        ax.legend(fontsize=8)
        ax.axhline(y=0, color='gray', alpha=0.5)
        ax.grid(alpha=0.3, axis='y')
    
    # 第4列：各Q的年化收益对比柱状图（三期并列）
    ax = axes[0, 3]
    x = np.arange(5)
    w = 0.25
    colors_bar = ['steelblue', 'coral', 'seagreen']
    for i, (pk, pn) in enumerate(zip(period_keys, period_names)):
        ann_rets = [calc_stats(results_dict[pk]['group_rets'][g])['年化'] for g in [1,2,3,4,5]]
        bars = ax.bar(x + (i-1)*w, ann_rets, w, label=pn, color=colors_bar[i], alpha=0.8)
    if bench_rets is not None:
        bs = calc_stats(bench_rets)
        ax.axhline(y=bs['年化'], color='gray', ls='--', lw=1.5, label=f'基准{bs["年化"]:.1%}')
    ax.set_title('三周期年化收益对比', fontsize=13, fontweight='bold')
    ax.set_xticks(x); ax.set_xticklabels(['Q1','Q2','Q3','Q4','Q5'])
    ax.set_ylabel('年化收益率')
    ax.axhline(y=0, color='gray', alpha=0.5)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3, axis='y')
    
    # 单调性数据
    ax = axes[1, 3]; ax.axis('off')
    ax = axes[2, 3]; ax.axis('off')
    
    # 写在第2行第4列
    ax2 = axes[1, 3]; ax2.axis('off')
    from scipy.stats import spearmanr
    ranks = [1,2,3,4,5]
    txt = "多空组合统计\n" + "─"*30 + "\n"
    txt += f"{'':<10}{'3m':>10}{'6m':>10}{'12m':>10}\n" + "─"*40 + "\n"
    for label in ['年化', '夏普', '月胜率', '最大回撤']:
        vals = []
        for pk in period_keys:
            s = calc_stats(results_dict[pk]['ls_rets'])
            if label == '年化': vals.append(f"{s['年化']:>9.2%}")
            elif label == '夏普': vals.append(f"{s['夏普']:>9.3f}")
            elif label == '月胜率': vals.append(f"{s['月胜率']:>9.2%}")
            elif label == '最大回撤': vals.append(f"{s['最大回撤']:>9.2%}")
        txt += f"{label:<10}{'  '.join(vals)}\n"
    
    txt += "─"*40 + "\n"
    for pk, pn in zip(period_keys, period_names):
        anns = [calc_stats(results_dict[pk]['group_rets'][g])['年化'] for g in [1,2,3,4,5]]
        corr, pv = spearmanr(ranks, anns)
        txt += f"{pn}: ρ={corr:.3f}(p={pv:.4f})\n"
        txt += f"  Q1-Q5差={anns[0]-anns[-1]:.1%}\n"
    
    if bench_rets is not None:
        bs = calc_stats(bench_rets)
        txt += f"基准: 年化{bs['年化']:.2%} 夏普{bs['夏普']:.3f}\n"
    
    ax2.text(0.05, 0.95, txt, transform=ax2.transAxes, fontsize=10, va='top', fontfamily='SimHei')
    
    # 第3行第4列放结论
    ax3 = axes[2, 3]; ax3.axis('off')
    txt2 = "核心结论\n" + "─"*30 + "\n"
    best_q1 = max(period_keys, key=lambda pk: calc_stats(results_dict[pk]['group_rets'][1])['年化'])
    txt2 += f"Q1最佳周期: {best_q1}"
    q1_ann = calc_stats(results_dict[best_q1]['group_rets'][1])['年化']
    txt2 += f" (年化{q1_ann:.1%})\n"
    
    # 单调性最佳
    best_mono = max(period_keys, key=lambda pk: abs(
        calc_stats(results_dict[pk]['group_rets'][1])['年化'] - calc_stats(results_dict[pk]['group_rets'][5])['年化']))
    txt2 += f"单调性最佳: {best_mono}\n"
    
    # 多空显著
    sig_periods = [pk for pk in period_keys if stats.ttest_1samp(results_dict[pk]['ls_rets'], 0)[1] < 0.05]
    txt2 += f"多空显著: {', '.join(sig_periods) if sig_periods else '无(均不显著)'}\n"
    
    ax3.text(0.05, 0.95, txt2, transform=ax3.transAxes, fontsize=11, va='top', fontfamily='SimHei')
    
    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=150, bbox_inches='tight')
    print(f"[图片] {OUTPUT_IMG}")

# ====== 额外: 每个Q的三周期对比曲线 ======
def plot_q_comparison(results_dict, bench_rets, months):
    """为每个Q画一张图，3/6/12m曲线放在一起对比"""
    fig, axes = plt.subplots(2, 3, figsize=(20, 12))
    axes_flat = axes.flatten()
    colors_line = {'3m': '#3182bd', '6m': '#e6550d', '12m': '#31a354'}
    
    for idx_q, g in enumerate([1,2,3,4,5]):
        ax = axes_flat[idx_q]
        for pk, pn in zip(['3m','6m','12m'], ['动量_3m','动量_6m','动量_12m']):
            ax.plot(results_dict[pk]['navs'][g], color=colors_line[pk], lw=1.5, label=pn)
        if bench_rets is not None:
            bnav = np.cumprod(1 + np.array(bench_rets[:len(months)]))
            ax.plot(range(len(months)), bnav, color='gray', ls='--', lw=1, label='中证500')
        yr_ticks = [i for i,m in enumerate(months) if m.endswith('-01') or i==0]
        yr_labels = [months[i][:4] for i in yr_ticks]
        ax.set_title(f'Q{g} 三周期对比', fontsize=12, fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax.set_xticks(yr_ticks); ax.set_xticklabels(yr_labels, rotation=45)
    
    # 第6个子图放汇总
    ax = axes_flat[5]; ax.axis('off')
    txt = "各Q三周期年化收益\n" + "─"*30 + "\n"
    for g in [1,2,3,4,5]:
        txt += f"Q{g}:  "
        for pk, pn in zip(['3m','6m','12m'], ['3m','6m','12m']):
            a = calc_stats(results_dict[pk]['group_rets'][g])['年化']
            txt += f"{pn}={a:.1%}  "
        txt += "\n"
    txt += "\n最大回撤\n" + "─"*15 + "\n"
    for g in [1,2,3,4,5]:
        txt += f"Q{g}:  "
        for pk in ['3m','6m','12m']:
            mdd = calc_stats(results_dict[pk]['group_rets'][g])['最大回撤']
            txt += f"{pk}={mdd:.1%}  "
        txt += "\n"
    ax.text(0.05, 0.95, txt, transform=ax.transAxes, fontsize=10, va='top', fontfamily='SimHei')
    
    plt.tight_layout()
    q_img = os.path.join(BASE_DIR, "phase2_stock_momentum_qcomparison.png")
    plt.savefig(q_img, dpi=150, bbox_inches='tight')
    print(f"[图片-Q对比] {q_img}")

def main():
    t0 = time.time()
    
    # 1. 加载数据（已有缓存）
    all_data = load_cached_stocks(CACHE_DIR)
    if len(all_data) < 50:
        # 无缓存时重新下载
        import akshare as ak
        codes = sorted(set(str(c).zfill(6) for c in ak.index_stock_cons(symbol="000905")['品种代码'].tolist()))
        print(f"[下载] 获取 {len(codes)} 只中证500成分股...")
        for i, code in enumerate(codes):
            cache_file = os.path.join(CACHE_DIR, f"{code}.pkl")
            if os.path.exists(cache_file):
                continue
            try:
                df = ak.stock_zh_a_hist(symbol=code, period="daily",
                    start_date="20170101", end_date="20260430", adjust="qfq")
                if df is not None and len(df) > 0:
                    df = df.rename(columns={'日期':'date','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume','成交额':'amount'})
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.sort_values('date').reset_index(drop=True)
                    pickle.dump(df, open(cache_file, 'wb'))
            except:
                pass
            if (i+1) % 100 == 0:
                print(f"  下载进度: {i+1}/{len(codes)}")
        all_data = load_cached_stocks(CACHE_DIR)
    
    # 2. 基准（必须限制时间范围，否则前100个月是2005-2013年数据）
    bench_df = load_benchmark()
    bench_ts = bench_df.set_index('date')['close']
    bench_ts = bench_ts[(bench_ts.index >= pd.Timestamp(START_DATE)) & (bench_ts.index <= pd.Timestamp(END_DATE))]
    bench_monthly_close = bench_ts.resample('ME').last()
    bench_rets = bench_monthly_close.pct_change().dropna().tolist()
    bs = calc_stats(bench_rets)
    print(f"[基准] 中证500({START_DATE}~{END_DATE}): 年化{bs['年化']:.2%} 夏普{bs['夏普']:.3f} 回撤{bs['最大回撤']:.2%} 总收益{bs['总收益']:.2%}")
    
    # 3. 时间
    month_ends = get_month_ends(all_data, START_DATE, END_DATE)
    print(f"[时间] {len(month_ends)} 个月末交易日 ({START_DATE}~{END_DATE})")
    sanity_check_benchmark(bench_df, bench_rets, START_DATE, END_DATE, expected_months=len(month_ends)-1)
    
    # 4. 因子
    factors = compute_all_factors(all_data, month_ends)
    
    # 5. 回测
    results = {}
    for pk in ['3m', '6m', '12m']:
        results[pk] = backtest_factor(factors[pk], all_data, month_ends)
        print_full_table(f"动量_{pk}", results[pk], bench_rets)
    
    # 5.1 最新 Top K 选股（更可交易）
    print(f"\n{'='*120}")
    print(f"  最新 Top {TOPK_N} 动量选股")
    print(f"{'='*120}")
    for pk in ['3m', '6m', '12m']:
        latest_date, picks = get_topk_latest(factors[pk], topk=TOPK_N)
        print(f"\n[{pk}] 截面日期: {latest_date.date()} | Top {TOPK_N}")
        for i, (code, score) in enumerate(picks.items(), 1):
            print(f"  {i:02d}. {code}  动量={score:.2%}")
    
    # 6. 绘图
    plot_all(results, bench_rets, results['3m']['months'])
    plot_q_comparison(results, bench_rets, results['3m']['months'])
    
    print(f"\n[完成] 总耗时: {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
