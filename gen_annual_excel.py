"""生成申万一级行业每年收益表 + 策略每年收益表 → Excel"""
import sys, io, os, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import akshare as ak

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
                prices[cname] = df['收盘']
        except:
            pass
    price_df = pd.DataFrame(prices).dropna(how='all')
    return price_df


# ════════════════════════════════════════
# 1. 行业每年收益表
# ════════════════════════════════════════
print('📥 加载数据...')
price_df = load_sw_data()
print(f'  {price_df.shape[1]} 个行业')

# 按年取年初年末收盘价
price_df['year'] = price_df.index.year
yearly = price_df.groupby('year').agg(['first', 'last'])
yearly.columns = ['_'.join(col) for col in yearly.columns]

# 每年收益率（%） 列: 行业名, 行: 年
years = sorted(yearly.index.unique())
industry_names = price_df.columns.tolist()

rows_annual = {}
for y in years:
    rets = []
    for name in industry_names:
        try:
            f = yearly.loc[y, (name, 'first')]
            l = yearly.loc[y, (name, 'last')]
            rets.append((l / f - 1) * 100)
        except:
            rets.append(np.nan)
    rows_annual[y] = rets

df_annual = pd.DataFrame(rows_annual, index=industry_names).round(2)

# 总收益：2015年初到2026年4月底
price_2015 = price_df[price_df.index.year == 2015].iloc[0]
price_2026 = price_df[price_df.index.year == 2026].iloc[-1]
total_rets = ((price_2026[industry_names] / price_2015[industry_names]) - 1) * 100
df_annual['总收益'] = total_rets.round(2)
df_annual = df_annual.sort_values('总收益', ascending=False)

print(f'  行业每年收益表: {df_annual.shape}')


# ════════════════════════════════════════
# 2. 策略+基准 每年收益表
# ════════════════════════════════════════
def compute_curve_year_ret(price_df, is_multi_factor, topk, momentum_months):
    """计算策略每年收益"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)

    if is_multi_factor:
        mom_ret = monthly.pct_change(periods=momentum_months)
        mom_rank = mom_ret.rank(axis=1, ascending=True, pct=True).fillna(0.5)
        vol_scores = {}
        for col in price_df.columns:
            dr = price_df[col].pct_change().dropna()
            vol = dr.groupby(pd.Grouper(freq='ME')).std() * np.sqrt(252)
            vol = vol.rolling(momentum_months, min_periods=1).mean()
            vol_scores[col] = 1.0 / vol.replace(0, np.nan)
        vol_df = pd.DataFrame(vol_scores)
        vol_rank = vol_df.rank(axis=1, ascending=True, pct=True).fillna(0.5)
        vol_rank = vol_rank.reindex(monthly.index).ffill()
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
        mom_ret = monthly.pct_change(periods=momentum_months)
        total_score = mom_ret.rank(axis=1, ascending=True, pct=True).fillna(0.5)

    # 模拟回测，按月记录净值
    val = 1.0
    monthly_vals = []
    monthly_dates = []
    dates = total_score.index.tolist()

    for i in range(1, len(dates)):
        prev_date = dates[i-1]
        cur_date = dates[i]
        if prev_date not in total_score.index or cur_date not in monthly.index:
            monthly_vals.append(val)
            monthly_dates.append(cur_date)
            continue
        scores = total_score.loc[prev_date]
        top_cols = scores.nlargest(topk).index.tolist()
        if prev_date not in monthly.index or cur_date not in monthly.index:
            monthly_vals.append(val)
            monthly_dates.append(cur_date)
            continue
        p_prev = monthly.loc[prev_date, top_cols].values
        p_cur = monthly.loc[cur_date, top_cols].values
        p_prev = np.where(p_prev == 0, np.nan, p_prev)
        rets = (p_cur / p_prev) - 1
        port_ret = np.nanmean(rets)
        if np.isnan(port_ret):
            port_ret = 0
        val *= (1 + port_ret)
        monthly_vals.append(val)
        monthly_dates.append(cur_date)

    nav = pd.Series(monthly_vals, index=monthly_dates)
    nav.index = pd.to_datetime(nav.index)
    # 按年计算收益
    yearly = {}
    years_in_data = sorted(set(nav.index.year))
    for y in years_in_data:
        y_data = nav[nav.index.year == y]
        if len(y_data) == 0:
            yearly[y] = np.nan
            continue
        start_val = y_data.iloc[0]
        end_val = y_data.iloc[-1]
        yearly[y] = (end_val / start_val - 1) * 100
    return yearly


def compute_ew_year_ret(price_df):
    """等权基准每年收益"""
    monthly = price_df.resample('ME').last().dropna(how='all', axis=1)
    val = 1.0
    vals = []
    for i in range(1, len(monthly)):
        rets = (monthly.iloc[i].values / monthly.iloc[i-1].values) - 1
        port_ret = np.nanmean(rets)
        val *= (1 + port_ret)
        vals.append(val)

    nav = pd.Series(vals, index=monthly.index[1:])
    nav.index = pd.to_datetime(nav.index)
    yearly = {}
    for y in sorted(set(nav.index.year)):
        y_data = nav[nav.index.year == y]
        if len(y_data) < 1:
            continue
        yearly[y] = ((y_data.iloc[-1] / y_data.iloc[0] - 1) * 100)
    return yearly


def compute_hs300_year_ret():
    """沪深300每年收益"""
    df = pd.read_pickle('sh000300_cache.pkl')
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.sort_index().loc['2015-01-01':'2026-04-30']
    yearly = {}
    for y in range(2015, 2027):
        yd = df[df.index.year == y]
        if len(yd) < 2:
            continue
        yearly[y] = ((yd['close'].iloc[-1] / yd['close'].iloc[0] - 1) * 100)
    return yearly


print('📊 计算策略每年收益...')
strategies = [
    ('纯动量_12m_top5', False, 5, 12),
    ('多因子_12m_top5', True, 5, 12),
    ('纯动量_6m_top10', False, 10, 6),
    ('纯动量_6m_top5', False, 5, 6),
    ('多因子_6m_top5', True, 5, 6),
]

strategy_yearly = {}
for name, is_mf, topk, mom_m in strategies:
    strategy_yearly[name] = compute_curve_year_ret(price_df, is_mf, topk, mom_m)
    print(f'  {name} ✅')

strategy_yearly['申万行业等权'] = compute_ew_year_ret(price_df)
strategy_yearly['沪深300'] = compute_hs300_year_ret()

# 转DataFrame
dfs = []
for name, yearly in strategy_yearly.items():
    ser = pd.Series(yearly, name=name)
    dfs.append(ser)

df_strat = pd.DataFrame(dfs).T
df_strat.index.name = '年份'
df_strat = df_strat.round(2)

# 加一行总收益
total_ret_row = {}
for name in df_strat.columns:
    vals = df_strat[name].dropna()
    if len(vals) > 1:
        # 总收益 = 各年(1+ret)连乘 -1
        cum = (1 + vals/100).prod() - 1
        total_ret_row[name] = round(cum * 100, 2)
    else:
        total_ret_row[name] = np.nan

df_strat.loc['累计'] = pd.Series(total_ret_row)


# ════════════════════════════════════════
# 写入Excel
# ════════════════════════════════════════
out_path = os.path.join(os.path.dirname(__file__), 'phase1_annual_returns.xlsx')
with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
    # Sheet 1: 行业每年收益
    df_annual.to_excel(writer, sheet_name='行业每年收益', index=True)

    # Sheet 2: 策略每年收益
    df_strat.to_excel(writer, sheet_name='策略每年收益', index=True)

    # Sheet 3: 行业信息（代码+名称）
    df_info = ak.sw_index_first_info()
    df_info.to_excel(writer, sheet_name='行业信息', index=False)

print(f'\n✅ Excel 已保存: {out_path}')
print(f'   Sheet 1: 行业每年收益 ({df_annual.shape[0]}行 x {df_annual.shape[1]}列)')
print(f'   Sheet 2: 策略每年收益 ({df_strat.shape[0]}行 x {df_strat.shape[1]}列)')
print(f'   Sheet 3: 行业信息')
