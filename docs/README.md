# AistockCN 文件索引

本目錄現在分成 3 類正式文件，分別面向不同讀者：

## 1. 面向一般使用者

- `USER_GUIDE_zh-Hant.md`
  - 正式面向使用者的產品說明書
  - 說明如何登入、看懂各頁面、如何使用 Daily Pipeline、Ranked Signals、Paper Trading 與 Admin 面板

## 2. 面向產品 / 工程 / 維運

- `SYSTEM_DESIGN_SPEC_zh-Hant.md`
  - 正式系統詳細設計書
  - 描述系統目標、範圍、架構、資料流、模組責任、部署、權限、安全、運維與風險

## 3. 面向量化系統理解與操作細節

- `SYSTEM_MANUAL_zh-Hant.md`
  - 既有的詳細說明手冊
  - 偏向「這套量化流水線每一步到底在做什麼」的技術與概念說明
  - 已補上 Daily Pipeline 實測耗時與每步驟耗時說明

## 建議閱讀順序

如果你是：

- 新使用者：先讀 `USER_GUIDE_zh-Hant.md`
- 產品經理 / 專案負責人：先讀 `SYSTEM_DESIGN_SPEC_zh-Hant.md`
- 量化研究 / 維運 / 工程同事：再讀 `SYSTEM_MANUAL_zh-Hant.md`

## 關於 Daily Job 時間

依目前系統實測，最新一次完整 Daily Pipeline 執行時間不是固定 7 小時，而是：

- 約 `6 小時 29 分`

而且絕大部分時間都花在：

- `Step 1 Data Prepare`

詳細分解請看：

- `SYSTEM_MANUAL_zh-Hant.md`
- `SYSTEM_DESIGN_SPEC_zh-Hant.md`
