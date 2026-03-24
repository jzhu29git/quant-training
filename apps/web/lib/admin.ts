import { PanelLocale } from "@/lib/i18n";

type WorkflowStep = {
  step: number;
  title: string;
  summary: string;
  inputs: string[];
  outputs: string[];
  anchor: string;
};

type FieldRow = {
  field: string;
  meaning: string;
  note: string;
};

type FieldSection = {
  key: string;
  title: string;
  summary: string;
  rows: FieldRow[];
};

const workflowSteps: WorkflowStep[] = [
  {
    step: 1,
    title: "Data Prepare",
    summary: "Refresh the A-share universe, maintain the canonical registry, and write raw kline plus valuation parquet artifacts.",
    inputs: ["BaoStock", "AKShare", "existing registry artifacts"],
    outputs: ["stock_registry.parquet", "stock_list.parquet", "daily_kline/*", "daily_valuation/*"],
    anchor: "batch_download_all_a.py / download_data.py"
  },
  {
    step: 2,
    title: "Training Features",
    summary: "Merge market and valuation data into the training panel and derive model labels plus engineered features.",
    inputs: ["daily_kline", "daily_valuation", "stock_list.parquet"],
    outputs: ["ml_features_ready.parquet"],
    anchor: "feature_engineering.py"
  },
  {
    step: 3,
    title: "Inference Features",
    summary: "Build the latest model input snapshot without forward-looking labels.",
    inputs: ["daily_kline", "daily_valuation", "stock_list.parquet"],
    outputs: ["inference_features_latest.parquet"],
    anchor: "build_inference_features.py"
  },
  {
    step: 4,
    title: "Train And Score",
    summary: "Train the latest LightGBM model, persist metadata, and score the most recent inference snapshot.",
    inputs: ["ml_features_ready.parquet", "inference_features_latest.parquet"],
    outputs: ["training_metadata.json", "lightgbm_model.txt", "inference_scores_latest.parquet"],
    anchor: "train_lightgbm.py"
  },
  {
    step: 5,
    title: "Backtest",
    summary: "Run profile-driven walk-forward backtests and compare saved results across model variants.",
    inputs: ["ml_features_ready.parquet", "model profiles"],
    outputs: ["backtest summary", "saved run artifacts"],
    anchor: "backtest_walk_forward.py"
  }
];

const fieldSections: FieldSection[] = [
  {
    key: "universe",
    title: "Universe And Registry",
    summary: "Core identity and lifecycle fields used to track the current tradable universe and registry history.",
    rows: [
      { field: "code", meaning: "Six-digit stock code.", note: "Primary join key across pipeline artifacts." },
      { field: "exchange", meaning: "Exchange slug such as sh or sz.", note: "Used together with code when merging data." },
      { field: "industry", meaning: "Industry context label.", note: "Also used as a categorical model feature." },
      { field: "trade_date", meaning: "Universe snapshot date.", note: "Represents the sync date of the current batch." }
    ]
  },
  {
    key: "raw_market_data",
    title: "Raw Market Data",
    summary: "Stable raw inputs used by feature engineering and downstream scoring.",
    rows: [
      { field: "open / high / low / close", meaning: "Daily OHLC prices.", note: "Base inputs for momentum and price-relative features." },
      { field: "volume / amount", meaning: "Share volume and turnover amount.", note: "Used for liquidity and activity features." },
      { field: "turnover / amplitude", meaning: "Turnover ratio and daily range measures.", note: "Useful for volatility and trading-intensity signals." },
      { field: "total_market_cap / float_market_cap", meaning: "Size metrics from valuation data.", note: "Stable valuation features preserved in the cleaned schema." }
    ]
  },
  {
    key: "engineered_features",
    title: "Engineered Features",
    summary: "Representative derived fields created before training and scoring.",
    rows: [
      { field: "ma5 / ma20", meaning: "Moving-average anchors.", note: "Used to normalize price context." },
      { field: "pct_chg_5d / pct_chg_20d", meaning: "Medium-term price change features.", note: "Core momentum signals." },
      { field: "volatility_20d", meaning: "Rolling realized volatility.", note: "Adds risk-sensitive context to price action." },
      { field: "future_return / label", meaning: "Forward return and binary target.", note: "Present in training artifacts only, never inference artifacts." }
    ]
  }
];

export function getAdminCatalog(_locale: PanelLocale) {
  return {
    title: "Admin Control Room",
    subtitle: "See the whole quant workflow in one place: artifact alignment, runtime health, and the field families used by each step.",
    labels: {
      field: "Field",
      meaning: "Meaning",
      note: "Note",
      inputs: "Inputs",
      outputs: "Outputs",
      liveArtifact: "Current artifact",
      currentGuardrails: "Current Guardrails",
      runtime: "Runtime Snapshot",
      workflow: "Workflow Map",
      catalog: "Field Catalog",
      aligned: "Aligned",
      checkNeeded: "Check needed",
      modelStillLegacy: "Saved model still carries legacy fields.",
      modelClean: "Saved model feature list matches the cleaned schema."
    },
    workflowSteps,
    fieldSections
  };
}
