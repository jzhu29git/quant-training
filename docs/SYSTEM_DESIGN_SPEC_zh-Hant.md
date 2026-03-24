# AistockCN 系統詳細設計書

版本：`v1.0`

文件定位：

- 本文件是正式的系統詳細設計書
- 面向產品、工程、維運、交付、內部審查與未來商業化包裝
- 重點不是教使用者按哪個按鈕，而是清楚定義這個系統「是什麼」、「怎麼運作」、「怎麼部署」、「怎麼維護」

---

## 1. 系統定位

### 1.1 產品一句話定義

AistockCN 是一套面向 A 股市場的量化研究與信號運營平台，將資料抓取、特徵工程、模型訓練、股票打分、回測驗證、模擬交易與控制面板整合成一條可運營的日常流水線。

### 1.2 產品目標

本系統的目標是提供一個可持續運作的量化基礎設施，而不是單一腳本集合。它要能支撐：

- 每日資料刷新
- 最新市場信號產出
- 歷史有效性驗證
- 模擬交易聯動
- 管理面板觀測與控制

### 1.3 非目標

目前系統不是：

- 直接面向券商正式實盤報單的生產交易系統
- 保證收益的投資產品
- 多市場、多資產類別的通用量化引擎
- 自動完成合規、風控、審計與對賬的一站式金融中台

---

## 2. 系統範圍

### 2.1 系統內涵蓋的核心能力

- 股票池與原始行情準備
- 估值資料補齊
- 訓練特徵生成
- 推理特徵生成
- LightGBM 二元分類模型訓練
- 最新股票池打分與排序
- Walk-forward 樣本外回測
- Futu gateway 模擬交易同步
- Web Control Panel 與 API 服務

### 2.2 每日主流程範圍

目前 Daily Pipeline 正式包含：

- Step 1 Data Prepare
- Step 2 Feature Engineering
- Step 3 Inference Features
- Step 4 Train and Score

目前 Daily Pipeline 不包含：

- Backtest

Backtest 已獨立成單獨控制項，不再阻塞每日刷新流程。

---

## 3. 使用角色

### 3.1 Viewer

- 可登入面板
- 可查看 Overview、Pipeline、Explorer、Models、Picks、Paper
- 不可啟動或停止流程
- 適合研究、觀察、業務展示、只讀審查

### 3.2 Admin

- 具備 Viewer 全部能力
- 可在 Panel 觸發 Daily Pipeline
- 可單獨啟動某一步驟
- 可啟動 / 停止 Backtest
- 可啟動 / 停止 Paper Trading
- 可進入 Admin 頁面檢查 artifact 對齊與流程漂移

---

## 4. 邏輯架構

### 4.1 邏輯分層

系統可拆成 5 層：

1. 外部資料與外部交易介面
2. 資料處理與量化計算層
3. 執行控制與調度層
4. 服務 API 層
5. Web 控制面板層

### 4.2 外部依賴

- `Baostock`
  - 主要提供股票名單與日 K 線資料
- `AKShare`
  - 補充市值與估值相關欄位
- `Futu Gateway`
  - 模擬交易同步的外部執行接口
- `Docker Compose`
  - 本地與部署環境的標準運行封裝

### 4.3 系統主要組件

- `download_data.py`
  - 原始資料下載與股票池刷新
- `feature_engineering.py`
  - 訓練特徵生成
- `build_inference_features.py`
  - 最新推理特徵生成
- `train_lightgbm.py`
  - 訓練模型與最新打分
- `backtest_walk_forward.py`
  - 歷史樣本外回測
- `paper_trade_futu.py`
  - 讀取最新分數並生成模擬交易計畫
- `paper_trade_daemon.py`
  - 持續監看 score snapshot 與同步模擬交易
- `apps/api`
  - 狀態、數據、模型、paper trading 與流程控制 API
- `apps/web`
  - Operator / User 控制面板

---

## 5. 資料流設計

### 5.1 主資料流

`外部資料源 -> 原始 parquet -> 訓練特徵 -> 推理特徵 -> 模型打分 -> 選股信號 -> 模擬交易 / 回測`

### 5.2 關鍵資料產物

- `quant_data/stock_list.parquet`
  - 活躍股票池
- `quant_data/stock_registry.parquet`
  - 歷史股票註冊表
- `quant_data/daily_kline/*.parquet`
  - 單股歷史行情
- `quant_data/daily_valuation/*.parquet`
  - 單股歷史估值
- `quant_data/ml_features_ready.parquet`
  - 訓練資料主表
- `quant_data/inference_features_latest.parquet`
  - 最新推理特徵表
- `quant_data/models/inference_scores_latest.parquet`
  - 最新打分結果
- `quant_data/models/training_metadata.json`
  - 模型訓練與驗證元資料
- `quant_data/backtests/summary.json`
  - 回測摘要
- `quant_data/paper_trading/state.json`
  - 模擬交易本地狀態
- `quant_data/paper_trading/targets_latest.parquet`
  - 最新目標持倉快照

### 5.3 資料一致性要求

系統需要持續觀察以下對齊關係：

- Step 2 特徵產物 與 活躍股票池代碼數是否一致
- Step 3 推理特徵 與 Step 4 打分代碼數是否一致
- Step 2 特徵產物 與 Backtest 使用代碼數是否一致
- 最新 score snapshot 是否已被 paper trading 消費

Admin 面板的 guardrails 與 workflow monitor 就是為這些一致性檢查而存在。

---

## 6. 每日流程設計

### 6.1 Daily Pipeline 的正式定義

Daily Pipeline 是每天產出最新交易信號的主流程，目的在於把資料從原始狀態一路刷新到最新模型分數。

### 6.2 每步驟責任

#### Step 1 Data Prepare

責任：

- 刷新股票池
- 補股票名稱與行業資料
- 下載 / 更新日 K 線
- 下載 / 更新估值資料

時間成本來源：

- 涉及全市場數千檔股票
- 受到外部資料源回應速度與限流影響
- 需要大量檔案 IO

#### Step 2 Feature Engineering

責任：

- 合併原始行情與估值表
- 計算訓練特徵
- 建立標籤欄位
- 生成 `ml_features_ready.parquet`

#### Step 3 Inference Features

責任：

- 生成最新可供模型打分的特徵快照
- 不包含未來標籤
- 生成 `inference_features_latest.parquet`

#### Step 4 Train and Score

責任：

- 使用訓練特徵重新訓練 LightGBM
- 保存模型與 metadata
- 對最新推理特徵打分
- 生成 `inference_scores_latest.parquet`

### 6.3 最新一次實測耗時

依 `2026-03-23` 啟動、`2026-03-24` 完成的最新一輪 Daily Pipeline 實測：

- Pipeline 總耗時：約 `389.44` 分鐘
- 約 `6 小時 29 分`

分步驟耗時如下：

| 步驟 | 內容 | 約耗時 |
|---|---|---:|
| Step 1 | Data Prepare | `378.75` 分鐘 |
| Step 2 | Feature Engineering | `5.34` 分鐘 |
| Step 3 | Inference Features | `3.67` 分鐘 |
| Step 4 | Train and Score | `1.67` 分鐘 |

### 6.4 正式結論

所以目前不應把 Daily Job 說成「固定 7 小時」。

更準確的說法應該是：

- 目前完整 Daily Pipeline 實測約 `6.5 小時`
- 實際時間高度取決於 Step 1 外部資料抓取
- 若外部資料源慢、限流、缺資料，Step 1 可能更長
- Step 2 到 Step 4 本身都很短，真正的瓶頸是資料準備

---

## 7. Backtest 設計

### 7.1 定位

Backtest 是驗證模型歷史有效性的獨立能力，不是每日主流程必經步驟。

### 7.2 設計原則

- 使用 walk-forward / expanding-window
- 避免把未來資料洩漏到訓練階段
- 用可重複比較的 run 形式保存結果

### 7.3 產物

- `summary.json`
- `equity_curve.parquet`
- `trade_log.parquet`
- `oos_predictions.parquet`

---

## 8. Paper Trading 設計

### 8.1 定位

Paper Trading 不是自行實作券商介面，而是站在既有 Futu gateway 之上，將最新 score snapshot 轉換成模擬委託。

### 8.2 行為模式

- daemon 持續監看 score snapshot
- 若 snapshot 沒變，則 noop
- 若 snapshot 變了，則重新生成目標持倉
- 透過 gateway 送出模擬交易

### 8.3 核心狀態檔

- `state.json`
- `targets_latest.parquet`
- `sync_history.jsonl`

---

## 9. API 與 Panel 設計

### 9.1 API 範圍

API 主要提供：

- 狀態查詢
- 日誌查看
- 資料摘要
- Data Explorer
- Model / Picks 查詢
- Paper Trading 狀態與明細
- 流程控制

### 9.2 Web Panel 範圍

Web Panel 目前主要頁面包括：

- `Overview`
- `Pipeline`
- `Explorer`
- `Models`
- `Picks`
- `Paper`
- `Admin`

### 9.3 權限模型

- Viewer：只讀
- Admin：可控流程

### 9.4 控制面板的重要設計原則

- 不只是看狀態，而是要讓 operator 看到 artifact 漂移
- 不只是顯示 log，而是要能看到每一步的容器、文件與時間
- 對使用者顯示的日期與數值應可讀，不應過度暴露機器格式

---

## 10. 部署設計

### 10.1 推薦部署方式

推薦使用 Docker Compose，原因包括：

- 環境一致
- Python / Node 依賴隔離
- 便於遷移與重建
- 容器狀態與運行時信息可被控制面板直接觀測

### 10.2 主要服務

- `data-prep` 容器
- `panel-api`
- `panel-web`
- `aistock-gateway`

### 10.3 主要運行時資料

- `logs/*.log`
- `run/*.pid`
- `quant_data/*`

---

## 11. 安全與權限設計

### 11.1 Web 登入

- 使用 Panel 使用者清單與簽名 cookie session
- 角色分為 `admin` 與 `viewer`

### 11.2 API 控制

- 控制類 API 透過 `PANEL_ADMIN_KEY` 保護
- Web 端 admin 控制動作會把 admin key 帶到 API

### 11.3 API 存取網段限制

- API 僅允許 localhost / 內部網段調用
- 降低暴露到公網後被直接調用的風險

---

## 12. 可觀測性設計

### 12.1 可觀測對象

- 容器是否在執行
- 最新 state 是否更新
- artifact 是否更新
- log 是否持續產生
- paper trading 是否仍在消費最新 score

### 12.2 觀測介面

- status API
- workflow API
- pipeline API
- Admin 頁面與 Pipeline 頁面

---

## 13. 已知瓶頸與風險

### 13.1 Step 1 時間過長

目前最大的工程瓶頸是 Step 1。

原因：

- 外部資料源速度有限
- 全市場資料量大
- 單股 parquet 寫入數量很多

### 13.2 外部資料 readiness 不穩定

自動排程即使到了預定時間，也可能因為上游資料還未就緒而跳過。

### 13.3 下游消費可能落後

最新 scores 產出後，不代表：

- Backtest 已更新
- Paper Trading 已重新消費

這就是為什麼系統需要 Admin guardrails。

---

## 14. 面向商業化的下一步

如果要把這套系統整理成真正可推出市場的產品，除了目前已完成的文檔化，下一階段通常還需要：

- 版本化的產品需求說明書
- 角色與權限矩陣
- 操作審計記錄
- 告警與通知
- 備份與恢復方案
- 多環境部署規範
- 更正式的測試與驗證基線
- 對外銷售版本的 UI 文案與品牌包裝
- 法務 / 風險揭露 / 免責聲明

本文件先把「系統設計」基礎定義清楚，作為後續產品化與市場化的骨架。
