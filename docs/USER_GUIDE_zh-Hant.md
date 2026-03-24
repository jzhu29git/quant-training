# AistockCN 使用者說明書

版本：`v1.0`

本文件是正式面向使用者的說明書，目標是讓使用者能夠：

- 知道這個系統能做什麼
- 看懂每個頁面代表什麼
- 正確理解 Daily Pipeline、Ranked Signals、Backtest、Paper Trading
- 知道哪些結果可以拿來輔助決策，哪些不能直接當成保證收益

---

## 1. 這套系統是什麼

AistockCN 是一套 A 股量化信號平台。

它每天會做幾件事：

- 更新股票池與行情資料
- 產生模型特徵
- 訓練模型
- 對最新股票池打分
- 輸出排序後的選股信號
- 視情況同步到模擬交易

你可以把它理解成：

- 一個會每天刷新資料的量化研究平台
- 一個會把股票依模型分數排序的信號系統
- 一個帶管理面板的 operator tool

---

## 2. 先理解兩件最重要的事

### 2.1 `score` 不是目標價

系統中的 `score` 不是：

- 目標價
- 明天會漲幾%
- 保證獲利機率

它比較接近：

- 模型認為這檔股票在定義好的預測窗口內，較可能達成目標報酬條件的相對強弱分數

### 2.2 Ranked Signals 是排序工具，不是保證買進名單

`Ranked Signals` 的用途是：

- 幫你快速看到目前模型最看好的股票
- 作為研究、複核、討論、模擬交易輸入的基礎

它不是：

- 無條件必買清單
- 已完成風控後的正式交易指令

---

## 3. 登入與角色

系統目前有兩種角色：

### 3.1 Viewer

- 可以查看所有主要頁面
- 不可啟動或停止流程

### 3.2 Admin

- 可以查看所有頁面
- 可以啟動 / 停止 Daily Pipeline
- 可以單獨跑 Backtest
- 可以啟動 / 停止 Paper Trading
- 可以使用 Admin 頁面的 guardrails 與 live monitor

---

## 4. 主導航頁面說明

登入後你會看到這些主要頁面：

- `Overview`
- `Pipeline`
- `Explorer`
- `Models`
- `Picks`
- `Paper`
- `Admin`

下面分別說明。

---

## 5. Overview 頁

### 5.1 這頁在做什麼

Overview 是整套系統的總覽頁。

適合用來：

- 快速確認系統是否活著
- 看當前資料量
- 看最新是否已有推理結果
- 看最新訓練驗證結果

### 5.2 你會看到什麼

- `Batch Status`
- `Progress`
- `Data Files`
- `Top Picks`
- `Validation AUC`

### 5.3 怎麼解讀

- `Batch Status`
  - 看主流程是否在跑
- `Progress`
  - 看目前進度
- `Data Files`
  - 看資料量級是否正常
- `Top Picks`
  - 看是否已有最新信號結果
- `Validation AUC`
  - 看模型近期驗證效果是否穩定

---

## 6. Pipeline 頁

### 6.1 這頁在做什麼

Pipeline 頁是日常營運的控制中心。

你可以在這裡：

- 看 Daily Pipeline 現在是否在跑
- 看每一步的 artifact 與 log
- 啟動 / 停止各步驟
- 單獨跑 Backtest
- 啟動 / 停止 Paper Trading

### 6.2 Daily Pipeline 包含哪些步驟

目前 Daily Pipeline 正式包含：

- Step 1 Data Prepare
- Step 2 Feature Engineering
- Step 3 Inference Features
- Step 4 Train and Score

Backtest 是獨立控制項，不包含在每日主流程中。

### 6.3 現在 Daily Job 要多久

依最新一次完整實測：

- 約 `6 小時 29 分`

而且大部分時間都花在：

- `Step 1 Data Prepare`

所以目前更準確的說法是：

- Daily Job 約 `6.5 小時`
- 不應說成固定 `7 小時`

### 6.4 每一步在做什麼

#### Step 1 Data Prepare

- 刷新股票池
- 下載 / 更新日 K 線
- 下載 / 更新估值資料
- 這一步最慢

#### Step 2 Feature Engineering

- 產生模型訓練用特徵

#### Step 3 Inference Features

- 產生最新推理特徵快照

#### Step 4 Train and Score

- 重新訓練模型
- 對最新股票池打分

#### Backtest

- 驗證模型過去歷史是否有效
- 不屬於 Daily Pipeline 主線

#### Auto Paper Trading

- 監看最新 score snapshot
- 嘗試把信號同步到模擬交易

### 6.5 什麼時候應該看這頁

- 每日開盤前或收盤後確認資料是否刷新
- 模型更新後確認 score 是否已生成
- 確認某步驟是否失敗
- 確認 Backtest 是否已更新

---

## 7. Explorer 頁

### 7.1 這頁在做什麼

Explorer 是面向研究與排查的資料查詢頁。

它讓你：

- 直接查看 parquet dataset
- 搜尋股票
- 篩欄位
- 排序
- 匯出資料

### 7.2 適合的使用場景

- 查某檔股票最近是否真的被打分
- 確認某欄位是否存在
- 快速做 ad-hoc 查詢
- 導出某個 dataset 做離線分析

### 7.3 不適合的使用場景

- 不適合拿來做正式報表系統
- 不適合當大規模 BI 平台

---

## 8. Models 頁

### 8.1 這頁在做什麼

Models 頁專門顯示：

- 目前模型驗證表現
- 訓練樣本量
- 回測摘要
- Backtest run 比較
- 特徵重要性

### 8.2 你最應該看哪幾個指標

- `AUC`
- `Accuracy`
- `Train Rows`
- `Valid Rows`
- `Backtest Total Return`
- `Backtest CAGR`
- `Backtest Max Drawdown`

### 8.3 怎麼解讀

- `AUC`
  - 看模型排序能力是否高於隨機
- `Accuracy`
  - 僅能輔助看，不應單獨判斷模型好壞
- `Max Drawdown`
  - 幫助理解策略過去曾承受多大回撤
- `Feature Importance`
  - 看模型主要依賴哪些特徵

---

## 9. Picks 頁

### 9.1 這頁在做什麼

Picks 頁是最接近「使用者每天會重度使用」的核心頁面之一。

這裡會直接顯示：

- 最新打分日期
- 目前展示的高分股票
- Ranked Signals 表格

### 9.2 Ranked Signals 怎麼看

現在表格中會清楚顯示：

- `預測時間`
- `當時股價`

還有：

- 排名
- 股票代碼
- 股票名稱
- 產業
- 模型分數

### 9.3 使用方式

建議你把這頁當成：

- 每日信號審核頁
- 投資討論頁
- 模擬交易前的人工複核頁

---

## 10. Paper 頁

### 10.1 這頁在做什麼

Paper 頁面是模擬交易控制與觀察頁。

你可以看到：

- daemon 是否在跑
- gateway 是否健康
- 最新信號日期
- 最新目標持倉
- 最近委託
- 同步歷史

### 10.2 你應該關注什麼

- `Latest Signal`
  - 是否已跟上最新 score
- `Last Sync`
  - 最近一次同步是否成功
- `Open Orders`
  - 是否還有未完成委託
- `Sync History`
  - 是否反覆出現同類型錯誤

### 10.3 重要提醒

Paper Trading 是模擬交易，不代表：

- 實盤一定能成交
- 成交價格一定相同
- 交易限制、漲跌停、最小單位問題已完全被消除

---

## 11. Admin 頁

### 11.1 這頁是給誰用的

Admin 頁只給管理員使用。

### 11.2 這頁的核心價值

它不是只是「多一頁管理頁」，而是用來檢查系統是否一致。

重點包括：

- 最新股票池與 Step 2 是否對齊
- Step 3 與 Step 4 代碼數是否對齊
- 最新 features、scores、backtest 是否對齊
- 哪些 artifact 漂移了

### 11.3 什麼時候一定要看 Admin

- Daily Pipeline 跑完後
- 懷疑 score 與 backtest 不一致時
- 懷疑 paper trading 還在吃舊 snapshot 時

---

## 12. 建議的日常操作流程

### 12.1 只讀使用者

建議每天：

1. 看 `Overview`
2. 看 `Pipeline`
3. 看 `Picks`
4. 視需要看 `Models`

### 12.2 Admin

建議每天：

1. 確認上游資料是否 ready
2. 執行或確認 `Daily Pipeline`
3. 到 `Admin` 檢查一致性
4. 到 `Picks` 檢查 Ranked Signals
5. 視需要啟動 `Paper Trading`
6. 視需要單獨執行 `Backtest`

---

## 13. 常見問題

### 13.1 為什麼 Daily Job 要跑這麼久

因為目前最大瓶頸在：

- 全市場資料抓取
- 外部資料源速度
- 大量 parquet 檔案 IO

不是模型訓練太慢。

### 13.2 為什麼今天到了排程時間還沒跑

可能原因：

- 上游 market data 還沒 ready
- 系統判斷今天資料還不完整，所以延後或跳過

### 13.3 為什麼有最新 scores，但 paper trading 沒更新

因為 score 產出，不代表下游已消費。

仍需要確認：

- daemon 是否在跑
- gateway 是否健康
- targets 是否已更新到最新 signal date

---

## 14. 風險揭露

本系統提供的是量化研究、排序與模擬執行能力，不是收益保證系統。

使用者需要理解：

- 模型表現可能失效
- 回測不代表未來績效
- 模擬交易不等於實盤交易
- 外部資料品質會影響結果

在任何對外商業化場景中，都應搭配正式風險揭露、免責聲明與合規審查。
