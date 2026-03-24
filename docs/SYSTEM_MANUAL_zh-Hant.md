# A 股量化系統詳細說明書

本文件是給股市新手看的系統使用與理解手冊。目標不是只告訴你「按哪個按鈕」，而是幫你真正理解：

- 這個系統每一步在做什麼
- 每一步吃進什麼資料
- 中間經過哪些邏輯處理
- 最後輸出什麼結果
- 這些結果在投資上能怎麼用
- 哪些地方可以幫助判斷股票
- 哪些地方不能直接拿來當買賣指令

如果你把這個系統想像成一條流水線，它的核心任務其實很簡單：

1. 先把 A 股原始資料抓下來
2. 把原始資料整理成模型可讀的特徵
3. 用歷史資料訓練模型
4. 用最新資料替今天的股票打分
5. 用歷史回測檢查這套做法過去是否有效

它不是自動下單系統，也不是保證獲利系統。它更像是一個「量化選股與驗證工具」。

## 1. 先用一句話講清楚這個系統在做什麼

這套系統會根據每檔股票最近一段時間的價格、成交量、估值和一些技術特徵，訓練一個 LightGBM 模型，去預測：

「這檔股票在未來 5 個交易日內，報酬是否大於 2%。」

因此，系統輸出的 `score` 不是目標價，也不是上漲點數，而是：

- 一個模型分數
- 更精確地說，是「這檔股票未來 5 個交易日漲幅超過 2% 的機率估計」
- 分數越高，代表在歷史相似樣本裡，這檔股票更像是會達成這個條件的股票

這是整個系統最重要的一句話。

## 2. 先釐清 Panel 上的 Step 和實際腳本名稱

這個系統有一個容易讓人困惑的地方：

- Panel 上顯示的是 Step 1 到 Step 5
- 但實際 runner 腳本名稱是 `run_step3_...` 到 `run_step6_...`

這不是錯誤，而是歷史命名留下來的結果。

對照如下：

| Panel 顯示 | 實際腳本 | 實際功能 |
|---|---|---|
| Step 1 Data Prepare | `download_data.py` / `run_a_share_3y_batch.sh` | 抓全市場股票池、K 線、估值資料 |
| Step 2 Training Features | `run_step3_feature_engineering.sh` | 產生訓練特徵資料 |
| Step 3 Inference Features | `run_step4_inference_features.sh` | 產生最新推理特徵 |
| Step 4 Train and Score | `run_step5_train_score.sh` | 訓練模型並對最新股票打分 |
| Step 5 Walk-forward Backtest | `run_step6_backtest.sh` | 做嚴格樣本外回測 |

所以你在 Panel 看到的：

- Step 4 Train and Score

實際執行的是：

- `run_step5_train_score.sh`
- 裡面再去跑 `train_lightgbm.py`

## 3. 整個系統的資料流總覽

完整資料流可以用這條線理解：

`外部資料源 -> 原始 parquet -> 訓練特徵 -> 推理特徵 -> 模型 -> 股票分數 -> 回測結果`

更細一點是：

1. 用 Baostock / AKShare 下載股票池、K 線、估值
2. 每檔股票各自存成 parquet
3. 合併成訓練面板資料
4. 建立技術特徵與未來報酬標籤
5. 訓練 LightGBM 二元分類模型
6. 對最新一天的股票做分數排序
7. 用 walk-forward 回測檢查過去是否有效

## 3.1 Daily Pipeline 現在到底要跑多久

這是一個很實際、也很重要的問題。

答案是：

- 目前不應該把它說成「固定 7 小時」
- 根據最新一次完整實測，它更接近 `6 小時 29 分`

這裡引用的是最新一輪成功完成的 Daily Pipeline：

- 啟動時間：`2026-03-23T23:45:25Z`
- 完成時間：`2026-03-24T06:14:51Z`
- 總耗時：約 `389.44` 分鐘
- 也就是約 `6.49` 小時

### 3.1.1 每一步大概花多久

根據同一次執行的 log：

| 步驟 | 功能 | 約耗時 |
|---|---|---:|
| Step 1 Data Prepare | 刷股票池、抓 K 線、抓估值、落 parquet | `378.75` 分鐘 |
| Step 2 Feature Engineering | 產生訓練特徵 | `5.34` 分鐘 |
| Step 3 Inference Features | 產生最新推理特徵 | `3.67` 分鐘 |
| Step 4 Train and Score | 訓練模型並輸出最新分數 | `1.67` 分鐘 |

### 3.1.2 正式結論

所以目前這條 Daily Job 的時間結構非常清楚：

- 真正的耗時瓶頸幾乎全部在 `Step 1`
- `Step 2` 到 `Step 4` 本身其實都很快
- 如果未來要優化整體時間，優先級最高的不是模型，而是資料準備

### 3.1.3 為什麼 Step 1 會這麼久

因為它同時做了最重的事：

- 全市場股票池刷新
- 大量股票逐檔抓取歷史資料
- 外部資料源請求與限流等待
- 大量 parquet 寫入與覆蓋
- 原始行情與估值的雙路資料維護

換句話說，現在的 Daily Pipeline 比較像：

- `資料工程工作量很大`

而不是：

- `模型訓練工作量很大`

## 4. 系統中的主要資料檔案

你可以把這些檔案分成 5 類。

### 4.1 股票池與主名單

#### `quant_data/stock_list.parquet`

這是「目前活躍股票池」。

主要欄位：

- `code`: 六位數股票代碼
- `exchange`: `sh` 或 `sz`
- `name`: 股票名稱
- `industry`: 行業
- `industry_classification`: 行業分類來源
- `trade_date`: 這次股票池快照對應的交易日
- `universe`: 股票池來源，例如 `all`
- `is_active`: 是否目前仍在活躍股票池
- `first_seen_date`: 第一次出現日期
- `last_seen_date`: 最後一次活躍日期
- `inactive_date`: 若已停用，會記錄停用日期

作用：

- 告訴系統現在有哪些股票要納入處理
- 提供股票名稱和行業資訊
- 後續所有資料合併都靠 `code + exchange`

#### `quant_data/stock_registry.parquet`

這是完整註冊表，比 `stock_list.parquet` 更長期。

作用：

- 保留歷史上曾出現過的股票
- 不是只保留今天還活著的股票
- 可用來追蹤新股、停牌、退市、重新恢復活躍等狀態

#### `quant_data/stock_list_subset.parquet`

這是子集測試時的股票池。

作用：

- 用於測試或小樣本下載
- 不會覆蓋正式的 `stock_list.parquet`

### 4.2 原始行情資料

#### `quant_data/daily_kline/*.parquet`

每一檔股票一個檔案，例如：

- `quant_data/daily_kline/000001.parquet`

主要欄位：

- `date`
- `code`
- `exchange`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`
- `turnover`
- `amplitude`
- `pct_chg`
- `change`

作用：

- 這是最基礎的價格與成交行為資料
- 技術指標和動量特徵幾乎都從這裡衍生

### 4.3 原始估值資料

#### `quant_data/daily_valuation/*.parquet`

每一檔股票一個檔案，例如：

- `quant_data/daily_valuation/000001.parquet`

主要欄位：

- `date`
- `code`
- `exchange`
- `close`
- `pct_chg`
- `total_market_cap`
- `float_market_cap`
- `total_shares`
- `float_shares`
- `pe_ttm`
- `pb`
- `ps`
- `pcf`

作用：

- 補上公司規模與估值信息
- 讓模型不只看價格，也看「股票現在貴不貴、大不大、流通結構如何」

### 4.4 訓練資料

#### `quant_data/ml_features_ready.parquet`

這是模型正式訓練用的資料。

它的每一列代表：

- 某一檔股票
- 在某一天
- 的一組特徵
- 加上未來表現標籤

這是最重要的訓練資料表。

### 4.5 推理、模型與回測產物

#### `quant_data/inference_features_latest.parquet`

最新一天每檔股票的特徵快照，不含未來標籤。

#### `quant_data/models/inference_scores_latest.parquet`

模型對最新股票池打分後的結果。

#### `quant_data/models/lightgbm_model.txt`

保存下來的 LightGBM 模型本體。

#### `quant_data/models/feature_importance.csv`

特徵重要性結果。

#### `quant_data/models/training_metadata.json`

訓練期間的參數、樣本數、驗證表現等資訊。

#### `quant_data/backtests/summary.json`

回測總結指標。

#### `quant_data/backtests/equity_curve.parquet`

回測淨值曲線。

#### `quant_data/backtests/trade_log.parquet`

每次調倉實際選到哪些股票。

#### `quant_data/backtests/oos_predictions.parquet`

每次樣本外預測的完整打分資料。

## 5. Step 1: Data Prepare 的詳細說明

### 5.1 這一步的任務

Step 1 的任務是：

- 建立股票池
- 補股票基本資料
- 下載每檔股票的歷史 K 線
- 下載每檔股票的估值資料

這一步是整個系統的地基。

如果 Step 1 沒做好，後面所有步驟都會出問題。

### 5.2 這一步的外部資料來源

Step 1 主要用兩個來源：

- `Baostock`
- `AKShare`

其中：

- 股票池、交易日、K 線、PE/PB/PS/PCF 等主要來自 Baostock
- 市值和股本資料補充來自 AKShare 的 `stock_value_em`

### 5.3 股票池是怎麼產生的

如果你跑的是全市場：

1. 先找出 `end_date` 之前最近的交易日
2. 用 `query_all_stock` 抓那天的全市場股票列表
3. 過濾成 A 股
4. 排除名稱以 `退` 結尾的股票
5. 補上 `exchange`
6. 補上 `trade_date`
7. 保留 `code / exchange / name / trade_date`

如果你跑的是 HS300：

1. 直接抓滬深 300 成分股
2. 轉成標準欄位

### 5.4 行業欄位怎麼來

系統會盡量保留舊的 `industry` 與 `industry_classification`，避免每次都全量重查。

如果行業缺失，才會再透過 Baostock 補查。

這樣做的好處：

- 比較快
- 比較穩
- 不會每次都對外部 API 造成太大壓力

### 5.5 原始 K 線是怎麼下載的

每檔股票會用 Baostock 抓歷史日線，重要設定是：

- `frequency="d"`
- `adjustflag="2"`

其中 `adjustflag="2"` 代表：

- 使用前復權資料

這很重要，因為如果不用復權資料，股價因除權除息產生的跳空，會污染技術特徵與報酬率計算。

### 5.6 原始估值是怎麼整理的

估值資料不是只抓 PE/PB。

系統會把：

- Baostock 的 `pe_ttm / pb / ps / pcf`
- AKShare 的 `total_market_cap / float_market_cap / total_shares / float_shares`

合併成一份每日估值表。

### 5.7 Step 1 的輸出

主要輸出：

- `quant_data/stock_list.parquet`
- `quant_data/stock_registry.parquet`
- `quant_data/daily_kline/*.parquet`
- `quant_data/daily_valuation/*.parquet`
- `quant_data/download_failures.csv`

### 5.8 這一步對炒股有什麼意義

這一步本身不會直接告訴你買哪支股票。

它的意義是：

- 讓後面模型有完整而乾淨的資料可用
- 保證股票池是最新的
- 保證每支股票都具備價格、成交和估值背景

如果把整個系統比喻成做菜：

- Step 1 就是在買菜、洗菜、切菜

這一步沒有它，後面全部不用談。

### 5.9 你應該怎麼檢查這一步有沒有正常

你可以看：

- `stock_list.parquet` 目前有多少活躍股票
- `daily_kline` 和 `daily_valuation` 是否成對存在
- `download_failures.csv` 是否很多失敗

如果這一步不完整，後面樣本會縮水，模型會偏掉。

## 6. Step 2: Training Features 的詳細說明

### 6.1 這一步的任務

把原始 K 線和估值資料整理成模型可訓練的表格。

這一步做完後，資料才會從「原始行情」變成「可學習樣本」。

### 6.2 這一步的輸入

輸入是：

- `quant_data/stock_list.parquet`
- `quant_data/daily_kline/*.parquet`
- `quant_data/daily_valuation/*.parquet`

### 6.3 這一步的核心邏輯

對每一檔股票：

1. 讀入它的 K 線 parquet
2. 讀入它的估值 parquet
3. 用 `date + code + exchange` 合併
4. 再跟 `stock_list.parquet` 合併名稱與行業
5. 針對每檔股票各自依日期排序
6. 計算技術特徵
7. 計算未來報酬和標籤
8. 丟掉缺值行
9. 寫入 `ml_features_ready.parquet`

### 6.4 這一步保留的原始欄位

訓練面板中保留的原始欄位主要包括：

- `date / code / exchange`
- `open / high / low / close`
- `volume / amount / turnover / amplitude`
- `pct_chg / change`
- `close_val / pct_chg_val`
- `total_market_cap / float_market_cap / total_shares / float_shares`
- `pe_ttm / pb / ps / pcf`
- `name / industry`

### 6.5 這一步產生的衍生特徵

目前主要特徵有：

- `ma5`: 5 日均線
- `ma20`: 20 日均線
- `bias_20`: 收盤價相對 20 日均線偏離
- `pct_chg_5d`: 5 日報酬
- `pct_chg_20d`: 20 日報酬
- `volatility_20d`: 20 日波動率
- `turnover_ma5`: 5 日平均換手率
- `volume_ma5`: 5 日平均成交量
- `close_to_high_20d`: 相對 20 日高點位置
- `close_to_low_20d`: 相對 20 日低點位置

你可以把這些特徵理解成 4 類：

- 趨勢類：`ma5`, `ma20`, `bias_20`
- 動量類：`pct_chg_5d`, `pct_chg_20d`
- 波動與流動性類：`volatility_20d`, `turnover_ma5`, `volume_ma5`
- 區間位置類：`close_to_high_20d`, `close_to_low_20d`

### 6.6 最重要的標籤是怎麼定義的

系統目前的標籤定義是：

- `label_horizon = 5`
- `label_threshold = 0.02`

也就是：

- `future_return = 5 個交易日後收盤價 / 今天收盤價 - 1`
- 如果 `future_return > 0.02`
- 就標記 `label = 1`
- 否則 `label = 0`

翻成人話就是：

- 這個模型在學的是「5 個交易日後有沒有漲超過 2%」

這也是之後 `score` 的真正含義。

### 6.7 這一步怎麼清理資料

目前實際跑的設定是：

- 直接 `dropna()`
- 不做 winsorize 裁切

也就是說：

- 任何需要的欄位有空值，該列就不進訓練集
- 這樣做簡單直接，但會讓某些股票某些日期被排除

### 6.8 Step 2 的輸出

輸出是：

- `quant_data/ml_features_ready.parquet`

這張表的每一列可以理解成：

- 這檔股票在某天長什麼樣
- 以及 5 天後有沒有漲超過 2%

### 6.9 這一步對炒股有什麼意義

這一步的意義不是產生買點，而是把市場歷史變成可學習的樣本。

它在回答：

- 什麼樣的股票狀態，在歷史上更容易於 5 日內上漲超過 2%

這是後面模型選股的基礎。

## 7. Step 3: Inference Features 的詳細說明

### 7.1 這一步的任務

Step 3 是為了「今天要打分」而做的特徵工程。

與 Step 2 最大的差別是：

- Step 2 有標籤，給模型學習
- Step 3 沒有標籤，只是準備最新樣本給模型預測

### 7.2 這一步的輸入

輸入還是：

- `stock_list.parquet`
- `daily_kline/*.parquet`
- `daily_valuation/*.parquet`

### 7.3 這一步的核心邏輯

對每檔股票：

1. 讀最近一小段歷史資料
2. 目前固定取最近 `25` 個交易日窗口
3. 生成和訓練時一致的技術特徵
4. 不計算未來報酬與標籤
5. 每檔股票只保留最後 1 列

所以這一步的輸出表：

- 一檔股票只會有一列
- 代表這檔股票在最新日期的特徵狀態

### 7.4 為什麼需要最近 25 天

因為特徵中有：

- `ma20`
- `20d volatility`
- `20d high/low`

如果沒有足夠回看天數，就算不出來。

所以系統會先取最近 25 天，確保 20 天相關特徵可以形成。

### 7.5 Step 3 的輸出

輸出是：

- `quant_data/inference_features_latest.parquet`

這裡每一列代表：

- 一檔股票
- 在最新一天
- 的最新特徵快照

### 7.6 這一步對炒股有什麼意義

這一步是「今天的觀察名單」準備工作。

它的作用是：

- 把今天所有股票整理成模型可打分的格式

如果 Step 2 是做教材，
那 Step 3 就是在準備今天的考題。

## 8. Step 4: Train and Score 的詳細說明

### 8.1 這一步的任務

Step 4 做兩件事：

1. 用歷史資料訓練模型
2. 用剛訓練好的模型，對最新股票快照打分

### 8.2 這一步的輸入

輸入是：

- `quant_data/ml_features_ready.parquet`
- `quant_data/inference_features_latest.parquet`

### 8.3 模型用了哪些欄位

模型會自動排除這些欄位：

- `date`
- `code`
- `exchange`
- `name`
- `future_return`
- `label`

也就是：

- 不直接拿股票代碼去學
- 不直接拿日期去學
- 不把未來報酬塞回特徵裡作弊

目前類別特徵是：

- `industry`

其餘大多是數值特徵。

### 8.4 訓練集和驗證集怎麼切

目前設定：

- 用最後 `60` 個唯一交易日作驗證集
- 更早以前的日期作訓練集

意思是：

- 模型用舊資料訓練
- 用最近一段歷史檢查效果

這種切法比隨機切分更符合金融時序資料的現實。

### 8.5 模型是什麼

目前模型是：

- `LightGBM`
- 二元分類模型

重要參數大致包括：

- `objective = binary`
- `n_estimators = 500`
- `learning_rate = 0.05`
- `num_leaves = 63`
- `subsample = 0.8`
- `colsample_bytree = 0.8`
- `class_weight = balanced`
- `early_stopping = 50`

這代表：

- 它不是神經網路
- 它是表格資料很常用、速度快、效果穩的樹模型

### 8.6 `score` 到底是什麼

這是整個系統最容易被誤解的地方。

`score` 不是：

- 目標價
- 明天漲幅
- 保證獲利機率

`score` 真正代表的是：

- 模型估計這檔股票未來 5 個交易日漲幅超過 2% 的相對機率

例如：

- `score = 0.90`

不代表保證 90% 會漲。
它只代表：

- 在模型看來，這檔股票比 `score = 0.30` 的股票更像歷史上曾經成功達標的樣子

所以 `score` 最適合用來：

- 排序
- 相對比較

不適合用來：

- 直接當報酬率預估
- 當成必買信號

### 8.7 Step 4 的輸出

主要輸出：

- `quant_data/models/lightgbm_model.txt`
- `quant_data/models/feature_importance.csv`
- `quant_data/models/training_metadata.json`
- `quant_data/models/inference_scores_latest.parquet`

### 8.8 這些輸出怎麼看

#### `training_metadata.json`

看模型這次怎麼訓練的：

- 用了多少訓練樣本
- 用了多少驗證樣本
- 驗證 AUC 是多少
- 訓練期間起止日期

#### `feature_importance.csv`

看哪些特徵對模型最重要。

這不能直接當投資結論，但能幫你理解模型當前偏好：

- 偏動量
- 偏波動
- 偏估值
- 偏行業

#### `inference_scores_latest.parquet`

這是你每天最常看的結果表。

它會保留：

- 原本的股票特徵
- 再加上最後一欄 `score`

### 8.9 這一步對炒股有什麼意義

這一步會給你一張「今日候選股排序表」。

你可以把它當成：

- 量化初篩器
- 自動把全市場從強到弱排一次

它能幫你做到：

- 從幾千支股票縮小到幾十支值得研究的股票
- 比較不容易漏掉弱基本面但短期型態很強的標的
- 避免純靠直覺掃盤

但它不能替你完成的事情包括：

- 判斷消息面真假
- 判斷政策風險
- 判斷財報造假
- 判斷板塊情緒和隔日開盤衝擊

所以最正確的用法是：

- 用 `score` 排序找候選股
- 再用你自己的交易規則做第二層確認

## 9. Step 5: Walk-forward Backtest 的詳細說明

### 9.1 這一步的任務

回測不是拿來賺錢，它是拿來回答：

- 這套方法在過去是否站得住腳

系統目前做的是：

- 嚴格樣本外
- expanding-window
- walk-forward backtest

### 9.2 這句話翻成人話是什麼

意思是：

- 每次只用當時以前看得到的資料訓練
- 不偷看未來
- 然後對下一個調倉日做預測
- 再把這個流程一路往前滾

這比「整包歷史資料一次訓練，再回頭看全部歷史」更真實。

### 9.3 目前回測的主要設定

目前預設大致是：

- `min_train_days = 252`
- `retrain_every = 20`
- `rebalance_every = 5`
- `top_k = 5`
- `threshold = 0.5`

含義如下：

- 至少先累積 252 個交易日才開始第一次回測
- 每 20 個調倉點重訓一次模型
- 每 5 個交易日調倉一次
- 每次買分數最高的 5 檔
- 用 `0.5` 當分類閾值計算 OOS 指標

### 9.4 回測的實際流程

每一個調倉日，系統會：

1. 取該日以前所有歷史資料當訓練集
2. 如果到達重訓節點，就重新訓練模型
3. 對該調倉日所有股票打分
4. 按 `score` 由高到低排序
5. 取前 `top_k` 檔股票
6. 讀這些股票未來實際 `future_return`
7. 用這些股票未來報酬的平均值當作這一期投組報酬
8. 更新淨值曲線

### 9.5 Step 5 的輸出

#### `summary.json`

這是回測總結。

常見欄位：

- `num_rows`
- `num_codes`
- `num_trade_dates`
- `num_rebalances`
- `oos_metrics`
- `portfolio_total_return`
- `portfolio_cagr`
- `portfolio_max_drawdown`
- `portfolio_win_rate`
- `portfolio_avg_return`
- `portfolio_std_return`
- `backtest_start`
- `backtest_end`

#### `equity_curve.parquet`

每次調倉後的淨值變化。

#### `trade_log.parquet`

每次實際選中的股票名單。

#### `oos_predictions.parquet`

每次樣本外預測時，所有股票的完整預測結果。

### 9.6 回測指標怎麼看

#### AUC

看模型把好樣本排在前面的能力。

- `0.5` 左右接近亂猜
- 越高越好

在金融上，AUC 不需要像醫療那麼高才有價值，但如果長期太接近 `0.5`，就要小心模型沒什麼辨識力。

#### Accuracy

整體判對比例。

但在股市裡不一定最重要，因為標籤常常不平衡。

#### Precision

模型說「會漲超過 2%」的股票中，實際達標的比例。

這個對選股很重要，因為它接近「挑出來的股票有多準」。

#### Recall

所有真正會漲超過 2% 的股票裡，模型抓到了多少。

#### Portfolio Total Return

整段回測累計報酬。

#### CAGR

年化報酬率。

#### Max Drawdown

最大回撤。

這非常重要，因為回撤太大，再高的報酬都很難實戰持有。

#### Win Rate

調倉期中有幾成是正報酬。

### 9.7 這一步對炒股有什麼意義

回測的意義不是證明未來一定賺錢。

它真正提供的是：

- 這套方法是否值得繼續信任
- 是不是只是偶然有效
- 高分股票過去是否真的有相對優勢
- 風險是不是大到無法實戰

如果 Step 4 是給你「今天該看誰」，
那 Step 5 就是在問：

- 這套看法過去到底有沒有邏輯、有沒有紀律、有沒有勝率

## 10. 目前這台機器上的實際產物快照

以下是你目前系統中的實際例子，目的是幫你對數量有感覺。

### 10.1 股票池

目前 `stock_list.parquet` 約有：

- `5189` 檔活躍股票

### 10.2 訓練資料

目前 `ml_features_ready.parquet` 約有：

- `3,403,990` 列
- `37` 欄

這不是 5000 個模型，而是：

- 大約 5000 檔股票
- 每檔很多個交易日
- 合起來形成 340 多萬筆訓練樣本

### 10.3 推理資料

目前 `inference_features_latest.parquet` 約有：

- `5005` 列

這代表：

- 最新快照中有 `5005` 檔股票可打分
- 每檔股票只保留 1 列

### 10.4 最新打分結果

目前 `inference_scores_latest.parquet` 也有：

- `5005` 列

這代表：

- 模型真的對 5005 檔股票都打了分

如果 log 裡只看到 20 檔，那只是因為程式只印了 `top_k` 的預覽，不是只算了 20 檔。

### 10.5 最新訓練結果

目前訓練驗證指標大約是：

- Valid AUC: `0.5629`
- Accuracy: `0.5901`
- Precision: `0.3989`
- Recall: `0.3491`

這表示：

- 模型有一定辨識能力
- 但不是非常強
- 比較適合作為篩選輔助工具，而不是單獨決策工具

### 10.6 最新回測結果

目前回測總結大約是：

- OOS AUC: `0.5445`
- 回測區間: `2024-05-09` 到 `2026-03-11`
- 調倉次數: `90`
- 投組總報酬: `6.7549`
- 最大回撤: `-15.74%`

這些數字有參考價值，但不能直接當未來保證。

## 11. 一個股市新手應該怎麼使用這套系統

建議你把它當成「選股助理」，不是「替你按買進的機器」。

### 11.1 每日或每週使用流程

建議流程：

1. 先跑資料更新，確認股票池與原始資料完整
2. 產生訓練特徵與推理特徵
3. 訓練模型並取得最新 `score`
4. 先看 `inference_scores_latest.parquet` 中分數最高的前 20 或前 50 檔
5. 再人工做第二層檢查

第二層檢查建議看：

- K 線是否已經大漲過頭
- 成交量是否異常
- 是否有重大公告、財報、監管消息
- 是否屬於高風險題材股
- 是否符合你自己的停損與倉位規則

### 11.2 最適合用這個系統的人

這套系統最適合：

- 想從全市場中快速篩出候選股的人
- 想把主觀選股加上一層量化排序的人
- 想驗證某些模式是否過去有效的人

### 11.3 不適合怎麼用

不建議這樣用：

- 看到第一名就直接滿倉買入
- 把 `score` 當目標價
- 不看風險管理
- 不看大盤環境
- 不看個股流動性

## 12. 這套系統能怎麼幫助炒股

它能幫你的地方：

- 幫你從數千檔股票中快速找出相對值得研究的標的
- 幫你用一致標準每天重複篩選
- 幫你把「感覺不錯」變成「有歷史驗證支持的排序」
- 幫你避免只看熟悉股票而忽略其他強勢標的
- 幫你用回測檢查策略是否只是運氣

它不能替你的地方：

- 不能替你承擔風險
- 不能保證未來照歷史重演
- 不能理解突發利空、政策變動、財務造假
- 不能決定你應該下多少倉位

所以最合理的定位是：

- 它是量化雷達
- 不是自動提款機

## 13. 重要限制與風險

### 13.1 標籤定義是短線風格

目前標籤只看：

- 未來 5 個交易日是否大於 2%

所以這套模型偏向：

- 短中短線動量 / 排名型選股

它不是長線基本面估值模型。

### 13.2 模型分數是相對值

不同日期的市場環境不同。

因此：

- `今天的 0.8`
- 不一定等於
- `另一個月的 0.8`

它更適合「同一天內做排序」。

### 13.3 回測不等於實盤

回測通常沒完全反映：

- 手續費
- 滑價
- 漲跌停成交限制
- 真實成交量衝擊
- 公告停牌

所以回測結果要打折看。

### 13.4 訓練資料質量決定上限

如果：

- 某些股票原始資料缺很多
- 行業欄位缺失
- 估值欄位不穩

那模型效果一定會受影響。

## 14. 常見誤解與常見現象

### 14.1 「為什麼 log 只看到 20 支股票？」

因為程式只印預覽。

真正打分結果在：

- `quant_data/models/inference_scores_latest.parquet`

裡面是一整個股票池，不是只有 log 顯示的幾支。

### 14.2 「為什麼 5000 多支股票訓練只花 1 到 2 分鐘？」

因為：

- 不是訓練 5000 個模型
- 而是訓練 1 個模型
- 用 300 多萬筆表格資料
- LightGBM 本來就很快

### 14.3 「為什麼回測 log 看起來沒什麼輸出？」

因為目前回測程式主要在：

- 每次重訓模型時才印 log

不是每個調倉日都印。

所以 log 很稀疏，不代表卡住。

### 14.4 「Step 4 為什麼容易吃記憶體？」

因為它要：

- 讀整份訓練 parquet
- 建訓練矩陣
- 再做模型訓練

在 8GB RAM 的機器上，這一步很容易成為最吃資源的步驟。

## 15. 如何解讀這套系統給你的答案

最重要的實戰心法是：

- 看分數，不是看神諭

建議你把結果分成三層理解：

### 第一層：市場掃描

先看誰分數最高，找出今日候選股。

### 第二層：風格辨認

再看它為什麼分數高：

- 是因為動量強
- 是因為接近 20 日高點
- 是因為估值相對便宜
- 還是因為某些行業特徵

### 第三層：人工判斷

最後再問：

- 我願不願意承擔這支股票的風險
- 我有沒有明確停損
- 這支股票流動性夠不夠
- 是否剛好碰到消息事件

只有做到第三層，這個系統才是真的在幫你，而不是帶著你亂衝。

## 16. 給新手的最簡單結論

如果你只記住 5 句話，請記住這 5 句：

1. 這套系統不是預言明天漲跌，而是在找「歷史上比較像會漲的股票」。
2. `score` 是排序分數，不是目標價。
3. Step 4 給你候選股，Step 5 告訴你這套方法過去有沒有道理。
4. 分數高只能代表值得優先研究，不能代表一定要買。
5. 真正能保護你的是風險控制，不是模型本身。

## 17. 建議你下一步怎麼用

如果你剛開始用這套系統，最建議的順序是：

1. 先打開 `inference_scores_latest.parquet`，只看前 20 檔
2. 我再幫你把這 20 檔翻成一份人能看懂的候選股報表
3. 再把回測結果翻成「這套方法到底值不值得信」的白話解讀

這樣你就不需要先去硬啃 parquet 或原始 JSON。
