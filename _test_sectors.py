"""测试中证行业指数数据可用性"""
import akshare as ak
import pandas as pd

sectors = {
    '000986': '全指能源',
    '000987': '全指材料',
    '000988': '全指工业',
    '000989': '全指可选',
    '000990': '全指消费',
    '000991': '全指医药',
    '000992': '全指金融',
    '000993': '全指信息',
    '000994': '全指电信',
    '000995': '全指公用',
}

for code, name in sectors.items():
    try:
        df = ak.stock_zh_index_daily(f'sh{code}')
        start = df['date'].iloc[0][:10]
        end = df['date'].iloc[-1][:10]
        rows = len(df)
        last_close = df['close'].iloc[-1]
        print(f'{code} {name}: {start} ~ {end}, {rows}行, 最新={last_close:.1f}')
    except Exception as e:
        print(f'{code} {name}: 失败 - {e}')
