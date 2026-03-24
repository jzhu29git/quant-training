import { PanelLocale } from "@/lib/i18n";

type LocalizedText = Record<PanelLocale, string>;

type WorkflowStep = {
  step: number;
  title: LocalizedText;
  summary: LocalizedText;
  inputs: string[];
  outputs: string[];
  anchor: string;
};

type FieldRow = {
  field: string;
  meaning: LocalizedText;
  note: LocalizedText;
};

type FieldSection = {
  key: string;
  title: LocalizedText;
  summary: LocalizedText;
  rows: FieldRow[];
};

function t(locale: PanelLocale, value: LocalizedText) {
  return value[locale];
}

const workflowSteps: WorkflowStep[] = [
  {
    step: 1,
    title: {
      en: "Data Prepare",
      "zh-Hant": "資料準備"
    },
    summary: {
      en: "Fetch the latest full A-share universe, refresh the canonical registry and active stock list, then download the raw kline and valuation parquet files.",
      "zh-Hant": "抓取最新全市場 A 股名單，刷新主註冊表與活躍股票池，接著下載原始 K 線與估值 parquet 檔。"
    },
    inputs: ["latest all-A universe", "stock_registry.parquet", "BaoStock / AkShare"],
    outputs: ["stock_registry.parquet", "stock_list.parquet", "stock_list_subset.parquet", "quant_data/daily_kline/*.parquet", "quant_data/daily_valuation/*.parquet"],
    anchor: "batch_download_all_a.py / download_data.py"
  },
  {
    step: 2,
    title: {
      en: "Training Features",
      "zh-Hant": "訓練特徵工程"
    },
    summary: {
      en: "Merge raw kline plus valuation data into the canonical training panel and build derived labels/features.",
      "zh-Hant": "把原始 K 線與估值資料合併成訓練面板，並產生衍生特徵與標籤。"
    },
    inputs: ["daily_kline", "daily_valuation", "stock_list.parquet"],
    outputs: ["quant_data/ml_features_ready.parquet"],
    anchor: "feature_engineering.py"
  },
  {
    step: 3,
    title: {
      en: "Inference Features",
      "zh-Hant": "推理特徵工程"
    },
    summary: {
      en: "Build the latest per-stock feature snapshot without future labels for scoring and ranking.",
      "zh-Hant": "產生不含未來標籤的最新單股特徵快照，用於打分與排序。"
    },
    inputs: ["daily_kline", "daily_valuation", "stock_list.parquet"],
    outputs: ["quant_data/inference_features_latest.parquet"],
    anchor: "build_inference_features.py"
  },
  {
    step: 4,
    title: {
      en: "Train And Score",
      "zh-Hant": "模型訓練與打分"
    },
    summary: {
      en: "Train the latest LightGBM model, save metadata, and score the newest inference snapshot.",
      "zh-Hant": "訓練最新 LightGBM 模型、保存訓練資訊，並對最新推理快照打分。"
    },
    inputs: ["ml_features_ready.parquet", "inference_features_latest.parquet"],
    outputs: ["training_metadata.json", "lightgbm_model.txt", "inference_scores_latest.parquet"],
    anchor: "train_lightgbm.py"
  },
  {
    step: 5,
    title: {
      en: "Backtest",
      "zh-Hant": "Backtest"
    },
    summary: {
      en: "Run profile-based backtests and compare rolling out-of-sample portfolio metrics across model variants.",
      "zh-Hant": "用不同模型 profile 執行回測，並比較滾動樣本外投組指標。"
    },
    inputs: ["ml_features_ready.parquet", "training config"],
    outputs: ["quant_data/backtests/summary.json", "backtest artifacts"],
    anchor: "backtest_walk_forward.py"
  }
];

const fieldSections: FieldSection[] = [
  {
    key: "registry",
    title: {
      en: "Universe And Registry Fields",
      "zh-Hant": "股票池與主註冊表字段"
    },
    summary: {
      en: "The canonical stock universe keeps current tradable rows separate from long-lived registry history.",
      "zh-Hant": "主股票池把目前可交易名單與長期保留的註冊歷史分開管理。"
    },
    rows: [
      {
        field: "code",
        meaning: { en: "Six-digit stock code.", "zh-Hant": "六位數股票代碼。" },
        note: { en: "Key join field across all artifacts.", "zh-Hant": "所有產物之間的主要關聯鍵。" }
      },
      {
        field: "exchange",
        meaning: { en: "Exchange slug such as sh or sz.", "zh-Hant": "交易所代碼，例如 sh 或 sz。" },
        note: { en: "Used together with code when merging.", "zh-Hant": "合併資料時會與 code 一起使用。" }
      },
      {
        field: "name",
        meaning: { en: "Display name of the stock.", "zh-Hant": "股票名稱。" },
        note: { en: "Used for panel display and score outputs.", "zh-Hant": "用於面板顯示與打分結果。" }
      },
      {
        field: "industry",
        meaning: { en: "Industry label used as context and categorical feature.", "zh-Hant": "行業標籤，作為上下文與類別特徵。" },
        note: { en: "Missing values are filled during stock-list refresh.", "zh-Hant": "股票池刷新時會補缺失值。" }
      },
      {
        field: "industry_classification",
        meaning: { en: "Industry source/classification marker.", "zh-Hant": "行業來源或分類標記。" },
        note: { en: "Tracks where industry tagging came from.", "zh-Hant": "用來標示行業欄位的來源。" }
      },
      {
        field: "trade_date",
        meaning: { en: "Universe snapshot trade date.", "zh-Hant": "股票池快照對應的交易日期。" },
        note: { en: "Represents the batch sync date.", "zh-Hant": "代表這次 batch 同步的日期。" }
      },
      {
        field: "universe",
        meaning: { en: "Universe source such as all or subset.", "zh-Hant": "股票池來源，例如 all 或 subset。" },
        note: { en: "Subset runs are isolated from the canonical active list.", "zh-Hant": "子集測試不會再覆寫正式活躍列表。" }
      },
      {
        field: "is_active",
        meaning: { en: "Whether the stock is still in the current active universe.", "zh-Hant": "該股票是否仍屬於目前活躍股票池。" },
        note: { en: "Stored in stock_registry.parquet.", "zh-Hant": "保存在 stock_registry.parquet。" }
      },
      {
        field: "first_seen_date",
        meaning: { en: "First date the code appeared in the registry.", "zh-Hant": "代碼首次出現在主註冊表的日期。" },
        note: { en: "Useful for IPO tracking and audits.", "zh-Hant": "方便追蹤新上市與審計。" }
      },
      {
        field: "last_seen_date / inactive_date",
        meaning: { en: "Last active date and inactive marker for removed names.", "zh-Hant": "最後活躍日期與停用日期標記。" },
        note: { en: "Used instead of hard-deleting history.", "zh-Hant": "用來保留歷史，而不是直接硬刪除。" }
      }
    ]
  },
  {
    key: "kline",
    title: {
      en: "Raw Daily Kline Fields",
      "zh-Hant": "原始日 K 線字段"
    },
    summary: {
      en: "Per-stock market data downloaded into quant_data/daily_kline.",
      "zh-Hant": "下載到 quant_data/daily_kline 的逐檔市場行情資料。"
    },
    rows: [
      {
        field: "date",
        meaning: { en: "Trading date.", "zh-Hant": "交易日期。" },
        note: { en: "Primary time index.", "zh-Hant": "主要時間索引。" }
      },
      {
        field: "open / high / low / close",
        meaning: { en: "OHLC prices.", "zh-Hant": "開高低收價格。" },
        note: { en: "Core price inputs for momentum features.", "zh-Hant": "動量類特徵的核心價格輸入。" }
      },
      {
        field: "volume / amount",
        meaning: { en: "Share volume and turnover amount.", "zh-Hant": "成交量與成交額。" },
        note: { en: "Used for liquidity and volume features.", "zh-Hant": "用於流動性與成交量特徵。" }
      },
      {
        field: "turnover",
        meaning: { en: "Turnover ratio.", "zh-Hant": "換手率。" },
        note: { en: "Used directly and in rolling averages.", "zh-Hant": "會直接使用，也會進入移動平均特徵。" }
      },
      {
        field: "amplitude",
        meaning: { en: "Intraday amplitude.", "zh-Hant": "日內振幅。" },
        note: { en: "Current saved model ranks it highly.", "zh-Hant": "目前保存的模型中它的重要性很高。" }
      },
      {
        field: "pct_chg / change",
        meaning: { en: "Percentage change and absolute price change.", "zh-Hant": "漲跌幅與漲跌額。" },
        note: { en: "Used in raw panel inputs and return features.", "zh-Hant": "會進入原始面板與報酬相關特徵。" }
      }
    ]
  },
  {
    key: "valuation",
    title: {
      en: "Raw Valuation Fields",
      "zh-Hant": "原始估值字段"
    },
    summary: {
      en: "The stable valuation schema currently supported by the downloader and training pipeline.",
      "zh-Hant": "目前下載器與訓練流程正式支持的穩定估值 schema。"
    },
    rows: [
      {
        field: "close_val / pct_chg_val",
        meaning: { en: "Valuation-table close and percentage change after merge.", "zh-Hant": "合併後來自估值表的收盤價與漲跌幅。" },
        note: { en: "Separated from kline columns after merge.", "zh-Hant": "與 K 線同名欄位分開保存。" }
      },
      {
        field: "total_market_cap / float_market_cap",
        meaning: { en: "Total and float market capitalization.", "zh-Hant": "總市值與流通市值。" },
        note: { en: "Used directly in current training features.", "zh-Hant": "目前會直接進入訓練特徵。" }
      },
      {
        field: "total_shares / float_shares",
        meaning: { en: "Total and float share count.", "zh-Hant": "總股本與流通股本。" },
        note: { en: "Useful for size and float structure.", "zh-Hant": "反映公司規模與流通結構。" }
      },
      {
        field: "pe_ttm",
        meaning: { en: "Trailing-twelve-month PE.", "zh-Hant": "滾動十二個月市盈率。" },
        note: { en: "Stable and currently supported.", "zh-Hant": "穩定且目前正式支持。" }
      },
      {
        field: "pb / ps / pcf",
        meaning: { en: "Price-to-book, price-to-sales, and price-to-cash-flow.", "zh-Hant": "市淨率、市銷率與市現率。" },
        note: { en: "Stable valuation factors in the current pipeline.", "zh-Hant": "目前流程中的穩定估值因子。" }
      }
    ]
  },
  {
    key: "panel",
    title: {
      en: "Unified Training Panel Fields",
      "zh-Hant": "統一訓練面板字段"
    },
    summary: {
      en: "These are the canonical raw columns preserved after kline plus valuation merge before feature derivation.",
      "zh-Hant": "這些是 K 線與估值合併後、特徵衍生之前保留下來的正式原始欄位。"
    },
    rows: [
      {
        field: "date / code / exchange",
        meaning: { en: "Primary keys for time-series panel rows.", "zh-Hant": "時序面板的主索引鍵。" },
        note: { en: "Used to sort and group each stock.", "zh-Hant": "用來排序與分組每一檔股票。" }
      },
      {
        field: "open / high / low / close",
        meaning: { en: "Price columns from the kline dataset.", "zh-Hant": "來自 K 線資料的價格欄位。" },
        note: { en: "Form the base of moving averages and return features.", "zh-Hant": "是均線與報酬特徵的基礎。" }
      },
      {
        field: "volume / amount / turnover / amplitude",
        meaning: { en: "Trading activity and range measures.", "zh-Hant": "交易活躍度與波動範圍相關欄位。" },
        note: { en: "Feed liquidity and volatility features.", "zh-Hant": "餵給流動性與波動率特徵。" }
      },
      {
        field: "pct_chg / change",
        meaning: { en: "Raw price move signals from kline.", "zh-Hant": "K 線中的原始價格變動訊號。" },
        note: { en: "Kept as direct model inputs too.", "zh-Hant": "也會直接作為模型輸入。" }
      },
      {
        field: "close_val / pct_chg_val",
        meaning: { en: "Close and pct change from the valuation source.", "zh-Hant": "來自估值來源的收盤價與漲跌幅。" },
        note: { en: "Helpful for schema consistency checks.", "zh-Hant": "也能幫助驗證兩個來源的一致性。" }
      },
      {
        field: "total_market_cap / float_market_cap / total_shares / float_shares",
        meaning: { en: "Size and share-structure inputs.", "zh-Hant": "規模與股本結構輸入。" },
        note: { en: "Stable full-market fields after the cleanup.", "zh-Hant": "清理後仍保留的穩定全市場字段。" }
      },
      {
        field: "pe_ttm / pb / ps / pcf",
        meaning: { en: "Stable valuation inputs kept in the official schema.", "zh-Hant": "正式 schema 中保留的穩定估值輸入。" },
        note: { en: "These are the valuation ratios still used in step 2 and step 3.", "zh-Hant": "它們仍會在 step 2 和 step 3 中使用。" }
      },
      {
        field: "name / industry",
        meaning: { en: "Context columns merged from stock_list.parquet.", "zh-Hant": "從 stock_list.parquet 合併進來的上下文欄位。" },
        note: { en: "Industry is also a categorical model feature.", "zh-Hant": "其中 industry 也是模型的類別特徵。" }
      }
    ]
  },
  {
    key: "derived",
    title: {
      en: "Derived Training Features",
      "zh-Hant": "衍生訓練特徵"
    },
    summary: {
      en: "Rolling and relative features generated inside feature_engineering.py.",
      "zh-Hant": "在 feature_engineering.py 中產生的滾動與相對位置特徵。"
    },
    rows: [
      {
        field: "ma5 / ma20",
        meaning: { en: "5-day and 20-day moving averages.", "zh-Hant": "5 日與 20 日均線。" },
        note: { en: "Trend anchors for price normalization.", "zh-Hant": "作為價格標準化與趨勢參考。" }
      },
      {
        field: "bias_20",
        meaning: { en: "Close divided by MA20 minus 1.", "zh-Hant": "收盤價相對 20 日均線的偏離。" },
        note: { en: "Captures short-term overextension.", "zh-Hant": "用來反映短期偏離程度。" }
      },
      {
        field: "pct_chg_5d / pct_chg_20d",
        meaning: { en: "5-day and 20-day price change features.", "zh-Hant": "5 日與 20 日價格變動特徵。" },
        note: { en: "Core medium-term momentum signals.", "zh-Hant": "中期動量訊號的重要部分。" }
      },
      {
        field: "volatility_20d",
        meaning: { en: "20-day rolling close volatility normalized by MA20.", "zh-Hant": "20 日滾動波動率，再以 MA20 標準化。" },
        note: { en: "Measures realized volatility.", "zh-Hant": "用來衡量實現波動率。" }
      },
      {
        field: "turnover_ma5 / volume_ma5",
        meaning: { en: "5-day rolling averages for turnover and volume.", "zh-Hant": "換手率與成交量的 5 日移動平均。" },
        note: { en: "Smooths noisy trading activity.", "zh-Hant": "平滑短期交易噪音。" }
      },
      {
        field: "close_to_high_20d / close_to_low_20d",
        meaning: { en: "Relative position versus the 20-day range extremes.", "zh-Hant": "相對 20 日區間高低點的位置。" },
        note: { en: "Useful for breakout or mean-reversion context.", "zh-Hant": "可描述突破或均值回歸背景。" }
      },
      {
        field: "future_return / label",
        meaning: { en: "Forward return and the binary training target.", "zh-Hant": "未來報酬與二元訓練標籤。" },
        note: { en: "Only present in step 2 training data, not inference.", "zh-Hant": "只會出現在 step 2 訓練資料，不會進入推理。" }
      }
    ]
  },
  {
    key: "legacy",
    title: {
      en: "Legacy Fields Excluded From The Official Schema",
      "zh-Hant": "已排除的舊版字段"
    },
    summary: {
      en: "These fields existed in only part of the historical valuation parquet files and caused training-universe collapse when treated as required.",
      "zh-Hant": "這些字段只存在於部分歷史估值 parquet 檔，若把它們當成必填欄位，會讓訓練股票池大幅縮水。"
    },
    rows: [
      {
        field: "pe_static",
        meaning: { en: "Static PE based on a fixed reporting period.", "zh-Hant": "基於固定報表期的靜態市盈率。" },
        note: { en: "Not generated by the current downloader.", "zh-Hant": "目前下載器不會統一生成它。" }
      },
      {
        field: "peg",
        meaning: { en: "PE divided by earnings-growth proxy.", "zh-Hant": "PE 與盈利增長率關係的 PEG。" },
        note: { en: "Also not generated consistently in the current pipeline.", "zh-Hant": "目前流程裡也沒有穩定一致地生成。" }
      }
    ]
  }
];

export function getAdminCatalog(locale: PanelLocale) {
  return {
    title: t(locale, {
      en: "Admin Control Room",
      "zh-Hant": "管理控制室"
    }),
    subtitle: t(locale, {
      en: "See the whole quant workflow in one place: current system state, live artifact alignment, and the exact fields each step uses.",
      "zh-Hant": "把整個量化工作流程放在同一頁：目前系統狀態、產物是否一致，以及每個 step 實際使用的字段。"
    }),
    labels: {
      field: t(locale, { en: "Field", "zh-Hant": "字段" }),
      meaning: t(locale, { en: "Meaning", "zh-Hant": "說明" }),
      note: t(locale, { en: "Note", "zh-Hant": "備註" }),
      inputs: t(locale, { en: "Inputs", "zh-Hant": "輸入" }),
      outputs: t(locale, { en: "Outputs", "zh-Hant": "輸出" }),
      liveArtifact: t(locale, { en: "Current artifact", "zh-Hant": "目前產物" }),
      currentGuardrails: t(locale, { en: "Current Guardrails", "zh-Hant": "目前守門資訊" }),
      runtime: t(locale, { en: "Runtime Snapshot", "zh-Hant": "執行狀態快照" }),
      workflow: t(locale, { en: "Workflow Map", "zh-Hant": "工作流程地圖" }),
      catalog: t(locale, { en: "Field Catalog", "zh-Hant": "字段字典" }),
      aligned: t(locale, { en: "Aligned", "zh-Hant": "一致" }),
      checkNeeded: t(locale, { en: "Check needed", "zh-Hant": "需要檢查" }),
      modelStillLegacy: t(locale, { en: "Saved model still carries legacy fields.", "zh-Hant": "目前保存的模型仍帶有舊版字段。" }),
      modelClean: t(locale, { en: "Saved model feature list matches the cleaned schema.", "zh-Hant": "目前保存的模型特徵已符合清理後的 schema。" })
    },
    workflowSteps: workflowSteps.map((step) => ({
      ...step,
      title: t(locale, step.title),
      summary: t(locale, step.summary)
    })),
    fieldSections: fieldSections.map((section) => ({
      key: section.key,
      title: t(locale, section.title),
      summary: t(locale, section.summary),
      rows: section.rows.map((row) => ({
        field: row.field,
        meaning: t(locale, row.meaning),
        note: t(locale, row.note)
      }))
    }))
  };
}
